"""Driver nativo Linux para el sensor BTS GSensor, vía Bluetooth SPP.

ESTADO: ESQUELETO — requiere completar las constantes de protocolo marcadas
con "# TODO(protocolo)" antes de que esto lea datos reales. Esas constantes
se obtienen capturando tráfico con sniff_gsensor.py y analizándolo con
protocol_analyzer.py (ver README_reverse_engineering.md).

Sigue el mismo patrón que MioTracker + UsbReader: un hilo lector con una
máquina de estados de framing, que emite paquetes ya recortados, y un
método de parseo que produce filas (t, ax, ay, az, gx, gy, gz, ...).

Implementa la interfaz de _devices.Device, por lo que es intercambiable
con GSensor (el driver Windows) en DeviceFactory una vez registrado ahí.
"""
from __future__ import annotations

import struct
import threading
import time
from collections import deque
from typing import Optional

import pandas as pd
import serial

from .Device import Device

# ──────────────────────────────────────────────────────────────────────
# TODO(protocolo): reemplazar con los valores reales obtenidos del
# análisis de la captura (protocol_analyzer.py). Los de abajo son
# EJEMPLOS ilustrativos tomados del formato Unicorn2LSL, NO son válidos
# para el GSensor real — su único propósito es mostrar la forma que
# deben tener.
# ──────────────────────────────────────────────────────────────────────
SYNC_START = b"\xC0\x00"        # TODO(protocolo): bytes de inicio de paquete reales
SYNC_END = b"\x0D\x0A"          # TODO(protocolo): bytes de fin de paquete reales (si existen)
PACKET_LEN = 45                 # TODO(protocolo): longitud total de paquete real
CMD_START_ACQ = bytes.fromhex("000000")   # TODO(protocolo): comando real de arranque
CMD_STOP_ACQ = bytes.fromhex("000000")    # TODO(protocolo): comando real de parada
ACK_OK = b"\x00\x00\x00"        # TODO(protocolo): respuesta de ACK esperada, si aplica


class GSensorLinux(Device):
    """Driver GSensor que habla directo por Bluetooth SPP, sin SDK .NET."""

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0) -> None:
        """
        Parameters
        ----------
        port:
            Puerto serie del enlace Bluetooth SPP, ej. ``/dev/rfcomm0``.
            Créalo previamente con ``bluetoothctl`` + ``rfcomm bind``.
        """
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._ser: Optional[serial.Serial] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._lock = threading.Lock()
        self._imu_rows: deque = deque(maxlen=100_000)

    # ---- lifecycle ----
    def connect(self, **kwargs) -> None:
        self._ser = serial.Serial(self.port, baudrate=self.baudrate, timeout=self.timeout)
        print(f"[GSensorLinux] Conectado a {self.port}")
        self._connected = True

    def start(self) -> None:
        if not self._ser or not self._ser.is_open:
            raise RuntimeError("Llama connect() primero.")

        # TODO(protocolo): confirmar si hace falta enviar CMD_START_ACQ y
        # esperar ACK_OK antes de que el sensor empiece a transmitir, tal
        # como hace el ejemplo de Unicorn (s.write(start_acq); s.read(3)).
        self._ser.write(CMD_START_ACQ)
        ack = self._ser.read(len(ACK_OK))
        if ack != ACK_OK:
            raise RuntimeError(f"No se pudo iniciar adquisición (ack={ack!r}). Revisa CMD_START_ACQ.")

        self._stop_evt.clear()
        self._reader_thread = threading.Thread(target=self._reader_loop, name="GSensorLinuxReader", daemon=True)
        self._reader_thread.start()
        self._started = True
        print("[GSensorLinux] Adquisición iniciada.")

    def stop(self) -> None:
        self._stop_evt.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)
        if self._ser and self._ser.is_open:
            try:
                self._ser.write(CMD_STOP_ACQ)  # TODO(protocolo): confirmar comando de parada
            except Exception:
                pass
        self._started = False
        print("[GSensorLinux] Adquisición detenida.")

    def disconnect(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None
        self._connected = False
        print("[GSensorLinux] Desconectado.")

    # ---- reader loop ----
    def _reader_loop(self) -> None:
        """Máquina de estados de framing: busca SYNC_START, lee PACKET_LEN
        bytes, valida SYNC_END si aplica, y parsea. Ajusta según lo que
        arroje protocol_analyzer.py — puede que no necesites SYNC_END, o
        que la longitud sea variable con un campo de tamaño (como en
        MioTracker/UsbReader) en vez de fija.
        """
        buf = bytearray()
        while not self._stop_evt.is_set():
            try:
                chunk = self._ser.read(256)
                if not chunk:
                    continue
                buf.extend(chunk)

                while True:
                    idx = buf.find(SYNC_START)
                    if idx == -1:
                        # conserva solo la cola por si el sync viene partido
                        if len(buf) > len(SYNC_START):
                            del buf[: len(buf) - len(SYNC_START) + 1]
                        break
                    if idx > 0:
                        del buf[:idx]
                    if len(buf) < PACKET_LEN:
                        break

                    packet = bytes(buf[:PACKET_LEN])
                    del buf[:PACKET_LEN]

                    if SYNC_END and packet[-len(SYNC_END):] != SYNC_END:
                        # framing inválido, resincroniza
                        continue

                    self._parse_packet(packet)

            except Exception as e:
                print(f"[GSensorLinux] Error en loop de lectura: {e}")

    def _parse_packet(self, packet: bytes) -> None:
        """Decodifica un paquete ya recortado a PACKET_LEN bytes.

        TODO(protocolo): reemplazar los offsets/formatos de struct.unpack
        por los reales, determinados comparando capturas con movimientos
        conocidos del sensor (igual que se hizo para accel/gyro en el
        ejemplo de Unicorn: struct.unpack('<h', payload[27:29])).
        """
        try:
            t = time.time()
            # --- EJEMPLO ilustrativo, offsets ficticios ---
            ax, ay, az = struct.unpack_from("<3h", packet, 2)
            gx, gy, gz = struct.unpack_from("<3h", packet, 8)
            with self._lock:
                self._imu_rows.append((t, ax, ay, az, gx, gy, gz))
        except Exception as e:
            print(f"[GSensorLinux] Error parseando paquete: {e}")

    # ---- data access (interfaz Device) ----
    def get_imu_df(self) -> pd.DataFrame:
        with self._lock:
            rows = list(self._imu_rows)
        if not rows:
            return pd.DataFrame()
        cols = ["ax", "ay", "az", "gx", "gy", "gz"]
        ts = pd.to_datetime([r[0] for r in rows], unit="s", origin="unix")
        df = pd.DataFrame([r[1:] for r in rows], index=pd.DatetimeIndex(ts, name="Timestamp"), columns=cols)
        return df.sort_index()

    def get_emg_df(self) -> pd.DataFrame:
        """Este dispositivo no provee EMG."""
        return pd.DataFrame()


if __name__ == "__main__":
    # Prueba manual rápida: python -m _devices.GSensorLinux /dev/rfcomm0
    import sys

    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/rfcomm0"
    dev = GSensorLinux(port=port)
    try:
        dev.connect()
        dev.start()
        time.sleep(3)
        print(dev.get_imu_df())
    finally:
        dev.stop()
        dev.disconnect()