"""Minimal RFC 6455 WebSocket server side for the dashboard (stdlib only).

The upgrade runs on the dashboard's BaseHTTPRequestHandler: ThreadingHTTPServer already
gives every connection its own thread, so each socket simply stays in its handler thread
until it closes. Only text messages carrying JSON objects are supported.

Security on top of the dashboard's Host check: the Origin must be the dashboard itself,
the first client message must be {"type": "hello", "token": <dashboard token>} (else close
4401) and a connection may send at most RATE_LIMIT frames per second (else close 4429).
"""
from __future__ import annotations

import base64
import collections
import hashlib
import json
import secrets
import socket
import struct
import threading
import time

from .models import utcnow

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
PATH = "/ws"
MAX_MESSAGE_BYTES = 1 << 20          # 1 MiB per (reassembled) message
RATE_LIMIT = 30                      # frames per second per connection
HELLO_TIMEOUT_SECONDS = 10.0
CLOSE_GRACE_SECONDS = 1.0

OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
CONTROL_OPS = {OP_CLOSE, OP_PING, OP_PONG}

CLOSE_NORMAL = 1000
CLOSE_GOING_AWAY = 1001
CLOSE_SERVICE_RESTART = 1012
CLOSE_PROTOCOL = 1002
CLOSE_UNSUPPORTED = 1003
CLOSE_INVALID_DATA = 1007
CLOSE_TOO_BIG = 1009
CLOSE_UNAUTHORIZED = 4401
CLOSE_RATE_LIMIT = 4429


def accept_key(key: str) -> str:
    """Sec-WebSocket-Accept for a Sec-WebSocket-Key (SHA-1 of key + GUID, base64)."""
    return base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest()).decode("ascii")


class HandshakeError(Exception):
    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _tokens(value: str | None) -> set[str]:
    return {p.strip().lower() for p in (value or "").split(",") if p.strip()}


def allowed_origins(port: int) -> set[str]:
    return {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}


def validate_upgrade(method: str, path: str, headers, port: int) -> str:
    """Check an upgrade request; return the Sec-WebSocket-Accept value or raise HandshakeError.

    The Host header is checked by the dashboard handler before routing reaches here.
    """
    if method != "GET" or path.split("?", 1)[0] != PATH:
        raise HandshakeError(404, "not found")
    if "upgrade" not in _tokens(headers.get("Connection")) or "websocket" not in _tokens(headers.get("Upgrade")):
        raise HandshakeError(400, "expected a WebSocket upgrade")
    if (headers.get("Sec-WebSocket-Version") or "").strip() != "13":
        raise HandshakeError(426, "unsupported WebSocket version")
    key = (headers.get("Sec-WebSocket-Key") or "").strip()
    try:
        raw = base64.b64decode(key.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError):
        raw = b""
    if len(raw) != 16:
        raise HandshakeError(400, "bad Sec-WebSocket-Key")
    if (headers.get("Origin") or "") not in allowed_origins(port):
        raise HandshakeError(403, "forbidden origin")
    return accept_key(key)


def _xor(payload: bytes, mask: bytes) -> bytes:
    if not payload:
        return payload
    n = len(payload)
    key = (mask * (n // 4 + 1))[:n]
    return (int.from_bytes(payload, "big") ^ int.from_bytes(key, "big")).to_bytes(n, "big")


def encode_frame(opcode: int, payload: bytes = b"", fin: bool = True, mask: bytes | None = None) -> bytes:
    """One frame. The server never masks; `mask` exists for test clients."""
    head = bytearray([(0x80 if fin else 0) | opcode])
    mbit = 0x80 if mask else 0
    n = len(payload)
    if n < 126:
        head.append(mbit | n)
    elif n < 1 << 16:
        head.append(mbit | 126)
        head += struct.pack("!H", n)
    else:
        head.append(mbit | 127)
        head += struct.pack("!Q", n)
    if mask:
        head += mask
        payload = _xor(payload, mask)
    return bytes(head) + payload


def close_payload(code: int, reason: str = "") -> bytes:
    raw = reason.encode("utf-8")[:123]
    return struct.pack("!H", code) + raw.decode("utf-8", "ignore").encode("utf-8")


def _valid_close_code(code: int) -> bool:
    return (1000 <= code <= 1014 and code not in (1004, 1005, 1006)) or 3000 <= code <= 4999


class ProtocolError(Exception):
    def __init__(self, code: int, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


class _Eof(Exception):
    pass


class WsConnection:
    """Server side of one upgraded socket. send_* is thread-safe; recv_* belongs to one reader thread."""

    def __init__(self, rfile, wfile, sock: socket.socket | None = None, *,
                 max_message: int = MAX_MESSAGE_BYTES, rate_limit: int = RATE_LIMIT, clock=time.monotonic):
        self.rfile, self.wfile, self.sock = rfile, wfile, sock
        self.max_message = max_message
        self.rate_limit = rate_limit
        self.clock = clock
        self._send_lock = threading.Lock()
        self._recent: collections.deque = collections.deque()
        self.close_sent = False
        self.close_received = False
        self.close_code: int | None = None       # code we sent (or echoed)
        self.peer_close_code: int | None = None
        self.done = threading.Event()             # the reader thread finished with this socket

    @property
    def closed(self) -> bool:
        return self.close_sent or self.close_received

    # ------------------------------------------------------------------ send
    def _write(self, data: bytes) -> bool:
        try:
            self.wfile.write(data)
            flush = getattr(self.wfile, "flush", None)
            if flush:
                flush()
            return True
        except (OSError, ValueError):
            return False

    def send_frame(self, opcode: int, payload: bytes = b"") -> bool:
        with self._send_lock:
            if self.close_sent:
                return False
            return self._write(encode_frame(opcode, payload))

    def send_text(self, text: str) -> bool:
        return self.send_frame(OP_TEXT, text.encode("utf-8"))

    def send_json(self, obj) -> bool:
        return self.send_text(json.dumps(obj, ensure_ascii=False, default=str))

    def close(self, code: int = CLOSE_NORMAL, reason: str = "") -> None:
        """Send one close frame (idempotent). The reader still drains the peer's reply."""
        with self._send_lock:
            if self.close_sent:
                return
            self.close_sent = True
            self.close_code = code
            self._write(encode_frame(OP_CLOSE, close_payload(code, reason)))

    def abort(self) -> None:
        """Unblock a reader stuck in recv (used on server shutdown)."""
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def settimeout(self, seconds: float | None) -> None:
        if self.sock is not None:
            self.sock.settimeout(seconds)

    # ------------------------------------------------------------------ receive
    def _read(self, n: int) -> bytes:
        data = self.rfile.read(n) if n else b""
        if len(data) != n:
            raise _Eof()
        return data

    def _tick(self) -> None:
        now = self.clock()
        self._recent.append(now)
        while self._recent and now - self._recent[0] >= 1.0:
            self._recent.popleft()
        if len(self._recent) > self.rate_limit:
            raise ProtocolError(CLOSE_RATE_LIMIT, "rate limit")

    def read_frame(self) -> tuple[bool, int, bytes]:
        b0, b1 = self._read(2)
        fin, opcode = bool(b0 & 0x80), b0 & 0x0F
        if b0 & 0x70:
            raise ProtocolError(CLOSE_PROTOCOL, "reserved bits set")
        if opcode not in (OP_CONT, OP_TEXT, OP_BINARY) and opcode not in CONTROL_OPS:
            raise ProtocolError(CLOSE_PROTOCOL, "reserved opcode")
        if not b1 & 0x80:
            raise ProtocolError(CLOSE_PROTOCOL, "client frames must be masked")
        n = b1 & 0x7F
        if n == 126:
            n = struct.unpack("!H", self._read(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", self._read(8))[0]
            if n >> 63:
                raise ProtocolError(CLOSE_PROTOCOL, "bad length")
        if opcode in CONTROL_OPS and (n > 125 or not fin):
            raise ProtocolError(CLOSE_PROTOCOL, "bad control frame")
        if n > self.max_message:
            raise ProtocolError(CLOSE_TOO_BIG, "message too big")
        mask = self._read(4)
        payload = _xor(self._read(n), mask)
        self._tick()
        return fin, opcode, payload

    def recv_text(self) -> str | None:
        """Next complete text message, or None once the connection is closed."""
        if self.close_received:
            return None
        parts: list[bytes] = []
        size = 0
        started = False
        try:
            while True:
                fin, opcode, payload = self.read_frame()
                if opcode == OP_PING:
                    self.send_frame(OP_PONG, payload)
                    continue
                if opcode == OP_PONG:
                    continue
                if opcode == OP_CLOSE:
                    self._on_close(payload)
                    return None
                if self.close_sent:          # closing: data frames are discarded until the peer's close
                    continue
                if opcode == OP_CONT:
                    if not started:
                        raise ProtocolError(CLOSE_PROTOCOL, "unexpected continuation")
                elif started:
                    raise ProtocolError(CLOSE_PROTOCOL, "expected continuation")
                elif opcode == OP_BINARY:
                    raise ProtocolError(CLOSE_UNSUPPORTED, "binary messages are not supported")
                started = True
                size += len(payload)
                if size > self.max_message:
                    raise ProtocolError(CLOSE_TOO_BIG, "message too big")
                parts.append(payload)
                if fin:
                    try:
                        return b"".join(parts).decode("utf-8")
                    except UnicodeDecodeError:
                        raise ProtocolError(CLOSE_INVALID_DATA, "invalid UTF-8") from None
        except ProtocolError as exc:
            self.close(exc.code, exc.reason)
            self.close_received = True       # do not wait for a peer that broke the protocol
            return None
        except socket.timeout:
            raise
        except (_Eof, OSError, ValueError):
            self.close_received = True
            return None

    def recv_json(self) -> dict | None:
        """Next JSON object, or None once closed. A non-object or invalid JSON closes with 1007."""
        text = self.recv_text()
        if text is None:
            return None
        try:
            obj = json.loads(text)
        except ValueError:
            obj = None
        if not isinstance(obj, dict):
            self.close(CLOSE_INVALID_DATA, "expected a JSON object")
            self.close_received = True
            return None
        return obj

    def _on_close(self, payload: bytes) -> None:
        self.close_received = True
        code = CLOSE_NORMAL
        if len(payload) == 1:
            code = CLOSE_PROTOCOL
        elif len(payload) >= 2:
            self.peer_close_code = struct.unpack("!H", payload[:2])[0]
            try:
                payload[2:].decode("utf-8")
                code = self.peer_close_code if _valid_close_code(self.peer_close_code) else CLOSE_PROTOCOL
            except UnicodeDecodeError:
                code = CLOSE_INVALID_DATA
        self.close(code)                     # echo (no-op if we already sent ours)

    def drain(self, timeout: float = CLOSE_GRACE_SECONDS) -> None:
        """After we sent close, wait briefly for the peer's close frame (clean closing handshake)."""
        if not self.close_sent or self.close_received:
            return
        try:
            self.settimeout(timeout)
            while self.recv_text() is not None:
                pass
        except (socket.timeout, OSError):
            pass


class Hub:
    """Tracks authenticated connections and their subscriptions; answers hello/ping."""

    def __init__(self, token, hello_timeout: float = HELLO_TIMEOUT_SECONDS, *, version: str = "unknown"):
        self._token = token                          # str, or a callable returning the current token
        self.hello_timeout = hello_timeout
        self.version = version
        self._lock = threading.Lock()
        self._subs: dict[WsConnection, set[str]] = {}
        self._pending: set[WsConnection] = set()      # upgraded but not yet authenticated
        self.handlers: dict[str, object] = {}         # message type -> fn(conn, msg), registered with on()
        self.closing = False
        self.close_code = CLOSE_GOING_AWAY
        self.close_reason = "server shutting down"

    @property
    def token(self) -> str:
        return self._token() if callable(self._token) else self._token

    # ------------------------------------------------------------------ registry
    def connections(self) -> list[WsConnection]:
        with self._lock:
            return list(self._subs)

    def subscriptions(self, conn: WsConnection) -> set[str]:
        with self._lock:
            return set(self._subs.get(conn, ()))

    def subscribe(self, conn: WsConnection, topics) -> None:
        with self._lock:
            if conn in self._subs:
                self._subs[conn].update(str(t) for t in topics)

    def unsubscribe(self, conn: WsConnection, topics) -> None:
        with self._lock:
            if conn in self._subs:
                self._subs[conn].difference_update(str(t) for t in topics)

    def on(self, kind: str, fn) -> None:
        """Register the handler of a client message type (ping/hello stay built in)."""
        self.handlers[kind] = fn

    def subscribed_topics(self) -> set[str]:
        with self._lock:
            return set().union(*self._subs.values()) if self._subs else set()

    def broadcast(self, topic: str, obj) -> int:
        with self._lock:
            targets = [c for c, subs in self._subs.items() if topic in subs]
        return sum(1 for c in targets if c.send_json(obj))

    # ------------------------------------------------------------------ lifecycle
    def handle_upgrade(self, handler, port: int) -> None:
        """Run the handshake on a BaseHTTPRequestHandler, then serve the socket in this thread."""
        handler.close_connection = True
        if self.closing:
            return handler._send(503, "shutting down", "text/plain")
        try:
            accept = validate_upgrade(handler.command, handler.path, handler.headers, port)
        except HandshakeError as exc:
            handler.send_response(exc.status)
            if exc.status == 426:
                handler.send_header("Sec-WebSocket-Version", "13")
            body = exc.reason.encode()
            handler.send_header("Content-Type", "text/plain")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
            return
        handler.send_response(101, "Switching Protocols")
        handler.send_header("Upgrade", "websocket")
        handler.send_header("Connection", "Upgrade")
        handler.send_header("Sec-WebSocket-Accept", accept)
        handler.end_headers()
        handler.wfile.flush()
        self.run(WsConnection(handler.rfile, handler.wfile, handler.connection))

    def run(self, conn: WsConnection) -> None:
        with self._lock:
            self._pending.add(conn)
        try:
            if not self._authenticate(conn):
                return
            self.dispatch(conn, {"type": "hello"})
            while True:
                msg = conn.recv_json()
                if msg is None:
                    break
                self.dispatch(conn, msg)
        except socket.timeout:
            conn.close(CLOSE_GOING_AWAY, "timeout")
        finally:
            with self._lock:
                self._pending.discard(conn)
                self._subs.pop(conn, None)
            conn.drain()
            conn.done.set()

    def _authenticate(self, conn: WsConnection) -> bool:
        conn.settimeout(self.hello_timeout)
        try:
            hello = conn.recv_json()
        except socket.timeout:
            hello = None
        token = hello.get("token") if hello else None
        ok = (hello is not None and hello.get("type") == "hello" and isinstance(token, str)
              and secrets.compare_digest(token.encode("utf-8"), self.token.encode("utf-8")))
        if not ok:
            conn.close(CLOSE_UNAUTHORIZED, "unauthorized")
            return False
        conn.settimeout(None)
        with self._lock:
            self._pending.discard(conn)
            if self.closing:
                conn.close(self.close_code, self.close_reason)
                return False
            self._subs[conn] = set()
        return True

    def dispatch(self, conn: WsConnection, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "ping":
            conn.send_json({"type": "pong"})
        elif kind == "hello":
            conn.send_json({"type": "welcome", "server_time": utcnow().isoformat(), "version": self.version})
        elif isinstance(kind, str) and kind in self.handlers:
            try:
                self.handlers[kind](conn, msg)
            except Exception:                    # a bad message must never kill the connection's reader thread
                conn.send_json({"type": "error", "error": "internal", "message_he": "שגיאה פנימית בטיפול בהודעה"})
        else:
            conn.send_json({"type": "error", "error": "unknown_type", "message_he": "סוג הודעה לא מוכר"})

    def close_all(self, grace: float = CLOSE_GRACE_SECONDS, *, code: int = CLOSE_GOING_AWAY,
                  reason: str = "server shutting down") -> None:
        """Close every socket with the lifecycle code, wait briefly, then force them shut."""
        with self._lock:
            self.closing = True
            self.close_code = code
            self.close_reason = reason
            conns = list(self._subs) + list(self._pending)
        for conn in conns:
            conn.close(code, reason)
        deadline = time.monotonic() + grace
        for conn in conns:
            if not conn.done.wait(max(0.0, deadline - time.monotonic())):
                conn.abort()
