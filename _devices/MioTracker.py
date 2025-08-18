"""Implementation of the MioTracker EMG+IMU device."""

from typing import List, Callable, Optional
import pandas as pd
import threading
import serial
import time
from ._utils.WebSocketClient import WebSocketClient
from ._utils.UsbReader import UsbReader
from ._utils.serialCoder import SerialCoder
from  .Plotting.LivePlot import LivePlot
from collections import deque
import struct
import datetime
import numpy as np
from .Device import Device as BaseDevice
from datetime import timedelta


class _OnlineEMGOffsetComp:
    """
    Dynamic per-channel offset compensator using an exponential moving average (EMA).
    baseline[t] = (1-alpha)*baseline[t-1] + alpha*x[t]
    x_corr = x - baseline
    alpha = dt / tau  (dt=1/fs, tau=time constant)
    """

    def __init__(self, n_channels=2, Fs=250, tau_ms=100):
        self.n = n_channels
        self.Fs = Fs
        self.tau = max(1e-3, tau_ms / 1000.0)
        self.alpha = min(1.0, (1.0 / self.Fs) / self.tau)
        self.baseline = 0.0

    def reset(self):
        """Reset the internal EMA baseline to zero."""
        self.baseline = 0.0

    def update(self, sample_vec):
        """Apply the offset compensation to ``sample_vec``."""
        x = np.array(sample_vec, dtype=float)

        for i, value in enumerate(x):
            self.baseline = (1.0 - self.alpha) * self.baseline + self.alpha * x[i]
            x[i] = x[i] - self.baseline

        return x


class MioTracker(BaseDevice):
    """Device driver for the MioTracker supporting serial and WebSocket modes."""

    def __init__(
        self,
        transport: str = "websocket",
        websocketuri: Optional[str] = None,
        port: Optional[str] = None,
        Fs: int = 500,
        baudrate: int = 100000,
        maxlen: int = 30,
        trim_sec: float = 0.1,
        gain: int = 6,
    ) -> None:
        """Initialize a MioTracker device.

        Parameters
        ----------
        transport:
            ``"serial"`` or ``"websocket"`` transport mode.
        websocketuri:
            URI used when ``transport`` is ``"websocket"``.
        port:
            Serial port name used when ``transport`` is ``"serial"``.
        Fs:
            Sampling frequency in Hz.
        baudrate:
            Serial baudrate when using serial transport.
        maxlen:
            Maximum buffer length in seconds.
        trim_sec:
            Seconds trimmed from the beginning of returned DataFrames.
        gain:
            Programmable amplifier gain.
        """
        super().__init__()
        self._transport = transport
        if self._transport == "serial":
            self._ser = None
            self._usb_thread = None
            self._sCoder = SerialCoder()
            if not port:
                raise ValueError("Port must be specified for serial transport")
        elif self._transport == "websocket":
            self._ws_client = None
            self._ws_thread = None
            self._ws_uri = websocketuri
        else:
            raise ValueError("Transport type not supported")

        self.port = port
        self.Fs = Fs
        self.baudrate = baudrate
        self.maxlen = maxlen * Fs
        self.websocketuri = websocketuri
        self.trim_sec = trim_sec
        self.gain = gain

        self._lock = threading.Lock()

        self.emgData = deque(maxlen=self.maxlen)
        self.emgRawData = deque(maxlen=self.maxlen)
        self.emgTime = deque(maxlen=self.maxlen)

        self.imuData = deque(maxlen=self.maxlen)
        self.imuTime = deque(maxlen=self.maxlen)

        self.tBase = 0.0
        self.timeout = 1.0

    # =====================
    # Connection / disconnection
    # =====================
    def connect(self) -> bool:
        """Open the underlying transport channel."""
        if self._transport == "serial":
            self.disconnect()
            self._ser = serial.Serial(
                self.port, baudrate=self.baudrate, timeout=self.timeout
            )
            print(f"[MioTracker] Connected via SERIAL on {self.port}")
            return True
        elif self._transport == "websocket":
            self.websocketuri = (
                "ws://miotracker.local/start"
                if not self.websocketuri
                else self.websocketuri
            )
            self._ws_client = WebSocketClient(self.websocketuri)
            self._ws_client.connect()
            return True
        return False

    def disconnect(self, port: Optional[str] = None) -> bool:
        """Close the transport channel and release resources."""
        if self._transport == "serial":
            if self._ser and self._ser.is_open:
                print(f"[MioTracker] Closing serial port {self._ser.port}...")
                self._ser.close()
                self._ser = None
                self._transport = None
                return True

        elif self._transport == "websocket":
            if self._ws_client:
                print("[MioTracker] Closing WebSocket connection...")
                self._ws_client.disconnect()
                self._ws_client = None
                self._transport = None
                return True

    def start(self) -> None:
        """Begin asynchronous acquisition depending on the transport."""
        if self._transport == "serial":
            if not self._ser or not self._ser.is_open:
                print("[MioTracker] Serial port not open. Call connect() first.")
            if self._usb_thread is not None and self._usb_thread.is_alive():
                self._usb_thread.join(timeout=1.0)
            self._usb_thread = UsbReader(self._ser, self._sCoder, debug=True)
            self._usb_thread.start()
            self._usb_thread.subscribe_packets(self._on_usb_packet)
            print("[MioTracker] Acquisition started.")
        elif self._transport == "websocket":
            if not self._ws_client:
                print("[MioTracker] Socket not open. Call connect() first.")
            self._ws_client.subscribe(self._on_ws_frame)

    def stop(self) -> None:
        """Stop acquisition and detach packet handlers."""
        if self._transport == "serial":
            self._usb_thread.stop()
            if self._usb_thread.is_alive():
                self._usb_thread.join(timeout=0.1)
            self._usb_thread.unsubscribe_packets(self._on_usb_packet)
            self._usb_thread = None
            print("[MioTracker] Acquisition stopped.")
        elif self._transport == "websocket":
            if self._ws_client:
                self._ws_client.desubscribe()

    def get_emg_df(self, onlyraw=False) -> pd.DataFrame:
        """Return buffered EMG samples as a DataFrame."""
        with self._lock:
            if len(self.emgData) == 0:
                print("[MioTracker] No data received")
                return pd.DataFrame()

        rows, ts = [], []
        packets = list(self.emgData)
        rawPackets = list(self.emgRawData)
        t0_list = list(self.emgTime)

        for pkt, pktRaw, t0 in zip(packets, rawPackets, t0_list):
            t0 = pd.Timestamp(t0)
            val_ch0 = np.asanyarray(pkt, dtype=float)
            val_chRaw = np.asanyarray(pktRaw, dtype=float)
            for i in range(0, len(val_ch0)):
                rows.append(
                    {
                        "ch0": val_ch0[i],
                        "chRaw": val_chRaw[i],
                    }
                )
        t_start = t0_list[0]
        t_end = t0_list[-1]
        n_points = len(rows)
        t_uniform = pd.date_range(start=t_start, end=t_end + pd.Timedelta(8*(1/self.Fs)), periods=n_points)
        df = pd.DataFrame(rows, index=pd.DatetimeIndex(t_uniform, name="Timestamp"))
        if self.trim_sec and not df.empty:
            t0 = df.index[0] + timedelta(seconds=float(self.trim_sec))
            df = df[df.index >= t0]
        if onlyraw:
            # Only column ch0 + Timestamp as a normal column
            df_out = df.reset_index()[["Timestamp", "ch0"]]
            return df_out
        else:
            return df

    def get_imu_df(self) -> pd.DataFrame:
        """Return buffered IMU samples as a DataFrame."""
        with self._lock:
            if len(self.imuData) == 0:
                return pd.DataFrame()
        imu_array = np.array(list(self.imuData))
        t0_list = list(self.imuTime)
        t_start = t0_list[0]
        t_end = t0_list[-1]
        n_points = len(t0_list)
        t_uniform = pd.date_range(start=t_start, end=t_end, periods=n_points)
        try:
            df = pd.DataFrame(
                {
                    "Accel_X_g": imu_array[:, 0],
                    "Accel_Y_g": imu_array[:, 1],
                    "Accel_Z_g": imu_array[:, 2] - 1,
                    "Gyro_X_dps": imu_array[:, 3],
                    "Gyro_Y_dps": imu_array[:, 4],
                    "Gyro_Z_dps": imu_array[:, 5],
                },
                index=pd.DatetimeIndex(t_uniform, name="Timestamp"),
            )
            if self.trim_sec and not df.empty:
                t0 = df.index[0] + timedelta(seconds=float(self.trim_sec))
                df = df[df.index >= t0]
            return df
        except Exception:
            return pd.DataFrame()

    # =====================
    # USB reading loop
    # =====================
    def _on_usb_packet(self, ptype: int, payload: bytes):
        """Handle a packet from the ``UsbReader`` thread."""
        DATA_TYPE_EMG = 0
        DATA_TYPE_IMU = 1
        DATA_TYPE_STATUS = 2
        try:
            if ptype == DATA_TYPE_EMG:
                self._parse_emg_payload(payload)
            elif ptype == DATA_TYPE_IMU:
                self._parse_imu_payload(payload)
            else:
                pass
        except Exception:
            pass

    def _on_ws_frame(self, data: bytes):
        """Parse a frame coming from the WebSocket transport."""
        DATA_TYPE_EMG = 0
        DATA_TYPE_IMU = 1
        DATA_TYPE_STATUS = 2
        try:
            if not isinstance(data, (bytes, bytearray)) or len(data) < 4:
                return
            offset = 2
            ptype = struct.unpack_from("<B", data, offset)[0]
            offset += 1
            size = struct.unpack_from("<B", data, offset)[0]
            offset += 1
            need = size - 4
            payload = (
                data[offset : offset + need]
                if len(data) >= offset + need
                else data[offset:]
            )
            if ptype == DATA_TYPE_EMG:
                self._parse_emg_payload(payload)
            elif ptype == DATA_TYPE_IMU:
                self._parse_imu_payload(payload)
        except Exception:
            pass

    def _parse_emg_payload(self, buf: bytes):
        """Decode EMG samples from a raw USB ``payload``."""
        off = 0
        pkt = list()
        if not hasattr(self, "_ema"):
            self._ema = _OnlineEMGOffsetComp(
                n_channels=1, Fs=self.Fs, tau_ms=100
            )
        try:
            channels = [0]
            for ch in channels:
                if off + 4 > len(buf):
                    break
                chid = struct.unpack_from("<H", buf, off)[0]
                off += 2
                nwords = struct.unpack_from("<H", buf, off)[0]
                off += 2
                for _ in range(nwords):
                    if off + 4 > len(buf):
                        break
                    val = struct.unpack_from("<f", buf, off)[0] / self.gain / 1e3
                    off += 4
                    pkt.append(val)
            with self._lock:
                pkt = np.array(pkt, float)
                corr = self._ema.update(pkt)
                self.emgTime.append(datetime.datetime.now())
                self.emgData.append(corr.tolist())
                self.emgRawData.append(pkt.tolist())
        except Exception as e:
            print(f"[USB] EMG payload error: {e}")
            pass

    def _parse_imu_payload(self, buf: bytes):
        """Decode IMU samples from a raw USB ``payload``."""
        try:
            if len(buf) < 28:
                return
            off = 0
            vals = []
            for _ in range(6):
                vals.append(struct.unpack_from("<f", buf, off)[0])
                off += 4
            with self._lock:
                self.imuData.append(vals.copy())
                self.imuTime.append(datetime.datetime.now())
        except Exception as e:
            print(f"[USB] IMU payload error: {e}")
            pass
    @staticmethod
    def touV(raw, gain=8, vref=2.42):
        """Convert raw ADC counts to microvolts."""
        x = raw
        # If the firmware sends float32 values, cast them to integers.
        if np.issubdtype(x.dtype, np.floating):
            x = np.rint(x).astype(np.int64)
        else:
            x = x.astype(np.int64)

        # 24-bit sign extension
        x &= 0xFFFFFF
        x = (x ^ 0x800000) - 0x800000

        # LSB exacto: (2*Vref/Gain)/(2^24 - 1)
        lsb_V = (2.0 * vref / float(gain)) / ((1 << 24) - 1)
        return x.astype(np.float64) * lsb_V * 1e6  # µV



if __name__ == "__main__":

    try:
        # Create device
        # dev = MioTracker(transport="serial", port="COM7", Fs=1000)
        dev = MioTracker(
            transport="websocket", websocketuri="ws://miotracker.local/start"
        )

        dev.list_serial_devices()
        # dev = MioTracker(transport="websocket", websocketuri="ws://miotracker.local/start")

        dev.connect()
        dev.start()

        # Live plotting
        plotter = LivePlot(
            plots=[
                {"get_df": lambda: dev.get_emg_df(onlyraw=True), "title": "EMG"},
                {"get_df": lambda: dev.get_imu_df(), "title": "IMU"},
            ],
            window_sec=3,
            refresh_hz=30,
            title="EMG + IMU Live",
        )
        plotter.start()

    except Exception as e:
        print(f"[MioTracker] Error connecting: {e}")
        try:
            dev.stop()
            dev.disconnect()
        except Exception as e:
            print(f"[MioTracker] Error stopping/disconnecting: {e}")

    df_all = dev.get_all_data()
    if not df_all.empty:
        out = f"miotracker_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df_all.to_csv(out, index=True)
        print(f"[MioTracker] Saved: {out}")
