# Quick Start

This guide shows how to quickly acquire EMG and IMU data using a supported device.

```bash
pip install pandas numpy pyserial websocket-client pythonnet PyQt5 pyqtgraph
```

```python
from DeviceFactory import DeviceFactory

# Create a MioTracker and acquire 5 seconds of data
mt = DeviceFactory.create(
    "miotracker", transport="websocket", websocketuri="ws://miotracker.local/start"
)
mt.connect()
mt.start()

# ... acquire data ...

time.sleep(5)
mt.stop()

df = mt.get_all_data()
print(df.head())
mt.disconnect()
```
