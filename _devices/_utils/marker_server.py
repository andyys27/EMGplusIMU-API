"""Receptor UDP de marcadores enviados por Unity (ExperimentLogger.cs).

Ubicación sugerida: ``_devices/_utils/marker_server.py`` (usa ``HostClock`` de clock.py).

Protocolo (texto UTF-8, campos separados por TAB)
-------------------------------------------------
  Unity -> PC : PING  seq  t1_unity_ns
  PC -> Unity : PONG  seq  t1  t2_rx_ns  t3_tx_ns      (t2/t3 con HostClock)
  Unity -> PC : EVT   seq  t_unity_ns  offset_ns|NA  label  detail

Unity estima ``offset_ns = reloj_python - reloj_unity`` (método NTP, quedándose con
el ping de menor RTT) y lo adjunta a cada evento. Así, el instante del evento en el
reloj de Python es ``t_unity_ns + offset_ns``: no depende de la latencia de red ni de
que ambos equipos estén sincronizados por NTP. Si Unity y Python corren en el mismo
equipo el offset sale ~0.

Salida (CSV incremental, sobrevive a cierres inesperados)
---------------------------------------------------------
  Timestamp   mejor estimación del instante del evento (UTC ingenuo, igual que HostClock)
  t_ns        lo mismo en ns desde epoch (int64, úsalo para cálculos exactos)
  source      "unity+offset" (preferible) o "rx" (hora de recepción si aún no hay offset)
  t_rx_ns     hora de recepción en Python
  t_unity_ns  hora en el reloj de Unity
  offset_ns   offset usado
  seq, label, detail

Uso
---
    from _devices._utils.marker_server import UnityMarkerServer
    srv = UnityMarkerServer("recordings/sesion01_unity_events.csv", port=5005, recorder=rec)
    srv.start()
    ...
    srv.stop()

Prueba rápida:  python -m _devices._utils.marker_server
"""

from __future__ import annotations

import csv
import os
import socket
import threading
from typing import Optional

import pandas as pd

from .clock import HostClock

COLUMNS = ["Timestamp", "t_ns", "source", "t_rx_ns", "t_unity_ns",
           "offset_ns", "seq", "label", "detail"]


class UnityMarkerServer:
    def __init__(self, out_path: str, host: str = "0.0.0.0", port: int = 5005,
                 recorder: Optional[object] = None, verbose: bool = True) -> None:
        self.out_path = out_path
        self.host = host
        self.port = port
        self.recorder = recorder      # StreamRecorder opcional: replica cada evento con .mark()
        self.verbose = verbose
        self._sock: Optional[socket.socket] = None
        self._th: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._fh = None
        self._csv = None
        self.n_events = 0
        self.n_pings = 0
        self.lost = 0                 # eventos EVT perdidos (huecos en seq)
        self._last_seq = 0

    # ---------------------------------------------------------------- ciclo
    def start(self) -> None:
        folder = os.path.dirname(os.path.abspath(self.out_path))
        os.makedirs(folder, exist_ok=True)
        is_new = not os.path.exists(self.out_path)
        self._fh = open(self.out_path, "a", newline="", encoding="utf-8")
        self._csv = csv.writer(self._fh)
        if is_new:
            self._csv.writerow(COLUMNS)
            self._fh.flush()

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.settimeout(0.2)

        self._stop.clear()
        self._th = threading.Thread(target=self._loop, name="UnityMarkers", daemon=True)
        self._th.start()
        print(f"[UnityMarkers] escuchando UDP {self.host}:{self.port} -> {self.out_path}")

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
        if self._th is not None:
            self._th.join(timeout=1.0)
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        print(f"[UnityMarkers] eventos={self.n_events} pings={self.n_pings} perdidos={self.lost}")

    # ----------------------------------------------------------------- loop
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(4096)
            except socket.timeout:
                continue
            except ConnectionResetError:          # Windows: ICMP de un envío previo
                continue
            except OSError:
                break
            t2 = HostClock.now_ns()               # instante de recepción, lo más pronto posible
            try:
                self._handle(data, addr, t2)
            except Exception as e:                # un paquete mal formado no debe tumbar el hilo
                print(f"[UnityMarkers] paquete ignorado: {e!r}")

    def _handle(self, data: bytes, addr, t2: int) -> None:
        parts = data.decode("utf-8", "replace").rstrip("\r\n").split("\t")
        kind = parts[0]

        if kind == "PING" and len(parts) >= 3:
            t3 = HostClock.now_ns()
            self._sock.sendto(f"PONG\t{parts[1]}\t{parts[2]}\t{t2}\t{t3}".encode(), addr)
            self.n_pings += 1

        elif kind == "EVT" and len(parts) >= 5:
            seq = int(parts[1])
            t_unity = int(parts[2])
            off = None if parts[3] in ("NA", "") else int(parts[3])
            label = parts[4]
            detail = parts[5] if len(parts) > 5 else ""

            if self._last_seq and seq > self._last_seq + 1:
                self.lost += seq - self._last_seq - 1
            self._last_seq = max(self._last_seq, seq)

            if off is not None:
                t_ns, source = t_unity + off, "unity+offset"
            else:
                t_ns, source = t2, "rx"

            self._csv.writerow([str(pd.Timestamp(t_ns, unit="ns")), t_ns, source, t2, t_unity,
                                "" if off is None else off, seq, label, detail])
            self._fh.flush()
            self.n_events += 1

            if self.recorder is not None:
                try:
                    self.recorder.mark(f"unity:{label}")
                except Exception:
                    pass
            if self.verbose:
                print(f"[Unity] {label:<14} {detail}")


if __name__ == "__main__":
    import time

    srv = UnityMarkerServer("recordings/unity_events.csv", port=5005)
    srv.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()