"""Threaded USB packet reader used by MioTracker devices."""

from __future__ import annotations
import threading, time
from typing import Callable, List, Optional


class UsbReader(threading.Thread):
    """
    USB packet reader with a simple state machine:
      Sync1 (0xA5) -> Sync2 (0x5A) -> Type (u8) -> Size (u8) -> Payload (size-4 bytes)
    Delivers packets as (ptype: int, payload: bytes).
    """

    def __init__(self, ser, sCoder, debug: bool = False):
        super().__init__(daemon=True)
        self.ser = ser
        self.sCoder = sCoder
        self._subscribers: List[Callable[[int, bytes], None]] = []  # multi-callbacks
        self._stop_event = threading.Event()
        self.bytes_to_read = 0
        self.rxstate = "Sync1"
        self._ptype: Optional[int] = None
        self.debug = debug

    # ---- pub/sub API ---------------------------------------------------------
    def subscribe_packets(self, fn: Callable[[int, bytes], None]) -> None:
        """Subscribe to parsed USB packets (ptype, payload)."""
        if callable(fn) and fn not in self._subscribers:
            self._subscribers.append(fn)
            print("[USB] subscriber added")

    def unsubscribe_packets(self, fn: Callable[[int, bytes], None]) -> None:
        try:
            self._subscribers.remove(fn)
        except ValueError:
            pass

    def _emit_packet(self, ptype: int, payload: bytes) -> None:

        for fn in list(self._subscribers):
            try:
                fn(ptype, payload)
            except Exception:
                if self.debug:
                    print("[USB] subscriber raised, ignoring")

    # ---- control -------------------------------------------------------------
    def stop(self):
        self._stop_event.set()

    # ---- utilities -----------------------------------------------------------
    def _read_exact(self, n: int, timeout_s: float = 0.1) -> Optional[bytes]:
        """Read exactly n bytes or None on timeout/stop."""
        out = bytearray()
        t0 = time.perf_counter()
        while len(out) < n and not self._stop_event.is_set():
            chunk = self.ser.read(n - len(out))
            if chunk:
                out.extend(chunk)
            elif (time.perf_counter() - t0) > timeout_s:
                return None
        return bytes(out)

    # ---- main loop -----------------------------------------------------------
    def run(self):
        try:
            while not self._stop_event.is_set():
                try:
                    if self.rxstate == "Sync1":
                        self.bytes_to_read = 0
                        b = self.sCoder.read_u08(self.ser)
                        if b == 0xA5:
                            self.rxstate = "Sync2"
                        else:
                            self.rxstate = "Sync1"

                    elif self.rxstate == "Sync2":
                        b = self.sCoder.read_u08(self.ser)
                        if b == 0x5A:
                            self.rxstate = "Type"
                        else:
                            self.rxstate = "Sync1"

                    elif self.rxstate == "Type":
                        self._ptype = self.sCoder.read_u08(self.ser)
                        self.rxstate = "Size"

                    elif self.rxstate == "Size":
                        size = self.sCoder.read_u08(
                            self.ser
                        )  # 1-byte size per your GUI
                        if size < 4:
                            # invalid header; resync
                            self.rxstate = "Sync1"
                            continue
                        self.bytes_to_read = size - 4
                        self.rxstate = "Payload"

                    elif self.rxstate == "Payload":
                        payload = self._read_exact(self.bytes_to_read, timeout_s=0.1)
                        self.rxstate = "Sync1"
                        if payload is None:
                            if self.debug:
                                print("[USB] payload timeout")
                            continue
                        if self._ptype is None:
                            continue
                        self._emit_packet(self._ptype, payload)

                except Exception as e:
                    if self.debug:
                        print(f"[USB] loop error: {e!r}")
                    raise ValueError(f"[USB] USB reader error: {e!r}")

                    # keep silent like GUI
                    pass
        finally:
            try:
                self.ser.close()
            except Exception:
                pass
