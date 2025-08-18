# Devices Module

This package contains drivers and utilities for EMG and IMU hardware.

## Contents
- `Device.py` – abstract base class defining the common device API.
- `MioTracker.py` – driver for the MioTracker EMG+IMU device.
- `GSensor.py` – driver for the BTS GSensor inertial sensor.
- `FREEEMG.py` – interface for the BTS FREEEMG system.
- `_utils/` – transport helpers such as serial readers and WebSocket clients.
- `Plotting/` – live plotting utilities built with PyQt5 and pyqtgraph.
- `activityDetection/` – pluggable activity detectors and training helpers.

All device classes inherit from `Device` and expose methods to `connect`,
`start`, `stop` and `disconnect`, along with helpers to retrieve data as
`pandas.DataFrame` objects.
