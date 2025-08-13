# SDK

Python modules for interfacing with EMG and IMU devices. The package exposes a small factory for constructing device instances and a collection of implementations and utilities under `_devices`.

## Structure

- **`DeviceFactory.py`** – factory helper that creates a device based on its name.
- **`_devices/`** – concrete device implementations and supporting utilities:
  - `MioTracker.py` – driver for MioTracker sensors with WebSocket and USB transports.
  - `_utils/` – reusable helpers such as the threaded USB reader and live plotting tools.

## Usage

```python
from SDK.DeviceFactory import DeviceFactory

# Create a MioTracker using the WebSocket transport
tracker = DeviceFactory.create(
    "miotracker",
    transport="websocket",
    websocketuri="ws://miotracker.local/start",
)

# Begin streaming data
tracker.start()
```

See the docstrings within each module for details on available parameters and features.

## Extending

To add support for a new device:

1. Implement a subclass of `Device` inside the `_devices` package.
2. Register the device in `DeviceFactory.create` by matching on its name.

This allows applications to request the new device simply by name.
