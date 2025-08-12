"""Minimal WebSocket client with callback support."""

import threading
from typing import Callable, List, Optional, Union
import websocket

Message = Union[str, bytes]


class WebSocketClient:
    """Minimal, Qt-free WebSocket client with callbacks and a background thread."""

    def __init__(self, url: str):
        self.url = url
        self._callbacks: List[Callable[[Message], None]] = []
        self._app: Optional[websocket.WebSocketApp] = None
        self._th: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # ---- public API ----
    def subscribe(self, fn: Callable[[Message], None]) -> None:
        """Register a function that receives each incoming message (text or bytes)."""
        if callable(fn) and fn not in self._callbacks:
            self._callbacks.append(fn)

    def desubscribe(self) -> None:
        self._callbacks: List[Callable[[Message], None]] = []

    def connect(self) -> None:
        """Start the background receiver (non-blocking)."""
        if self._th and self._th.is_alive():
            return  # already running
        self._stop.clear()
        self._app = websocket.WebSocketApp(
            self.url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        def _runner():
            # reconnect loop until close() is called
            while not self._stop.is_set():
                try:
                    self._app.run_forever(
                        ping_interval=20, ping_timeout=10, reconnect=5
                    )
                except Exception as e:
                    print(f"[WebSocketClient] run_forever error: {e}")
                if not self._stop.is_set():
                    # small backoff before retry
                    import time

                    time.sleep(2)

        self._th = threading.Thread(target=_runner, daemon=True)
        self._th.start()

    def disconnect(self) -> None:
        if self._th and self._th.is_alive():
            self._th.join(timeout=1.0)
        self._th = None
        self._app = None
        print("[WebSocketClient] closed")

    def send(self, data: Message) -> None:
        """Send text (str) or binary (bytes/bytearray) to the server."""
        app = self._app
        if not app or not getattr(app, "sock", None) or not app.sock.connected:
            print("[WebSocketClient] send() ignored: not connected")
            return
        try:
            if isinstance(data, (bytes, bytearray)):
                app.send(data, opcode=websocket.ABNF.OPCODE_BINARY)
            else:
                app.send(str(data), opcode=websocket.ABNF.OPCODE_TEXT)
        except Exception as e:
            print(f"[WebSocketClient] send error: {e}")

    # ---- internals ----
    def _emit(self, msg: Message) -> None:
        for fn in list(self._callbacks):
            try:
                fn(msg)
            except Exception as e:
                print(f"[WebSocketClient] callback error: {e}")

    # WebSocketApp event handlers
    def _on_open(self, _ws):
        print(f"[WebSocketClient] connected to {self.url}")

    def _on_message(self, _ws, message: Message):
        self._emit(message)

    def _on_error(self, _ws, error):
        print(f"[WebSocketClient] error: {error}")

    def _on_close(self, _ws, code, reason):
        print(f"[WebSocketClient] closed: code={code} reason={reason}")
