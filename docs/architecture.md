# Architecture Overview

```
DeviceFactory
    └── _devices/
          ├── Device (abstract base class)
          ├── MioTracker
          ├── GSensor
          ├── FREEEMG
          └── _utils/
                ├── UsbReader
                ├── WebSocketClient
                └── LivePlot
```

Each device extends the common `Device` interface providing:

- `connect` / `disconnect` lifecycle methods
- `start` / `stop` acquisition controls
- `get_emg_df` / `get_imu_df` data accessors returning pandas `DataFrame`

Utilities in `_utils` implement transport specifics such as serial USB packet
parsing and WebSocket communication. Live plotting is optional and powered by
PyQt5 and pyqtgraph.
