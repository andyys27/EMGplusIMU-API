"""Helpers for reading and writing binary data over serial links."""

from __future__ import annotations
import struct, time
from typing import Optional


class SerialTimeout(Exception):
    pass


class SerialCoder:
    """Safe read/write helpers for a file-like stream (e.g., pyserial)."""

    # ---- internal: read exactly n bytes or raise ----
    @staticmethod
    def _read_exact(s, n: int, timeout_s: Optional[float] = None) -> bytes:
        """
        Read exactly n bytes from stream s. Honors s.timeout if set.
        If timeout_s is provided, it caps the total wait.
        Raises SerialTimeout if not enough bytes arrive.
        """
        buf = bytearray()
        t0 = time.perf_counter()
        while len(buf) < n:
            chunk = s.read(n - len(buf))
            if chunk:
                buf.extend(chunk)
                continue
            # no data this iteration
            if timeout_s is not None and (time.perf_counter() - t0) > timeout_s:
                raise SerialTimeout(f"Needed {n} bytes, got {len(buf)}")
            # tiny yield to avoid busy-wait if nonblocking/zero timeout
            time.sleep(0.001)
        return bytes(buf)

    # ---- signed reads ----
    @staticmethod
    def read_s08(s, timeout_s: Optional[float] = None) -> int:
        return struct.unpack("<b", SerialCoder._read_exact(s, 1, timeout_s))[0]

    @staticmethod
    def read_s16(s, timeout_s: Optional[float] = None) -> int:
        return struct.unpack("<h", SerialCoder._read_exact(s, 2, timeout_s))[0]

    @staticmethod
    def read_s32(s, timeout_s: Optional[float] = None) -> int:
        return struct.unpack("<l", SerialCoder._read_exact(s, 4, timeout_s))[0]

    # ---- unsigned reads ----
    @staticmethod
    def read_u08(s, timeout_s: Optional[float] = None) -> int:
        return struct.unpack("<B", SerialCoder._read_exact(s, 1, timeout_s))[0]

    @staticmethod
    def read_u16(s, timeout_s: Optional[float] = None) -> int:
        return struct.unpack("<H", SerialCoder._read_exact(s, 2, timeout_s))[0]

    @staticmethod
    def read_u32(s, timeout_s: Optional[float] = None) -> int:
        return struct.unpack("<L", SerialCoder._read_exact(s, 4, timeout_s))[0]

    # ---- writes (validate ranges for unsigned) ----
    @staticmethod
    def write_s08(s, value: int) -> None:
        if not (-128 <= value <= 127):
            raise ValueError(f"s08 out of range: {value}")
        s.write(struct.pack("<b", value))

    @staticmethod
    def write_s16(s, value: int) -> None:
        if not (-32768 <= value <= 32767):
            raise ValueError(f"s16 out of range: {value}")
        s.write(struct.pack("<h", value))

    @staticmethod
    def write_s32(s, value: int) -> None:
        if not (-2147483648 <= value <= 2147483647):
            raise ValueError(f"s32 out of range: {value}")
        s.write(struct.pack("<l", value))

    @staticmethod
    def write_u08(s, value: int) -> None:
        if not (0 <= value <= 255):
            raise ValueError(f"u08 out of range: {value}")
        s.write(struct.pack("<B", value))

    @staticmethod
    def write_u16(s, value: int) -> None:
        if not (0 <= value <= 65535):
            raise ValueError(f"u16 out of range: {value}")
        s.write(struct.pack("<H", value))

    @staticmethod
    def write_u32(s, value: int) -> None:
        if not (0 <= value <= 0xFFFFFFFF):
            raise ValueError(f"u32 out of range: {value}")
        s.write(struct.pack("<L", value))
