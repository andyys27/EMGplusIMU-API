import clr
import time
import matplotlib.pyplot as plt
import queue
from .Device import Device
import threading
from datetime import datetime
from typing import Callable, Optional, Iterable
import os
import pandas as pd
import serial
from .Plotting.LivePlot import LivePlot
from ._utils._utilsfn import list_serial_devices 
# 1) Load your BTS SDK DLL (adjust path if needed)
# Ruta base: la carpeta actual de este script
base_path = os.path.dirname(os.path.abspath(__file__))
dll_path = os.path.join(base_path, "dll", "Core.dll")
clr.AddReference(dll_path)


# 2) Import the types we need
from BTS.GS2.Core import (
    Supervisor, LogLevel,
    QueueType, DeviceState,
    AccelRange, GyroRange,SensorType
)




class GSensor(Device):
    """
    Dispositivo BAIOBIT (plantilla) compatible con la interfaz Device.
    Soporta:
      - Serial:   BAIOBIT(port="COM8", baud=115200)
      - WebSocket: BAIOBIT(ws_url="ws://127.0.0.1:8765")
    """

    def __init__(self, com_port) -> None:
            # 1) Create & configure the Supervisor
        self.manager = Supervisor()
        self.manager.SetLoggerState(True)
        self.manager.SetLoggerLevel(LogLevel.OFF)
        self.net_name = "GS_Network"
        self.configured = False
        self._acq_handler = None
        self.data = []
        # 2) Placeholder for the discovered sensor info
        self.sensor_info = None

        # 3) Try to discover immediately
        if not self._discover_sensor(com_port):
            raise RuntimeError(f"No sensor found on port {com_port!r}")
        # 4) Create a network
        if self.sensor_info is not None:
            self.manager.AddNetwork(self.net_name, self.sensor_info.Type)

    def _discover_sensor(self, com_port: str) -> bool:
        """
        Attempts to discover a sensor on the given COM port.
        Returns True if found (and stores info in self.sensor_info), else False.
        """
        found, info = self.manager.DiscoverSensorOnComPort(com_port)
        if found:
            self.sensor_info = info
        return found

    # --------------------------- Ciclo de vida ---------------------------

    def connect(self):
        if not self.sensor_info:
            raise RuntimeError("No sensor info available. Cannot connect.")
        
        # 2) Grab the network object
        idx          = self.manager.NetworksList.GetNetworkIndex(self.net_name)
        self.network = self.manager.NetworksList[idx]

        existing_ports = [s.pPort for s in self.network.SensorsList]
        if self.sensor_info.Port not in existing_ports:
            added = self.network.AddSensorToNetwork(self.sensor_info.Port)

        # 3) Connect all networks
        ok, netResult, mask = self.manager.ConnectAllNetworks()
        self.connected = ok
        if not ok:
            raise RuntimeError(f"Failed to connect networks (code {netResult}).")

        # 4) Grab the ISensor instance
        self.sensor = self.network.SensorsList[0]

        # 5) Verify it’s really connected
        if not getattr(self.sensor, "State", None) is not ok:
            raise RuntimeError("Sensor did not connect successfully.")
        self._configure()
        self.get_battery()
    def get_battery(self):
        if not self.sensor:
            print("Sensor not connected. Battery reading aborted.")
            return 
        ok, charging, percent = self.sensor.ReadBattery()
        if not ok:
            raise RuntimeError("ReadBattery failed.")
        state = " (charging)" if charging else ""
        print(f"Battery: {percent}%{state}")


    def disconnect(self):
        if self.network:
            ok, mask = self.manager.DisconnectNetwork(self.network.pName)
            if ok:
                print("Disconnected.")
            else:
                print("Disconnect failed.")
            self.connected = not ok
            self.network = None
            self.sensor  = None



    def _configure(self, freq_hz: int = 100):
        """Enable accel/gyro/mag/quat, set ranges & frequency exactly as in the SDK."""
        # only do this once
        if getattr(self, "configured", False):
            return

        ds = DeviceState
        # 1) Enable each channel
        self.network.SetAccelerometerState(ds.Device_Enabled)
        self.network.SetGyroscopeState   (ds.Device_Enabled)
        self.network.SetMagnetometerState(ds.Device_Enabled)
        self.network.SetQuaternionState  (ds.Device_Enabled)
        self.network.SetGPSState         (ds.Device_Unsupported)

        # 2) Acquisition rate
        self.network.SetMemsAcqFrequency(freq_hz)

        # 3) Hole‐filling (only affects downloads)
        self.network.pEnableHolesFillingProcess = True

        # 4) Choose ranges based on sensor type
        if self.sensor_info.Type == SensorType.GS2:
            acc_range  = AccelRange.Acc_8g
            gyro_range = GyroRange.Gyro_2000
        else:
            acc_range  = AccelRange.Acc_1_5g
            gyro_range = GyroRange.Gyro_1200

        self.sensor.SetAccelRange(acc_range)
        self.sensor.SetGyroRange (gyro_range)

        # 5) Set the sensor’s internal health‐check periods
        self.sensor.SetSensorConnectionCheckPeriod(10)
        self.sensor.SetSensorIsAliveCheckPeriod     (10)

        # 6) Apply the configuration
        ok, cfgRes = self.network.ApplySensorsConfiguration_ACQ()
        if not ok:
            raise RuntimeError(f"ApplySensorsConfiguration_ACQ failed ({cfgRes})")
        
    def _rad_to_deg360(_,rad):
        import math
        deg = math.degrees(rad)
        return deg % 360.0
    def start(self):
        self._start_time = time.time()
        def _handler(sender, args):
            def print_frame(f):
                """
                Print out the 12 values in an IDataSample frame f.Sample.
                """
                labels = [
                    "Acc X (m/s²)", "Acc Y (m/s²)", "Acc Z (m/s²)",
                    "Gyro X (°/s)",  "Gyro Y (°/s)",  "Gyro Z (°/s)",
                    "Mag X (µT)",    "Mag Y (µT)",    "Mag Z (µT)",
                    "Roll (°)",      "Pitch (°)",     "Yaw (°)"
                ]
                for i, label in enumerate(labels):
                    val = f.Sample[i].value
                    print(f"{label:12s}: {val:.3f}")
                print("-" * 40)
            try:
                # 1) figure out which queue holds inertial data
                qi = sender.DataQueueList.GetQueueIndex(QueueType.INTERTIAL)

                # 2) create a .NET List[IDataSample] buffer and dump into it
                ok,buf = sender.DataQueueList[qi].Dump()
                if not ok or buf.Count == 0:
                    return

                # 3) take the first frame
                f = buf[0]
                #print_frame(f)
                t = time.time() #- self._start_time

                # 4) unpack accel (indices 0–2)
                ax, ay, az = (f.Sample[i].value for i in (0, 1, 2))
                # 5) unpack gyro  (indices 3–5)
                gx, gy, gz = (f.Sample[i].value for i in (3, 4, 5))
               
                # 6) unpack Euler angles roll,pitch,yaw (indices 9–11)
                roll, pitch, yaw = (self._rad_to_deg360(f.Sample[i].value) for i in (9, 10, 11))

                # 7) append a 10-tuple (t, ax,ay,az, gx,gy,gz, roll,pitch,yaw)
                self.data.append(
                    (t, ax, ay, az,
                        gx, gy, gz,
                        roll, pitch, yaw)
                )

            except Exception as e:
                print("Error in handler:", e)
        
        
        self._acq_handler = _handler
        self.sensor.DataReady += self._acq_handler
        ok, _ = self.manager.StartOnlineAcquisitionOnNetwork(self.net_name)
        if not ok:
            self.sensor.DataReady -= self._acq_handler
            raise RuntimeError("StartOnlineAcquisitionOnNetwork failed")
    def stop(self):
        """Unsubscribe & stop acquisition."""
        if self._acq_handler:
            try:
                self.sensor.DataReady -= self._acq_handler
            except:
                pass
            ok, mask = self.manager.StopOnlineAcquisitionOnNetwork(self.net_name)
            print("⏹️ Acquisition stopped" if ok else " Stop failed")  


    def get_imu_df(self) -> pd.DataFrame:
            """Return IMU data with real datetime index."""
            if not self.data:
                return pd.DataFrame()
            
            rows = list(self.data)
            # Separar timestamps y datos
            timestamps = [r[0] for r in rows]  # primera columna
            values = [r[1:] for r in rows]     # resto de columnas

            data_cols = ["ax", "ay", "az", "gx", "gy", "gz", "roll", "pitch", "yaw"]
            ts_index = pd.to_datetime(timestamps, unit="s", origin="unix")
            df = pd.DataFrame(values, index=pd.DatetimeIndex(ts_index, name="Timestamp"), columns=data_cols)
            df = df.sort_index()

            return df
    
    def get_emg_df(self) -> pd.DataFrame:
        return pd.DataFrame()
        

    def print_queue(self):
        """
        Take a snapshot of the internal data queue and print each (t, ax, ay, az).
        Does not remove items from the queue.
        """
        snapshot = list(self.data)  # peek without popping
        if not snapshot:
            print("🔎 Queue is empty.")
            return

        print(f"🔎 Queue has {len(snapshot)} items:")
        for idx, (t, ax, ay, az, gx, gy, gz, roll, pitch, yaw) in enumerate(self.data, 1):
            print(f"{idx:3d}: t={t:.3f}s  "
                f"Acc=({ax:.2f},{ay:.2f},{az:.2f})  "
                f"Gyro=({gx:.2f},{gy:.2f},{gz:.2f})  "
                f"Euler=({roll:.1f}°,{pitch:.1f}°,{yaw:.1f}°)")
    def __enter__(self):
        print("Entering GSensor context manager")
        return self

    def __exit__(self, exc_type, exc_val, tb):
        print("Exiting GSensor context manager")
        if exc_type:
            print(f"[!] Exception {exc_type.__name__} raised—disconnecting sensor")
        self.disconnect()
        return False

    
    def _on_sdk_error(self, source, error_code, comment):
        print(f"[SDK ERROR] {source}: {comment}  → disconnecting")
        self.disconnect()

# ---------------------------------------------------------------------
# Ejemplo de uso
# ---------------------------------------------------------------------
if __name__ == "__main__":
    # Escoge uno de los dos transportes:
    # 1) Serial

    try:
        dev = GSensor(com_port="COM8")
        
        dev.connect()
        dev.start()
                # Graficar en vivo
        plotter = LivePlot(
            plots=[
                {"get_df": lambda: dev.get_all_data(), "title": "IMU"},

            ],
            window_sec=3,
            refresh_hz=30,
            title="IMU Live",
        )
        plotter.start()

        dev.stop()
        dev.disconnect()
    except Exception as e:
        print("Error:", e)
    finally:
        dev.stop()
        dev.disconnect()
