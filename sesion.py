from _devices.FREEEMG import FREEEMG
from _devices.GSensor import GSensor
from _devices._utils.recorder import StreamRecorder
from _devices._utils.marker_server import UnityMarkerServer
from _devices.Plotting.LivePlot import LivePlot
import time

# FREEEMG: sin límite de duración
fr = FREEEMG(num_channels=4, fs=1000, buffer_sec=None)
gs = GSensor(com_port="COM7")  # cambia por tu puerto real

fr.connect()
gs.connect()

fr.start()
gs.start()

rec = StreamRecorder({"free": fr, "gs": gs}, "sesion01", out_dir="recordings")
rec.start()

srv = UnityMarkerServer(
    "recordings/sesion01_unity_events.csv",
    port=5005,
    recorder=rec
)
srv.start()

plotter = LivePlot(
    plots=[
        {"get_df": lambda: fr.get_emg_df(), "title": "FREEEMG"},
        {"get_df": lambda: gs.get_imu_df(), "title": "GSensor"}
    ],
    window_sec=5,
    refresh_hz=30,
    title="FREEEMG + GSensor"
)

plotter.start()

print("Grabando datos...")
time.sleep(300)  # 5 minutos de prueba

rec.stop()
srv.stop()
fr.stop()
gs.stop()
fr.disconnect()
gs.disconnect()