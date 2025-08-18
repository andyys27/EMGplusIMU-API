
from _devices.MioTracker import MioTracker
from _devices.GSensor import GSensor
from _devices.Plotting.LivePlot import LivePlot
from _devices.FREEEMG import FREEEMG
from _devices._utils._utilsfn import list_serial_devices,exportCSV
from _devices.activityDetection.activityDetectors import FixedThresholdDetector, AdaptiveMADDetector, ModelDetector,ModelDetectorONNX
from _devices.Plotting.LivePlotActivity import LivePlotActivity

detector =  FixedThresholdDetector(fs=1000, window_sec=0.15, threshold=0.00001)
#detector = AdaptiveMADDetector(fs = 1000, window_sec=0.01,baseline_sec = 5)



list_serial_devices()
try:
    # Crear dispositivo
    dev = MioTracker(transport="websocket", port="COM6", Fs=500, gain=8)
    fr = FREEEMG()
    #sg = GSensor(com_port="COM8")
    

    devices = [fr]
    for device in devices:
        device.connect()
        device.start()
    

    

    plots = [
        

        
        {
            "get_df": lambda: fr.get_emg_df(channel='EMG1'),
            "title": "EMG",
            "detector": detector, 
            "overlay": "band",
            "line_y": 0.0,
        }, 
        {
            "get_df": lambda: fr.get_emg_df(channel='EMG2'),
            "title": "EMG",
            "detector": detector, 
            "overlay": "band",
            "line_y": 0.0,
        }, 
    ]

    plotter = LivePlotActivity(
        plots=plots,
        window_sec=5,
        refresh_hz=30.0,
        title="IMU + Activity",
    )

    plotter.start()
    for device in devices:
        try:
            exportCSV(device.get_emg_df(), f"{device.__class__.__name__}")
            device.stop()
            device.disconnect()
        except Exception as e:
            print(f"Error stopping/disconnecting {device}: {e}")

except Exception as e:
    print(f"Error connecting {e}")
    for device in devices:
            device.stop()
            device.disconnect()

