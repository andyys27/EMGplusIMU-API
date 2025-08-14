# Advanced Examples

## Live Plotting
Use the built-in `LivePlot` utility to visualise streaming data:

```python
from _devices.MioTracker import MioTracker
from _devices._utils.LivePlot import LivePlot

mt = MioTracker(transport="serial", port="COM7")
mt.connect()
mt.start()

plotter = LivePlot(
    plots=[
        {"get_df": lambda: mt.get_emg_df(onlyraw=True), "title": "EMG"},
        {"get_df": lambda: mt.get_imu_df(), "title": "IMU"},
    ],
    window_sec=3,
    refresh_hz=30,
    title="EMG + IMU Live",
)
plotter.start()
```

## Multiple Devices

```python
from _devices.MioTracker import MioTracker
from _devices.GSensor import GSensor

mt = MioTracker(transport="websocket", websocketuri="ws://miotracker.local/start")
gs = GSensor(com_port="COM8")

for dev in (mt, gs):
    dev.connect()
    dev.start()

# ... use devices ...

for dev in (mt, gs):
    dev.stop()
    dev.disconnect()
```
