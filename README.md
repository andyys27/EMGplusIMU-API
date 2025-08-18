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
# Installation Guide

## 1. Create the Conda Environment (32-bit)
```bash
conda create -n emgplusimu python=3.8 --platform win-32
```

## 2. Activate the Environment
```bash
conda activate emgplusimu
```

## 3. Install Dependencies
```bash
pip install -r requirements.txt
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

## Citation
If you use this, please cite the following reference:

> Fuentes-Aguilar, R.Q., Llorente-Vidrio, D., Campos-Macias, L., *et
> al.*\
> *Surface electromyography dataset from different movements of the hand
> using a portable and a non-portable device.*\
> *Data in Brief*, 57, 111079, 2025.\
> https://doi.org/10.1016/j.dib.2025.111079

## BibTeX

``` bibtex
@article{FuentesAguilar2025EMG,
  title={Surface electromyography dataset from different movements of the hand using a portable and a non-portable device},
  author={Fuentes-Aguilar, R.Q. and Llorente-Vidrio, D. and Campos-Macias, L. and others},
  journal={Data in Brief},
  volume={57},
  pages={111079},
  year={2025},
  publisher={Elsevier},
  doi={10.1016/j.dib.2025.111079}
}
