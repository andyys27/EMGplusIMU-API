"""Factory helpers for creating EMG and IMU device instances."""

from _devices.MioTracker import MioTracker


class DeviceFactory:
    """Factory class able to instantiate supported devices by name."""

    @staticmethod
    def create(name: str, **kwargs):
        """Return an initialized device matching ``name``.

        Parameters
        ----------
        name:
            Identifier of the desired device. Currently only ``"miotracker"``
            is supported.
        **kwargs:
            Additional keyword arguments forwarded to the device constructor.
        """
        name = name.lower()
        if name == "miotracker":
            return MioTracker(**kwargs)
        # elif name == "freeemg":
        #     return FreeEMGDevice()
        # else:
        #     raise ValueError(f"Unknown device: {name}")


if __name__ == "__main__":
    DeviceFactory.create(
        "miotracker", transport="websocket", websocketuri="ws://miotracker.local/start"
    )
