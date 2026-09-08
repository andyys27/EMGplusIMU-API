"""Driver nativo Linux para FREEEMG, vía el chip FTDI en modo D2XX.

ESTADO: ESQUELETO — requiere completar las constantes de protocolo marcadas
con "# TODO(protocolo)". Captura tráfico con sniff_freeemg.py y analízalo
con protocol_analyzer.py antes de usar esto en serio.

Si el sniffing revela que el dongle en realidad opera en modo VCP (puerto
serie estándar) en vez de D2XX puro, cambia la sección de transporte por
`pyserial` tal como en GSensorLinux.py — el resto (framing, parseo) es
igual de válido.

Implementa la interfaz de _devices.Device, intercambiable con FREEEMG (el
driver Windows) en DeviceFactory una vez registrado ahí.
"""
from __future__ import annotations

import struct
import threading
import time
from collections import deque
from typing import Optional

import numpy as np
import pandas as pd

try:
    import ftd2xx as ftd
except ImportError:
    ftd = None

from .Device import Device

# ──────────────────────────────────────────────────────────────────────
# TODO(protocolo): reemplazar con valores reales. Estos son placeholders,
# NO válidos, solo para mostrar la forma esperada.
# ──────────────────────────────────────────────────────────────────────
SYNC_BYTES = b"\xA5\x5A"        # TODO(protocolo)
HEADER_LEN = 4                  # TODO(protocolo): bytes de sync+tipo+tamaño antes del payload
CMD_ATTACH = b""                # TODO(protocolo): si aplica, comando de "Attach" equivalente
CMD_ARM = b""                   # TODO(protocolo)
CMD_START = b""                 # TODO(protocolo)
CMD_STOP = b""                  # TODO(protocolo)
N_CHANNELS = 4                  # ajustar según el hardware (EMG1..EMG8)
SAMPLE_FS = 1000


class FREEEMGLinux(Device):
    """Driver FREEEMG que habla directo al chip FTDI vía D2XX, sin SDK .NET."""

    def __init__(self, device_index: int = 0, serial_number: Optional[str] = None,
                 baudrate: int = 115200) -> None:
        super().__init__()
        if ftd is None:
            raise RuntimeError(
                "Falta el paquete 'ftd2xx' o la librería nativa libftd2xx. "
                "pip install ftd2xx, y descarga libftd2xx de ftdichip.com."
            )
        self.device_index = device_index
        self.serial_number = serial_number
        self.baudrate = baudrate
        self._dev = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._lock = threading.Lock()
        self.fs = SAMPLE_FS
        self.num_channels = N_CHANNELS
        self._emg_rows: deque = deque(maxlen=200_000)

    # ---- lifecycle ----
    def connect(self, **kwargs) -> None:
        if self.serial_number:
            self._dev = ftd.openEx(self.serial_number.encode())
        else:
            self._dev = ftd.open(self.device_index)
        self._dev.setBaudRate(self.baudrate)
        self._dev.setDataCharacteristics(8, 0, 0)
        self._dev.setTimeouts(1000, 1000)
        self._connected = True
        print("[FREEEMGLinux] Conectado al dongle FTDI.")

        # TODO(protocolo): si el "Attach" del SDK original hace algo más
        # que abrir el puerto (negociación, lectura de estado de sensores
        # inalámbricos, etc.), replicarlo aquí con CMD_ATTACH.
        if CMD_ATTACH:
            self._dev.write(CMD_ATTACH)

    def start(self) -> None:
        if self._dev is None:
            raise RuntimeError("Llama connect() primero.")

        # TODO(protocolo): el SDK original hace Trigger -> Arm -> Start.
        # Replicar esa secuencia de comandos reales aquí, con sus ACKs si
        # existen.
        for cmd in (CMD_ARM, CMD_START):
            if cmd:
                self._dev.write(cmd)

        self._stop_evt.clear()
        self._reader_thread = threading.Thread(target=self._reader_loop, name="FREEEMGLinuxReader", daemon=True)
        self._reader_thread.start()
        self._started = True
        print("[FREEEMGLinux] Adquisición iniciada.")

    def stop(self) -> None:
        self._stop_evt.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)
        if self._dev is not None and CMD_STOP:
            try:
                self._dev.write(CMD_STOP)
            except Exception:
                pass
        self._started = False
        print("[FREEEMGLinux] Adquisición detenida.")

    def disconnect(self) -> None:
        if self._dev is not None:
            self._dev.close()
        self._dev = None
        self._connected = False
        print("[FREEEMGLinux] Desconectado.")

    # ---- reader loop ----
    def _reader_loop(self) -> None:
        """Máquina de estados de framing sobre el flujo D2XX.

        TODO(protocolo): ajustar exactamente igual que en GSensorLinux,
        según lo que revele protocol_analyzer.py: sync bytes, si el
        tamaño es fijo o viene en un campo del header (como en
        UsbReader.py de MioTracker), y si hay checksum al final.
        """
        buf = bytearray()
        while not self._stop_evt.is_set():
            try:
                n_wait = self._dev.getQueueStatus()
                if n_wait == 0:
                    time.sleep(0.005)
                    continue
                chunk = self._dev.read(n_wait)
                if not chunk:
                    continue
                buf.extend(chunk)

                while True:
                    idx = buf.find(SYNC_BYTES)
                    if idx == -1:
                        if len(buf) > len(SYNC_BYTES):
                            del buf[: len(buf) - len(SYNC_BYTES) + 1]
                        break
                    if idx > 0:
                        del buf[:idx]
                    if len(buf) < HEADER_LEN:
                        break

                    # TODO(protocolo): si el tamaño de payload viene en el
                    # header (como en MioTracker: byte de "size"), léelo
                    # aquí en vez de asumir una longitud fija.
                    size = buf[len(SYNC_BYTES)]  # placeholder
                    total_len = HEADER_LEN + size
                    if len(buf) < total_len:
                        break

                    packet = bytes(buf[:total_len])
                    del buf[:total_len]
                    self._parse_packet(packet)

            except Exception as e:
                print(f"[FREEEMGLinux] Error en loop de lectura: {e}")

    def _parse_packet(self, packet: bytes) -> None:
        """TODO(protocolo): decodificar canales EMG reales del payload."""
        try:
            t = time.time()
            payload = packet[HEADER_LEN:]
            n_vals = len(payload) // 4
            vals = struct.unpack_from(f"<{n_vals}f", payload, 0)
            with self._lock:
                self._emg_rows.append((t, list(vals)))
        except Exception as e:
            print(f"[FREEEMGLinux] Error parseando paquete: {e}")

    # ---- data access (interfaz Device) ----
    def get_emg_df(self) -> pd.DataFrame:
        with self._lock:
            rows = list(self._emg_rows)
        if not rows:
            return pd.DataFrame()
        ts = pd.to_datetime([r[0] for r in rows], unit="s", origin="unix")
        vals = np.array([r[1] for r in rows], dtype=float)
        cols = [f"ch{i}" for i in range(vals.shape[1])]
        df = pd.DataFrame(vals, index=pd.DatetimeIndex(ts, name="Timestamp"), columns=cols)
        return df.sort_index()

    def get_imu_df(self) -> pd.DataFrame:
        """Este dispositivo no provee IMU."""
        return pd.DataFrame()


if __name__ == "__main__":
    dev = FREEEMGLinux(device_index=0)
    try:
        dev.connect()
        dev.start()
        time.sleep(3)
        print(dev.get_emg_df())
    finally:
        dev.stop()
        dev.disconnect()