"""Base definitions for EMG and IMU devices."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, List, Optional, Type

import pandas as pd
import serial.tools.list_ports as portList

EMGCallback = Callable[[pd.DataFrame], None]
IMUCallback = Callable[[pd.DataFrame], None]


class Device(ABC):
    """Common interface for any EMG+IMU device."""

    def __init__(self) -> None:
        self._emg_subs: List[EMGCallback] = []
        self._imu_subs: List[IMUCallback] = []
        self._connected = False
        self._started = False
        self._port = None

    # ---- lifecycle ----
    @abstractmethod
    def connect(self, **kwargs) -> None: ...

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    # ---- data access ----
    def get_all_data(self) -> pd.DataFrame:
        emg_df = pd.DataFrame()
        imu_df = pd.DataFrame()
        emg_df = self.get_emg_df()
        imu_df = self.get_imu_df()
        if emg_df.empty and imu_df.empty:
            return pd.DataFrame()
        if not emg_df.empty and not imu_df.empty:
            df_all = pd.merge(
                emg_df,
                imu_df,
                left_index=True,
                right_index=True,
                how="outer",  # keep all times from both
            ).sort_index()
            df_all = df_all.infer_objects(copy=False)
            df_all = df_all.interpolate(method="linear")
            df_all = df_all.ffill()
            df_all.dropna()  # drop any remaining NaNs

            # outer join on Timestamp index; sort for sanity
            return df_all
        if emg_df.empty:
            return imu_df
        if imu_df.empty:
            return emg_df

    @abstractmethod
    def get_emg_df(self) -> pd.DataFrame:
        return pd.DataFrame()

    @abstractmethod
    def get_imu_df(self) -> pd.DataFrame:
        return pd.DataFrame()

    # ---- optional control ----
    def send_command(self, data: bytes | str) -> None:
        pass

    # ---- pub/sub for live consumers (GUI/recorder) ----
    def subscribe_emg(self, fn: EMGCallback) -> None:
        self._emg_subs.append(fn)

    def subscribe_imu(self, fn: IMUCallback) -> None:
        self._imu_subs.append(fn)

    # Helpers for subclasses to notify subscribers
    def _emit_emg(self, df_chunk: pd.DataFrame) -> None:
        for fn in list(self._emg_subs):
            try:
                fn(df_chunk)
            except Exception:
                pass

    def _emit_imu(self, df_chunk: pd.DataFrame) -> None:
        for fn in list(self._imu_subs):
            try:
                fn(df_chunk)
            except Exception:
                pass

    def list_serial_devices(self):
        """List serial ports similarly to the GUI's scan button."""
        ports = list(portList.comports())
        devices = []
        for p in ports:
            print(p.device, p.name, p.description)
            devices.append(
                {
                    "device": p.device,
                    "name": p.name,
                    "description": p.description,
                    "manufacturer": getattr(p, "manufacturer", None),
                    "vid": getattr(p, "vid", None),
                    "pid": getattr(p, "pid", None),
                    "serial_number": getattr(p, "serial_number", None),
                }
            )
        return devices

    # ----- context manager for auto-cleanup -----
    def __enter__(self) -> "Device":
        # let the caller decide when to connect/start
        return self

    def __exit__(
        self, exc_type: Optional[Type[BaseException]], exc: Optional[BaseException], tb
    ) -> bool:
        # ALWAYS attempt to stop & disconnect, even if start/connect failed
        try:
            self.stop()
        except Exception:
            pass
        try:
            self.disconnect()
        except Exception:
            pass
        # Returning False propagates the exception (good for debugging)
        return False
