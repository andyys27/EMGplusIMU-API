"""Sincronización de relojes para múltiples dispositivos.

Idea central
------------
1. ``HostClock``: reloj de referencia común. Se ancla UNA vez a ``time.time_ns()``
   y a partir de ahí avanza con ``perf_counter_ns`` (monotónico), por lo que no
   sufre saltos de NTP ni del reloj del sistema durante la sesión.
2. ``DeviceClock``: convierte el *índice de muestra* de un dispositivo
   (0, 1, 2, ...) en un ``Timestamp`` del reloj común. Como cada paquete llega
   con latencia y jitter variables, NO se usa la hora de llegada directamente:
   se ajusta una recta  t = a + b * n  (b = periodo real => estima Fs real y
   deriva del cristal) y se desplaza al "envolvente inferior" de las llegadas
   (una muestra nunca llega antes de ser generada).
3. Todos los timestamps salen como ``pd.DatetimeIndex`` con precisión de ns.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

import numpy as np
import pandas as pd


class HostClock:
    """Reloj de referencia monotónico anclado a la hora de pared."""

    _wall0_ns = time.time_ns()
    _perf0_ns = time.perf_counter_ns()

    @classmethod
    def now_ns(cls) -> int:
        return cls._wall0_ns + (time.perf_counter_ns() - cls._perf0_ns)

    @classmethod
    def now(cls) -> pd.Timestamp:
        return pd.Timestamp(cls.now_ns())  # int -> ns desde epoch


class DeviceClock:
    """Mapea índice de muestra -> Timestamp común, con estimación de deriva.

    Parameters
    ----------
    fs : Fs nominal en Hz.
    window : nº máximo de observaciones (paquetes) usadas en el ajuste.
    refit_every : re-ajustar cada N observaciones.
    max_drift : desviación máxima tolerada del periodo respecto al nominal
        (fracción, 0.005 = 0.5 %). Protege contra ajustes espurios.
    """

    def __init__(self, fs: float, window: int = 1500,
                 refit_every: int = 25, max_drift: float = 0.005) -> None:
        self.fs_nominal = float(fs)
        self._period_nom = 1e9 / self.fs_nominal          # ns / muestra
        self._obs: deque = deque(maxlen=window)           # (idx, host_ns)
        self._refit_every = refit_every
        self._max_drift = max_drift
        self._lock = threading.Lock()
        self._host0: Optional[int] = None                 # ancla entera (ns)
        self._period = self._period_nom
        self._icpt = 0.0                                  # ns relativos a host0
        self._count = 0
        self.offset_ns = 0                                # corrección manual/xcorr

    # ---- alimentación ----
    def observe(self, end_idx: int, host_ns: Optional[int] = None) -> None:
        """Registra que la muestra ``end_idx`` (última del paquete) llegó ahora."""
        host_ns = HostClock.now_ns() if host_ns is None else host_ns
        with self._lock:
            if self._host0 is None:
                self._host0 = host_ns
                self._icpt = -end_idx * self._period
            self._obs.append((end_idx, host_ns - self._host0))
            self._count += 1
            if self._count % self._refit_every == 0 and len(self._obs) >= 20:
                self._fit()

    def _fit(self) -> None:
        a = np.asarray(self._obs, dtype=np.float64)       # host relativo: sin pérdida de precisión
        x, y = a[:, 0], a[:, 1]
        if np.ptp(x) < 1:
            return
        period, icpt = np.polyfit(x, y, 1)
        if abs(period / self._period_nom - 1.0) > self._max_drift:
            period = self._period_nom                     # ajuste no creíble
            icpt = np.median(y - period * x)
        # Envolvente inferior: la llegada siempre es >= al instante real.
        icpt += np.min(y - (period * x + icpt))
        self._period, self._icpt = float(period), float(icpt)

    # ---- consulta ----
    @property
    def fs_estimated(self) -> float:
        return 1e9 / self._period

    @property
    def drift_ppm(self) -> float:
        return (self.fs_estimated / self.fs_nominal - 1.0) * 1e6

    def index_to_ns(self, idx) -> np.ndarray:
        idx = np.asarray(idx, dtype=np.float64)
        with self._lock:
            base = self._host0 if self._host0 is not None else HostClock.now_ns()
            ns = self._icpt + self._period * idx
        return (base + np.rint(ns)).astype(np.int64) + int(self.offset_ns)

    def index_to_datetime(self, idx, name: str = "Timestamp") -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.index_to_ns(idx).astype("datetime64[ns]"), name=name)