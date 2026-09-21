from _devices.FREEEMG import FREEEMG
from _devices._utils.recorder import StreamRecorder
from _devices._utils.marker_server import UnityMarkerServer

name = "sesion01"
fr = FREEEMG(num_channels=4, fs=1000)
fr.connect()
rec = StreamRecorder({"free": fr}, name, out_dir="recordings")
srv = UnityMarkerServer(f"recordings/{name}_unity_events.csv", port=5005, recorder=rec)
try:
    srv.start(); fr.start(); rec.start()
    input("Grabando EMG. Da Play en Unity; Enter aquí al terminar la secuencia...")
finally:
    rec.stop(); srv.stop(); fr.disconnect()