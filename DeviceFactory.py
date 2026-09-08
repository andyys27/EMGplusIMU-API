"""Factory helpers for creating EMG and IMU device instances.

Esta versión agrega los drivers reconstruidos nativos-Linux
(GSensorLinux, FREEEMGLinux) junto a los originales. Los originales
Windows-only se siguen pudiendo deshabilitar con
`EMGPLUSIMU_DISABLE_WINDOWS_MODULES=1`, independientemente de los nuevos.
"""

import os
from _devices.MioTracker import MioTracker

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

# Drivers Linux nativos (reversados). Disponibles siempre que sus
# dependencias (pyserial / ftd2xx) estén instaladas, sin importar
# EMGPLUSIMU_DISABLE_WINDOWS_MODULES.
_HAS_GSENSOR_LINUX = False
_HAS_FREEEMG_LINUX = False
try:
    from _devices.GSensorLinux import GSensorLinux
    _HAS_GSENSOR_LINUX = True
except Exception:
    _HAS_GSENSOR_LINUX = False

try:
    from _devices.FREEEMGLinux import FREEEMGLinux
    _HAS_FREEEMG_LINUX = True
except Exception:
    _HAS_FREEEMG_LINUX = False


class DeviceFactory:
    """Factory class able to instantiate supported devices by name."""

    @staticmethod
    def create(name: str, **kwargs):
        """Return an initialized device matching ``name``.

        Nombres soportados:
            "miotracker"     -> multiplataforma
            "freeemg"        -> driver original (Windows, SDK BTS)
            "gsensor"        -> driver original (Windows, SDK BTS)
            "gsensor_linux"  -> reconstrucción nativa Linux (BT SPP directo)
            "freeemg_linux"  -> reconstrucción nativa Linux (D2XX directo)
        """
        name = name.lower()
        if name == "miotracker":
            return MioTracker(**kwargs)

        if name == "freeemg":
            if not _HAS_FREEEMG:
                raise RuntimeError(
                    "FREEEMG driver not available (pythonnet/BTS SDK missing) or "
                    "disabled via EMGPLUSIMU_DISABLE_WINDOWS_MODULES"
                )
            return FREEEMG(**kwargs)

        if name == "gsensor":
            if not _HAS_GSENSOR:
                raise RuntimeError(
                    "GSensor driver not available (pythonnet/BTS SDK missing) or "
                    "disabled via EMGPLUSIMU_DISABLE_WINDOWS_MODULES"
                )
            return GSensor(**kwargs)

        if name == "gsensor_linux":
            if not _HAS_GSENSOR_LINUX:
                raise RuntimeError(
                    "GSensorLinux no disponible: falta pyserial o hubo un error de import. "
                    "Recuerda además que requiere completar las constantes de protocolo "
                    "en _devices/GSensorLinux.py antes de que produzca datos válidos."
                )
            return GSensorLinux(**kwargs)

        if name == "freeemg_linux":
            if not _HAS_FREEEMG_LINUX:
                raise RuntimeError(
                    "FREEEMGLinux no disponible: falta ftd2xx/libftd2xx o hubo un error de "
                    "import. Recuerda además que requiere completar las constantes de "
                    "protocolo en _devices/FREEEMGLinux.py antes de que produzca datos válidos."
                )
            return FREEEMGLinux(**kwargs)

        raise ValueError(f"Unknown device: {name}")


if __name__ == "__main__":
    DeviceFactory.create(
        "miotracker", transport="websocket", websocketuri="ws://miotracker.local/start"
    )