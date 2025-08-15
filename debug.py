
from _devices.MioTracker import MioTracker
from _devices.GSensor import GSensor
from _devices.Plotting.LivePlot import LivePlot
from _devices.FREEEMG import FREEEMG
from _devices._utils._utilsfn import list_serial_devices 
from _devices._utils._utilsfn import exportCSV
from _devices.activityDetection.activityDetectors import FixedThresholdDetector, AdaptiveMADDetector, ModelDetector
from _devices.Plotting.LivePlotActivity import LivePlotActivity

detector =  FixedThresholdDetector(fs=500, window_sec=0.001)

list_serial_devices()
try:
    devices = None
    # Crear dispositivo
    dev = MioTracker(transport="serial", port="COM7", Fs=500, gain=8)
    #free = FREEEMG()
    #sg = GSensor(com_port="COM8")
    

    devices = [dev]
    for device in devices:
        device.connect()
        device.start()
    

    

    plots = [
        {
            "get_df": lambda: dev.get_imu_df(),
            "title": "IMU",
            "detector": detector, 
            "overlay": "band",
            "line_y": 0.0,
        },
    ]

    plotter = LivePlotActivity(
        plots=plots,
        window_sec=30,
        refresh_hz=30.0,
        title="IMU + Activity",
    )

    plotter.start()

    for device in devices:
        try:
            device.stop()
            device.disconnect()
        except Exception as e:
            print(f"Error stopping/disconnecting {device}: {e}")

except Exception as e:
    print(f"Error connecting {e}")
    for device in devices:
        try:
            device.stop()
            device.disconnect()
        except Exception as e:
            print(f"Error stopping/disconnecting {device}: {e}")

