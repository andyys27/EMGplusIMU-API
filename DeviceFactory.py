"""Factory helpers for creating EMG and IMU device instances.

This factory exposes available drivers and allows disabling Windows-only
modules via the environment variable `EMGPLUSIMU_DISABLE_WINDOWS_MODULES=1`.
"""

import os
from _devices.MioTracker import MioTracker

# Attempt to import optional Windows-only drivers. If imports fail or the
# environment requests disabling, the drivers will not be available.
_DISABLE_WIN = bool(os.environ.get("EMGPLUSIMU_DISABLE_WINDOWS_MODULES", "0") in ("1", "true", "True"))

_HAS_FREEEMG = False
_HAS_GSENSOR = False
if not _DISABLE_WIN:
    try:
        from _devices.FREEEMG import FREEEMG
        _HAS_FREEEMG = True
    except Exception:
        _HAS_FREEEMG = False

    try:
        from _devices.GSensor import GSensor
        _HAS_GSENSOR = True
    except Exception:
        _HAS_GSENSOR = False


class DeviceFactory:
    """Factory class able to instantiate supported devices by name."""

    @staticmethod
    def create(name: str, **kwargs):
        """Return an initialized device matching ``name``.

        Parameters
        ----------
        name:
            Identifier of the desired device. Supported values include
            ``"miotracker"``, and optionally ``"freeemg"`` and ``"gsensor"``
            when the corresponding drivers are available and not disabled.
        **kwargs:
            Additional keyword arguments forwarded to the device constructor.
        """
        name = name.lower()
        if name == "miotracker":
            return MioTracker(**kwargs)
        if name == "freeemg":
            if not _HAS_FREEEMG:
                raise RuntimeError("FREEEMG driver not available (pythonnet/BTS SDK missing) or disabled via EMGPLUSIMU_DISABLE_WINDOWS_MODULES")
            return FREEEMG(**kwargs)
        if name == "gsensor":
            if not _HAS_GSENSOR:
                raise RuntimeError("GSensor driver not available (pythonnet/BTS SDK missing) or disabled via EMGPLUSIMU_DISABLE_WINDOWS_MODULES")
            return GSensor(**kwargs)

        raise ValueError(f"Unknown device: {name}")


if __name__ == "__main__":
    DeviceFactory.create(
        "miotracker", transport="websocket", websocketuri="ws://miotracker.local/start"
    )
