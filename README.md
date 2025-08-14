# EMGplusIMU-API

EMGplusIMU-API provides a unified Python interface for electromyography (EMG) and inertial measurement unit (IMU) devices. It includes ready-to-use drivers for MioTracker, FREEEMG and BTS GSensor hardware, delivering synchronized data streams as pandas `DataFrame` objects and optional live visualisation utilities.

## Features
- Factory pattern to instantiate supported devices by name
- Serial and WebSocket transports for flexible connectivity
- Thread-safe buffering of EMG and IMU samples
- Live plotting via PyQt5/pyqtgraph
- Export of data to CSV using pandas

## Requirements
- Python 3.8 or newer
- Recommended packages:
  - `pandas`, `numpy`
  - `pyserial`, `websocket-client`
  - `pythonnet` (required for BTS devices on Windows)
  - `PyQt5`, `pyqtgraph` for live plots

## Installation
```bash
# clone repository
git clone https://github.com/your-user/EMGplusIMU-API.git
cd EMGplusIMU-API

# install dependencies
pip install pandas numpy pyserial websocket-client pythonnet PyQt5 pyqtgraph
```

## Usage
Create a device using the factory and acquire EMG/IMU data:
```python
from DeviceFactory import DeviceFactory

# create and start a MioTracker device
mt = DeviceFactory.create(
    "miotracker", transport="websocket", websocketuri="ws://miotracker.local/start"
)
mt.connect()
mt.start()

# obtain a pandas DataFrame with EMG samples
df_emg = mt.get_emg_df()
mt.stop()
mt.disconnect()
```

## Project Structure
```
EMGplusIMU-API/
├── DeviceFactory.py        # factory for creating devices
├── _devices/
│   ├── Device.py           # abstract base class
│   ├── MioTracker.py       # MioTracker driver
│   ├── GSensor.py          # BTS GSensor driver
│   ├── FREEEMG.py          # FREEEMG driver
│   └── _utils/             # shared utilities (USB reader, WebSocket client, plots)
├── debug.py                # example script for multiple devices
├── visualizeMultiple.py    # plotting example
└── docs/                   # additional documentation
```

## Credits
Created and maintained by the EMGplusIMU-API contributors.

## License
This project is licensed under the [MIT License](LICENSE).
