"""Driver BTS FREEEMG (BioDAQ SDK) con timestamps sincronizados.

Cambios principales respecto a la versión anterior
--------------------------------------------------
* Se leen TODOS los canales (antes ``range(n-1)`` omitía el último).
* Timestamps derivados de ``DeviceClock`` (índice de muestra -> reloj común
  con estimación de Fs real y deriva) en vez de ``now + 600 ms`` sintético.
* Buffer acotado (``deque``) y almacenamiento por bloques numpy (rápido).
* ``stop()`` idempotente y drena la cola; ``disconnect()`` seguro.
* ``get_emg_df(since=...)`` permite lecturas incrementales (grabación).
* Constructor con ``num_channels`` configurable.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .Device import Device
from ._utils.clock import DeviceClock, HostClock

try:
    import clr
    _HAS_CLR = True
except Exception:
    clr = None
    _HAS_CLR = False

try:
    import System
except Exception:
    System = None

DLL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dll")
_DLLS = ["bts.biodaq.core.dll", "FTD2XX_NET.dll", "log4net.dll", "Core.dll"]

if _HAS_CLR:
    for _n in _DLLS:
        clr.AddReference(os.path.join(DLL_DIR, _n))
    from BTS.BioDAQ.Core import BioDAQ, BioDAQExitStatus, TriggerSource, QueueSink
else:
    BioDAQ = BioDAQExitStatus = TriggerSource = QueueSink = None


class FREEEMG(Device):
    _BAT = {0: "0% (Empty)", 1: "25% (Low)", 2: "50% (Medium)",
            3: "75% (High)", 4: "100% (Full)"}

    def __init__(self, num_channels: int = 4, fs: int = 1000,
                 buffer_sec: float = 60.0) -> None:
        super().__init__()
        if BioDAQ is None:
            raise RuntimeError("FREEEMG requiere pythonnet + SDK BTS (Windows).")
        self.bio = BioDAQ()
        self.qs = None
        self.attached = False
        self.fs = fs
        self.num_channels = num_channels
        self.clock = DeviceClock(fs=fs)
        self.channel_names: List[str] = [f"EMG{i + 1}" for i in range(num_channels)]

        self._stop_evt = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        # Cada elemento: (idx_inicial, ndarray (n, num_channels))
        self._chunks: deque = deque()
        self._max_samples = int(buffer_sec * fs)
        self._n_buffered = 0
        self._next_idx = 0                       # contador global de muestras
        self._pending: Dict[int, List[float]] = {c: [] for c in range(num_channels)}
        self.dropped_reads = 0

    # ------------------------------------------------------------ lifecycle
    def connect(self) -> bool:
        st = self.bio.Attach()
        if st != BioDAQExitStatus.Success:
            raise RuntimeError(f"Attach failed: {st} ({int(st)})")
        self.bio.UpdateStatusInfo()
        self.attached = True
        self.qs = QueueSink()
        self.qs.Init()
        self.bio.Sinks.Add(self.qs)
        self.connected_sensors()
        self._connected = True
        return True

    def _ensure_attached(self) -> None:
        if not self.attached or self.bio is None:
            raise RuntimeError("Llama a connect() primero.")

    def connected_sensors(self) -> List[str]:
        """Imprime estado/batería y devuelve las etiquetas conectadas.

        Además fija ``channel_names`` según el orden de SensorsView.
        NOTA: se asume que el índice de canal del QueueSink coincide con el
        orden de ``SensorsView.Values``; verifícalo con tu hardware.
        """
        self._ensure_attached()
        self.bio.UpdateStatusInfo()
        connected, names = [], []
        for i, sv in enumerate(self.bio.SensorsView.Values):
            label = getattr(sv, "Label", None) or getattr(sv, "SensorLabel", None) or str(i + 1)
            ok = bool(getattr(sv, "Connected", False))
            batt = getattr(sv, "BattLevel", None)
            try:
                batt_txt = self._BAT.get(batt.value__, "?")
            except Exception:
                batt_txt = "?"
            print(f"[FREEEMG] Sensor {label}: "
                  f"{'conectado, batería ' + batt_txt if ok else 'DESCONECTADO'}")
            names.append(f"EMG{label}")
            if ok:
                connected.append(label)
        if names:
            self.num_channels = max(self.num_channels, len(names)) if len(names) < self.num_channels else len(names)
            self.channel_names = names
            for c in range(self.num_channels):
                self._pending.setdefault(c, [])
        return connected

    def start(self) -> None:
        self._ensure_attached()
        if self._started:
            return
        self.bio.Trigger(TriggerSource.Software)
        for name, fn in (("Arm", self.bio.Arm), ("Start", self.bio.Start)):
            st = fn()
            if st != BioDAQExitStatus.Success:
                raise RuntimeError(f"{name} failed: {st}")
        self._stop_evt.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_loop, name="FEMGReader", daemon=True)
        self._reader_thread.start()
        self._started = True

    def stop(self) -> None:
        if not self._started:
            return
        self._stop_evt.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)
        self._reader_thread = None
        try:
            self.bio.Stop()
        except Exception as e:
            print(f"[FREEEMG] Stop error: {e}")
        try:
            self.read_queue_values()      # drena lo que quedó en la cola
        except Exception:
            pass
        self._started = False

    def disconnect(self) -> None:
        self.stop()
        if self.bio is not None:
            for fn in (self.bio.Sinks.Clear, self.bio.Reset, self.bio.Dispose):
                try:
                    fn()
                except Exception:
                    pass
        self.attached = False
        self._connected = False
        self.bio = None
        if System is not None:
            System.GC.Collect()
            System.GC.WaitForPendingFinalizers()
            System.GC.Collect()
        time.sleep(0.3)

    # --------------------------------------------------------------- reader
    def _reader_loop(self) -> None:
        idle = 1.0 / self.fs * 2
        while not self._stop_evt.is_set():
            try:
                got = self.read_queue_values()
            except Exception as e:
                print(f"[FREEEMG] reader error: {e}")
                self.dropped_reads += 1
                got = False
            if not got:
                time.sleep(idle)

    def read_queue_values(self) -> bool:
        """Vacía el QueueSink y agrega bloques alineados por muestra."""
        if self.qs is None:
            return False
        any_data = False
        for ch in range(self.num_channels):          # <- TODOS los canales
            if self.qs.QueueSize(int(ch)) <= 0:
                continue
            _status, values = self.qs.ReadDataBufferByChannel(ch)
            if values is None:
                continue
            arr = [float(v) for v in values]
            if arr:
                self._pending[ch].extend(arr)
                any_data = True
        if not any_data:
            return False

        # Solo se emiten muestras presentes en TODOS los canales que transmiten
        active = [c for c in range(self.num_channels) if self._pending[c] or True]
        n = min(len(self._pending[c]) for c in active)
        if n == 0:
            return True
        block = np.empty((n, self.num_channels), dtype=np.float64)
        for c in active:
            block[:, c] = self._pending[c][:n]
            del self._pending[c][:n]

        with self._lock:
            start = self._next_idx
            self._chunks.append((start, block))
            self._next_idx += n
            self._n_buffered += n
            while self._n_buffered > self._max_samples and len(self._chunks) > 1:
                _, old = self._chunks.popleft()
                self._n_buffered -= len(old)
        self.clock.observe(self._next_idx - 1)        # llegada de la última muestra
        return True

    # ----------------------------------------------------------------- data
    def get_emg_df(self, channel: Optional[str] = None,
                   since: Optional[pd.Timestamp] = None) -> pd.DataFrame:
        """DataFrame con DatetimeIndex (reloj común). ``since`` = solo filas nuevas."""
        with self._lock:
            if not self._chunks:
                return pd.DataFrame()
            starts = [s for s, _ in self._chunks]
            data = np.vstack([b for _, b in self._chunks])
            idx = np.concatenate([np.arange(s, s + len(b)) for s, b in self._chunks])
        ts = self.clock.index_to_datetime(idx)        # timestamps refinados retroactivamente
        df = pd.DataFrame(data, index=ts, columns=self.channel_names[: data.shape[1]])
        if since is not None:
            df = df[df.index > since]
        if channel is not None and channel in df.columns:
            return df[[channel]]
        return df

    def get_imu_df(self) -> pd.DataFrame:
        return pd.DataFrame()

    def sync_report(self) -> dict:
        return {"fs_nominal": self.clock.fs_nominal,
                "fs_estimated": round(self.clock.fs_estimated, 4),
                "drift_ppm": round(self.clock.drift_ppm, 1),
                "samples": self._next_idx,
                "dropped_reads": self.dropped_reads}


if __name__ == "__main__":
    emg = None
    try:
        emg = FREEEMG(num_channels=4)
        emg.connect()
        emg.start()
        time.sleep(5)
        print(emg.get_emg_df().tail())
        print(emg.sync_report())
    finally:
        if emg is not None:
            emg.disconnect()