
from _devices.MioTracker import MioTracker
from _devices.GSensor import GSensor
from _devices._utils.LivePlot import LivePlot
from _devices.FREEEMG import FREEEMG

try:
    devices = None
    # Crear dispositivo
    dev = MioTracker(transport="serial", port="COM7", Fs=1000)
    free = FREEEMG()
    sg = GSensor(com_port="COM8")
    

    devices = [dev, free, sg]
    for device in devices:
        device.connect()
        device.start()
    



        # Graficar en vivo
    plotter = LivePlot(
        plots=[
            {"get_df": lambda: dev.get_imu_df(), "title": "MioTracker EMG + IMU"},
            {"get_df": lambda: dev.get_emg_df(onlyraw=True), "title": "MioTracker EMG + IMU"},
            {"get_df": lambda: sg.get_imu_df(), "title": "BAIOBIT IMU"},
            {"get_df": lambda: free.get_emg_df(), "title": "FREEEMG EMG"},
        ],
        window_sec=3,
        refresh_hz=30,
        title="EMG + IMU Live",
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

