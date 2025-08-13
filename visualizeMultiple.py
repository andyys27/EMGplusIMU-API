
from _devices.MioTracker import MioTracker
from _devices.GSensor import GSensor
from _devices._utils.LivePlot import LivePlot


try:
        # Crear dispositivo
    dev = MioTracker(transport="serial", port="COM7", Fs=1000)
    gs = GSensor(com_port="COM8")
    dev.list_serial_devices()
        # dev = MioTracker(transport="websocket", websocketuri="ws://miotracker.local/start")

    dev.connect()
    gs.connect()
    dev.start()
    gs.start()

        # Graficar en vivo
    plotter = LivePlot(
        plots=[
            {"get_df": lambda: dev.get_all_data(), "title": "EMG"},
            {"get_df": lambda: gs.get_imu_df(), "title": "IMU"},
        ],
        window_sec=3,
        refresh_hz=30,
        title="EMG + IMU Live",
    )
    plotter.start()
    gs.stop()
    gs.disconnect()
    dev.stop()
    dev.disconnect()
except Exception as e:
    print(f"Error connecting {e}")
    try:
        gs.stop()
        gs.disconnect()
        dev.stop()
        dev.disconnect()
    except Exception as e:
        print(f"Error stopping/disconnecting Devices: {e}")

