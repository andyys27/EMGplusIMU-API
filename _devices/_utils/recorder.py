"""Herramientas de sincronización, alineación y grabación en streaming."""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .clock import HostClock


# ---------------------------------------------------------------- sincronía
def _envelope(s: pd.Series, fs: float, smooth_ms: float = 50.0) -> pd.Series:
    """Envolvente rectificada + suavizada (comparable entre equipos distintos)."""
    x = s.astype(float)
    x = (x - x.mean()).abs()
    win = max(1, int(fs * smooth_ms / 1000))
    return x.rolling(win, min_periods=1).mean()


def estimate_lag(df_a: pd.DataFrame, col_a: str,
                 df_b: pd.DataFrame, col_b: str,
                 fs: float = 250.0, max_lag_s: float = 1.0) -> pd.Timedelta:
    """Retardo de B respecto a A por correlación cruzada de envolventes.

    Resultado > 0  => B llega DESPUÉS de A. Para corregir: ``shift_index(df_b, -lag)``.
    Haz que ambos midan la misma contracción (p. ej. 3 contracciones fuertes al inicio).
    """
    step = pd.Timedelta(seconds=1.0 / fs)
    t0 = max(df_a.index.min(), df_b.index.min())
    t1 = min(df_a.index.max(), df_b.index.max())
    grid = pd.date_range(t0, t1, freq=step)
    if len(grid) < 10:
        raise ValueError("Solapamiento insuficiente entre señales")

    def on_grid(df, col):
        e = _envelope(df[col], fs)
        e = e[~e.index.duplicated()].sort_index()
        return e.reindex(e.index.union(grid)).interpolate("time").reindex(grid).to_numpy()

    a, b = on_grid(df_a, col_a), on_grid(df_b, col_b)
    a = (a - a.mean()) / (a.std() + 1e-12)
    b = (b - b.mean()) / (b.std() + 1e-12)
    n = len(a)
    nfft = 1 << (2 * n - 1).bit_length()
    xc = np.fft.irfft(np.fft.rfft(a, nfft).conj() * np.fft.rfft(b, nfft), nfft)
    xc = np.concatenate([xc[-(n - 1):], xc[:n]])
    lags = np.arange(-(n - 1), n)
    m = np.abs(lags) <= int(max_lag_s * fs)
    best = lags[m][np.argmax(xc[m])]
    return pd.Timedelta(best * step)


def shift_index(df: pd.DataFrame, delta: pd.Timedelta) -> pd.DataFrame:
    out = df.copy()
    out.index = out.index + delta
    return out


def align(dfs: Dict[str, pd.DataFrame], fs: float = 500.0,
          method: str = "time") -> pd.DataFrame:
    """Une varios DataFrames en una malla común (DatetimeIndex uniforme).

    Columnas resultantes: ``<nombre>.<columna>``. Interpola en el tiempo (no
    extrapola fuera del rango de cada dispositivo).
    """
    dfs = {k: v for k, v in dfs.items() if v is not None and not v.empty}
    if not dfs:
        return pd.DataFrame()
    t0 = max(d.index.min() for d in dfs.values())
    t1 = min(d.index.max() for d in dfs.values())
    grid = pd.date_range(t0, t1, freq=pd.Timedelta(seconds=1.0 / fs), name="Timestamp")
    parts = []
    for name, d in dfs.items():
        d = d[~d.index.duplicated()].sort_index().select_dtypes("number")
        r = d.reindex(d.index.union(grid)).interpolate(method, limit_area="inside").reindex(grid)
        r.columns = [f"{name}.{c}" for c in r.columns]
        parts.append(r)
    return pd.concat(parts, axis=1)


# ---------------------------------------------------------------- grabación
class StreamRecorder:
    """Escribe a disco de forma incremental (sobrevive a cierres inesperados).

    rec = StreamRecorder({"mio": dev, "free": fr}, "sesion01")
    rec.start(); rec.mark("reposo"); ...; rec.mark("contraccion"); rec.stop()

    Genera: <dir>/<nombre>_<dispositivo>.csv, <nombre>_events.csv, <nombre>_meta.json
    """

    def __init__(self, devices: Dict[str, object], name: str,
                 out_dir: str = "recordings", interval_s: float = 1.0) -> None:
        self.devices = devices
        self.dir = out_dir
        self.name = name
        self.interval = interval_s
        self._last: Dict[str, Optional[pd.Timestamp]] = {k: None for k in devices}
        self._hdr: Dict[str, bool] = {k: False for k in devices}
        self._events: List[dict] = []
        self._stop = threading.Event()
        self._th: Optional[threading.Thread] = None
        os.makedirs(out_dir, exist_ok=True)

    def _path(self, suffix: str) -> str:
        return os.path.join(self.dir, f"{self.name}_{suffix}")

    def mark(self, label: str) -> pd.Timestamp:
        """Marcador de evento con el reloj común (útil para sincronizar y etiquetar)."""
        t = HostClock.now()
        self._events.append({"Timestamp": t, "label": label})
        pd.DataFrame([{"Timestamp": t, "label": label}]).to_csv(
            self._path("events.csv"), mode="a",
            header=not os.path.exists(self._path("events.csv")), index=False)
        return t

    def _flush(self) -> None:
        for k, dev in self.devices.items():
            try:
                df = dev.get_all_data()
            except Exception as e:
                print(f"[Recorder] {k}: {e}")
                continue
            if df is None or df.empty:
                continue
            if self._last[k] is not None:
                df = df[df.index > self._last[k]]
            if df.empty:
                continue
            df.to_csv(self._path(f"{k}.csv"), mode="a",
                      header=not self._hdr[k], index_label="Timestamp")
            self._hdr[k] = True
            self._last[k] = df.index[-1]

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self._flush()

    def start(self) -> None:
        self._stop.clear()
        self._th = threading.Thread(target=self._loop, daemon=True)
        self._th.start()

    def stop(self) -> None:
        self._stop.set()
        if self._th:
            self._th.join(timeout=self.interval + 1)
        self._flush()
        meta = {"name": self.name, "ended": str(HostClock.now()),
                "devices": {}}
        for k, dev in self.devices.items():
            clk = getattr(dev, "clock", None)
            meta["devices"][k] = (dev.sync_report() if hasattr(dev, "sync_report")
                                  else {"class": type(dev).__name__})
        with open(self._path("meta.json"), "w") as f:
            json.dump(meta, f, indent=2, default=str)


# ------------------------------------------------------------ calidad datos
def quality_report(df: pd.DataFrame, fs_nominal: float) -> dict:
    """Huecos, jitter y Fs efectiva de un DataFrame con DatetimeIndex."""
    if df.empty or len(df) < 3:
        return {}
    dt = np.diff(df.index.values1).astype("timedelta64[ns]").astype(np.int64) / 1e9
    nominal = 1.0 / fs_nominal
    return {
        "fs_effective": float(1.0 / np.median(dt)),
        "jitter_std_ms": float(np.std(dt) * 1e3),
        "gaps_>2x": int(np.sum(dt > 2 * nominal)),
        "max_gap_ms": float(dt.max() * 1e3),
        "monotonic": bool(np.all(dt >= 0)),
        "duplicates": int(df.index.duplicated().sum()),
    }