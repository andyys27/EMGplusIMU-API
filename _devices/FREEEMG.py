from __future__ import annotations
import os
import clr
import time
import numpy as np
import matplotlib.pyplot as plt
import System, time
from System import Int64, Single,Array
from enum import IntEnum
import os
import time
import threading
from typing import Optional, List, Dict
import pandas as pd

from .Device import Device

# ──────────────────────────────────────────────────────────────────────
# Carga de DLLs (.NET) del SDK BTS (ruta relativa a este archivo)
# ──────────────────────────────────────────────────────────────────────
import clr
base_path = os.path.dirname(os.path.abspath(__file__))
DLL_DIR  = os.path.join(base_path, "dll")



dlls = [
    "bts.biodaq.core.dll",
    "FTD2XX_NET.dll",
    "log4net.dll",
    "Core.dll",
]

    
for name in dlls:
    #print(os.path.join(DLL_DIR, name))
    clr.AddReference(os.path.join(DLL_DIR, name))

from BTS.BioDAQ.Core import (
    BioDAQ, BioDAQExitStatus,
    Protocol, ProtocolItem, ChannelType,
    TriggerSource, DiskSink, TrialReader, TDFExporter, FileFormat,ProtocolItemState,QueueSink,SinkExitStatus
)

class FREEEMG(Device):
    def __init__(self) -> None:
        super().__init__()
        self.bio = BioDAQ()
        self.disk_sink = None
        self.attached = False
        self.protocol_applied = False
        self.fs = 1000
        self.num_channels = 4     # EMG1..EMG8 (ajústalo a tu equipo)
        self._stop_evt = threading.Event()
        self._reader_thread = None
        self._lock = threading.Lock()
        self._emg_rows: list[dict] = [] 
        self._last_ts = None

    def connect(self):
        st = self.bio.Attach()
        if st != BioDAQExitStatus.Success:
            raise RuntimeError(f"Attach failed: {st} ({int(st)})")
        self.bio.UpdateStatusInfo()
        self.attached = True
        self.qs = QueueSink()
        self.qs.Init()
        self.bio.Sinks.Add(self.qs)
        self.connected_sensors()
        self.fs = 1000
        return True
        
    def _ensure_attached(self):
        if not self.attached:
            raise RuntimeError("Llama attach() primero.")
        

    _bat_levels = {
        0:  "0% (Empty)",
        1:    "25% (Low)",
        2: "50% (Medium)",
        3:   "75% (High)",
        4:   "100% (Full)",
    }
    def connected_sensors(self):
            self._ensure_attached()
            self.bio.UpdateStatusInfo()
            connected = []

            for sview in self.bio.SensorsView.Values:
                label = getattr(sview, "Label", None) or getattr(sview, "SensorLabel", None) or "?"
                is_connected = getattr(sview, "Connected", False)
                batteryLevel = getattr(sview, "BattLevel", False)
            
                
                print(f"Sensor {label}: {'✅ Conectado, Battery ' + str(self._bat_levels[batteryLevel.value__]) if is_connected else '❌ Desconectado'}")
                if is_connected:
                    connected.append(label)

            return connected
    
    def start(self):
        
        self.bio.Trigger(TriggerSource.Software)
        st = self.bio.Arm()
        if st != BioDAQExitStatus.Success:
            raise RuntimeError(f"Arm failed: {st}")

        st = self.bio.Start()
        if st != BioDAQExitStatus.Success:
            raise RuntimeError(f"Start failed: {st}")
                # Lanzar hilo lector
        self._stop_evt.clear()
        self._reader_thread = threading.Thread(target=self._reader_loop, name="FEMGReader", daemon=True)
        self._reader_thread.start()
        self._started = True

    def stop(self,out_dir="."):
        """
        Stops acquisition, saves to CSV with default name, and cleans up BioDAQ.
        """
        try:
            st = self.bio.Stop()   
            if not self._started:
                return
            self._stop_evt.set()
            if self._reader_thread and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=1.0)
            self._reader_thread = None 
            self._started = False
        except Exception as e:
            print(f"[ERROR] Failed: {e}")


    # (Si suscribiste evento)
    # if hasattr(self, "_on_sink") and self._on_sink:
    #     self.bio.SinkDataReady -= self._on_sink
    #     self._on_sink = None
    def _reader_loop(self):
        """
        Hilo dedicado a vaciar la QueueSink y pasar datos a _emg_rows.
        Mantén un pequeño sleep para no quemar CPU si no hay datos.
        """
        while not self._stop_evt.is_set():
            got = self.read_queue_values()
            if not got:
                time.sleep((1.0 / self.fs)  * 2 )



    def disconnect(self):
        try: self.bio.Stop()
        except: pass
        try: self.bio.Sinks.Clear()
        except: pass
        try: self.bio.Reset()
        except: pass
        try: self.bio.Dispose()
        except: pass

        self.attached = False
        self.bio = None

        # Fuerza GC para que Windows suelte el puerto
        System.GC.Collect()
        System.GC.WaitForPendingFinalizers()
        System.GC.Collect()
        time.sleep(0.3)
    def read_queue_values(self) -> bool:
        """
        Lee todos los canales del QueueSink y agrega filas al buffer _emg_rows.
        Devuelve True si leyó algo, False si no había datos.
        """
        any_data = False
        ch_data = {}  # ch_idx -> list[float]

        # Lee por canal


        for ch_idx in range(0,self.num_channels-1):
            qsz = self.qs.QueueSize(int(ch_idx))
            if qsz <= 0:
                continue

            #values = Array.CreateInstance(Single, 0)
            status, values = self.qs.ReadDataBufferByChannel(ch_idx)
            if values is None:
                # print(f"[WARN] Canal {ch_idx} status: {status}")
                continue

            ch_data[ch_idx] = [float(v) for v in values]
            any_data = any_data or len(ch_data[ch_idx]) > 0

        if not any_data:
            return False

        # Reconstrucción por-muestra (filas con todas las columnas EMG)
        if self._last_ts is None:
            self._last_ts = pd.Timestamp.now() + pd.Timedelta(milliseconds=1000)
        # Aproxima timestamps centrados en "ahora"

        # Las últimas muestras acaban "ya"; retrocede (max_n-1)/fs
        delta = pd.Timedelta(seconds=1.0 / self.fs)
        t0 = self._last_ts 

        rows = []
        max_n = max(len(v) for v in ch_data.values())
        for i in range(max_n):
            ts = t0 + i * delta
            row = {"Timestamp": ts}
            for ch_idx in range(0, self.num_channels):
                if ch_idx in ch_data and i < len(ch_data[ch_idx]):
                    row[f"EMG{ch_idx+1}"] = ch_data[ch_idx][i]
                # else: si faltan muestras en ese canal, se omite la columna en esta fila
                
            rows.append(row)
            self._last_ts = rows[-1]["Timestamp"]
        with self._lock:
            self._emg_rows.extend(rows)

        # (Opcional) emitir a suscriptores aquí si quieres “live streaming”
        # self._emit_if_ready()

        return True
    def get_emg_df(self) -> pd.DataFrame:
        """
        Devuelve un DataFrame con las muestras de EMG acumuladas en _emg_rows.
        Espera filas tipo: {"Timestamp": time.time(), "EMG1": v1, "EMG2": v2, ...}
        """
        data_cols = []
        with self._lock:
            if not self._emg_rows:
                return pd.DataFrame()
            timestamps = [r["Timestamp"] for r in self._emg_rows]  # lista de segundos UNIX
            for sview in self.bio.SensorsView.Values:
                is_connected = getattr(sview, "Connected", False)
                
                if is_connected:
                    data_cols.append(f'EMG{sview.Label}')
           
# Convierte a índice datetime
            ts_index = pd.to_datetime(timestamps)

# Construye el DataFrame
            df = pd.DataFrame(
                [[row.get(col, None) for col in data_cols] for row in self._emg_rows],
                index=pd.DatetimeIndex(ts_index, name="Timestamp"),
                columns=data_cols
            )

            df = df.sort_index().infer_objects()   
            df.dropna()         
            return df
    


    def get_imu_df(self) -> pd.DataFrame:

        return pd.DataFrame()
    
if __name__ == "__main__":
    try:
        emg = FREEEMG()
        emg.connect()

        print("EMGSystem ya está inicializado.")

        sensores_ok = emg.connected_sensors()
        #emg.create_protocol(2)
        emg.start()

        time.sleep(2)  # Espera un poco para que se adquieran datos
        emg.print_queue_values()  # Imprime los valores adquiridos

        emg.stop()
        #emg.set_protocol()
        emg.disconnect()
    
    except Exception as e:
        print("Error:", e)
        emg.disconnect()