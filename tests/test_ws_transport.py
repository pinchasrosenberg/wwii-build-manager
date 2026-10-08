"""RFC 6455 transport of the dashboard (wwii_build.ws): handshake, framing, security, live round trip."""
from __future__ import annotations

import base64
import io
import json
import os
import socket
import struct
import threading
import time
import unittest
import urllib.request

from helpers import FakeEnv, TmpTestCase, init_repo

from wwii_build import ws
from wwii_build.dashboard import Dashboard

MASK = b"\x37\xfa\x21\x3d"


def client_frame(opcode: int, payload: bytes = b"", fin: bool = True) -> bytes:
    return ws.encode_frame(opcode, payload, fin=fin, mask=MASK)


def conn_for(data: bytes, **kw) -> tuple[ws.WsConnection, io.BytesIO]:
    out = io.BytesIO()
    return ws.WsConnection(io.BytesIO(data), out, **kw), out


def server_frames(raw: bytes) -> list[tuple[int, bytes]]:
    """Decode unmasked server frames from a byte string."""
    frames, i = [], 0
    while i < len(raw):
        op, n = raw[i] & 0x0F, raw[i + 1] & 0x7F
        i += 2
        if n == 126:
            n, i = struct.unpack("!H", raw[i:i + 2])[0], i + 2
        elif n == 127:
            n, i = struct.unpack("!Q", raw[i:i + 8])[0], i + 8
        frames.append((op, raw[i:i + n]))
        i += n
    return frames


def close_code(payload: bytes) -> int:
    return struct.unpack("!H", payload[:2])[0]


class Handshake(unittest.TestCase):
    HEADERS = {"Connection": "keep-alive, Upgrade", "Upgrade": "websocket", "Sec-WebSocket-Version": "13",
               "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==", "Origin": "http://127.0.0.1:8765"}  # gitleaks:allow (RFC 6455 sample nonce)

    def test_accept_value_matches_rfc_example(self):
        self.assertEqual(ws.accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")
        self.assertEqual(ws.validate_upgrade("GET", "/ws", self.HEADERS, 8765), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_localhost_origin_is_allowed(self):
        h = dict(self.HEADERS, Origin="http://localhost:8765")
        self.assertTrue(ws.validate_upgrade("GET", "/ws", h, 8765))

    def test_rejections(self):
        cases = [
            ({"Origin": "http://evil.example"}, 403),
            ({"Origin": "http://127.0.0.1:9999"}, 403),
            ({"Origin": "https://127.0.0.1:8765"}, 403),
            ({"Origin": ""}, 403),
            ({"Upgrade": "h2c"}, 400),
            ({"Connection": "keep-alive"}, 400),
            ({"Sec-WebSocket-Version": "8"}, 426),
            ({"Sec-WebSocket-Key": "short"}, 400),
        ]
        for override, status in cases:
            with self.subTest(override=override):
                with self.assertRaises(ws.HandshakeError) as cm:
                    ws.validate_upgrade("GET", "/ws", dict(self.HEADERS, **override), 8765)
                self.assertEqual(cm.exception.status, status)


class Framing(unittest.TestCase):
    def test_masked_frame_decoding_rfc_example(self):
        raw = bytes([0x81, 0x85, 0x37, 0xfa, 0x21, 0x3d, 0x7f, 0x9f, 0x4d, 0x51, 0x58])
        conn, _ = conn_for(raw)
        self.assertEqual(conn.recv_text(), "Hello")

    def test_unmasked_client_frame_is_protocol_error(self):
        conn, out = conn_for(ws.encode_frame(ws.OP_TEXT, b"hi"))
        self.assertIsNone(conn.recv_text())
        op, payload = server_frames(out.getvalue())[-1]
        self.assertEqual((op, close_code(payload)), (ws.OP_CLOSE, ws.CLOSE_PROTOCOL))

    def test_16_and_64_bit_lengths(self):
        for size, marker in ((200, 126), (70000, 127)):
            with self.subTest(size=size):
                text = "א" * (size // 2)               # 2 UTF-8 bytes each
                frame = client_frame(ws.OP_TEXT, text.encode())
                self.assertEqual(frame[1] & 0x7F, marker)
                conn, out = conn_for(frame)
                self.assertEqual(conn.recv_text(), text)
                conn.send_text(text)
                self.assertEqual(out.getvalue()[1], marker)   # server frames are unmasked
                self.assertEqual(server_frames(out.getvalue()), [(ws.OP_TEXT, text.encode())])

    def test_continuation_and_interleaved_ping(self):
        data = (client_frame(ws.OP_TEXT, b'{"type":', fin=False) + client_frame(ws.OP_PING, b"p1")
                + client_frame(ws.OP_CONT, b'"ping"}'))
        conn, out = conn_for(data)
        self.assertEqual(conn.recv_json(), {"type": "ping"})
        self.assertEqual(server_frames(out.getvalue()), [(ws.OP_PONG, b"p1")])

    def test_stray_continuation_is_protocol_error(self):
        conn, out = conn_for(client_frame(ws.OP_CONT, b"x"))
        self.assertIsNone(conn.recv_text())
        self.assertEqual(close_code(server_frames(out.getvalue())[-1][1]), ws.CLOSE_PROTOCOL)

    def test_oversize_frame_and_oversize_fragments_close_1009(self):
        big = client_frame(ws.OP_TEXT, b"x" * (ws.MAX_MESSAGE_BYTES + 1))
        frag = client_frame(ws.OP_TEXT, b"x" * 600_000, fin=False) + client_frame(ws.OP_CONT, b"x" * 600_000)
        for data in (big, frag):
            conn, out = conn_for(data)
            self.assertIsNone(conn.recv_text())
            op, payload = server_frames(out.getvalue())[-1]
            self.assertEqual((op, close_code(payload)), (ws.OP_CLOSE, ws.CLOSE_TOO_BIG))

    def test_declared_64_bit_oversize_is_rejected_before_reading(self):
        head = bytes([0x81, 0x80 | 127]) + struct.pack("!Q", 1 << 40) + MASK   # no payload follows
        conn, out = conn_for(head)
        self.assertIsNone(conn.recv_text())
        self.assertEqual(close_code(server_frames(out.getvalue())[-1][1]), ws.CLOSE_TOO_BIG)

    def test_invalid_utf8_closes_1007(self):
        conn, out = conn_for(client_frame(ws.OP_TEXT, b"\xff\xfe"))
        self.assertIsNone(conn.recv_text())
        self.assertEqual(close_code(server_frames(out.getvalue())[-1][1]), ws.CLOSE_INVALID_DATA)

    def test_non_object_json_closes_1007(self):
        conn, out = conn_for(client_frame(ws.OP_TEXT, b"[1,2]"))
        self.assertIsNone(conn.recv_json())
        self.assertEqual(close_code(server_frames(out.getvalue())[-1][1]), ws.CLOSE_INVALID_DATA)

    def test_binary_closes_1003(self):
        conn, out = conn_for(client_frame(ws.OP_BINARY, b"\x00"))
        self.assertIsNone(conn.recv_text())
        self.assertEqual(close_code(server_frames(out.getvalue())[-1][1]), ws.CLOSE_UNSUPPORTED)

    def test_client_close_is_echoed(self):
        conn, out = conn_for(client_frame(ws.OP_CLOSE, ws.close_payload(1000, "bye")))
        self.assertIsNone(conn.recv_text())
        self.assertEqual(conn.peer_close_code, 1000)
        op, payload = server_frames(out.getvalue())[-1]
        self.assertEqual((op, close_code(payload)), (ws.OP_CLOSE, 1000))
        self.assertFalse(conn.send_json({"type": "late"}))      # nothing is sent after close

    def test_rate_limit_closes_4429(self):
        now = [100.0]
        data = b"".join(client_frame(ws.OP_TEXT, b'{"type":"ping"}') for _ in range(ws.RATE_LIMIT + 1))
        conn, out = conn_for(data, clock=lambda: now[0])
        for _ in range(ws.RATE_LIMIT):
            self.assertEqual(conn.recv_json(), {"type": "ping"})
        self.assertIsNone(conn.recv_json())
        self.assertEqual(close_code(server_frames(out.getvalue())[-1][1]), ws.CLOSE_RATE_LIMIT)

    def test_rate_limit_window_slides(self):
        now = [100.0]
        data = b"".join(client_frame(ws.OP_TEXT, b'{"type":"ping"}') for _ in range(ws.RATE_LIMIT * 2))
        conn, _ = conn_for(data, clock=lambda: now[0])
        for i in range(ws.RATE_LIMIT * 2):
            if i == ws.RATE_LIMIT:
                now[0] += 1.0
            self.assertEqual(conn.recv_json(), {"type": "ping"})

    def test_send_is_thread_safe(self):
        conn, out = conn_for(b"")
        threads = [threading.Thread(target=lambda: [conn.send_json({"n": "x" * 300}) for _ in range(50)])
                   for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        frames = server_frames(out.getvalue())
        self.assertEqual(len(frames), 400)
        self.assertTrue(all(json.loads(p) == {"n": "x" * 300} for _, p in frames))


class HubUnit(unittest.TestCase):
    def run_hub(self, data: bytes, token: str = "secret-token") -> list[tuple[int, bytes]]:
        conn, out = conn_for(data)
        ws.Hub(token, version="synthetic-version").run(conn)
        self.assertTrue(conn.done.is_set())
        return server_frames(out.getvalue())

    def hello(self, token: str) -> bytes:
        return client_frame(ws.OP_TEXT, json.dumps({"type": "hello", "token": token}).encode())

    def test_good_hello_then_ping(self):
        frames = self.run_hub(self.hello("secret-token") + client_frame(ws.OP_TEXT, b'{"type":"ping"}')
                              + client_frame(ws.OP_CLOSE, ws.close_payload(1000)))
        welcome = json.loads(frames[0][1])
        self.assertEqual(welcome["type"], "welcome")
        self.assertIn("T", welcome["server_time"])
        self.assertEqual(welcome["version"], "synthetic-version")
        self.assertEqual(json.loads(frames[1][1]), {"type": "pong"})
        self.assertEqual(close_code(frames[2][1]), 1000)

    def test_bad_or_missing_token_closes_4401(self):
        for first in (self.hello("wrong"), self.hello("סוד"), client_frame(ws.OP_TEXT, b'{"type":"ping"}'),
                      client_frame(ws.OP_TEXT, b'{"type":"hello","token":5}')):
            with self.subTest(first=first):
                frames = self.run_hub(first + client_frame(ws.OP_TEXT, b'{"type":"ping"}'))
                self.assertEqual(len(frames), 1)
                self.assertEqual((frames[0][0], close_code(frames[0][1])), (ws.OP_CLOSE, ws.CLOSE_UNAUTHORIZED))

    def test_service_restart_closes_connections_with_1012(self):
        self.assertTrue(ws._valid_close_code(ws.CLOSE_SERVICE_RESTART))

        class Conn:
            def __init__(self):
                self.closed = None
                self.done = threading.Event()
            def close(self, code, reason):
                self.closed = (code, reason)
                self.done.set()
            def abort(self):
                raise AssertionError("graceful synthetic close should not abort")

        hub = ws.Hub("synthetic-token")
        conn = Conn()
        hub._subs[conn] = set()
        hub.close_all(code=ws.CLOSE_SERVICE_RESTART, reason="service restart")
        self.assertEqual(conn.closed, (1012, "service restart"))


class TinyClient:
    """A synthetic WebSocket client for tests: raw socket, masked frames."""

    def __init__(self, port: int, origin: str | None = None, host: str | None = None, token: str | None = None):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        self.expected_accept = ws.accept_key(key)
        lines = [f"GET /ws HTTP/1.1", f"Host: {host or f'127.0.0.1:{port}'}", "Upgrade: websocket",
                 "Connection: Upgrade", f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
        origin = f"http://127.0.0.1:{port}" if origin is None else origin
        if origin:
            lines.append(f"Origin: {origin}")
        self.sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        self.buf = b""
        while b"\r\n\r\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            self.buf += chunk
        head, _, self.buf = self.buf.partition(b"\r\n\r\n")
        status_line, *header_lines = head.decode().split("\r\n")
        self.status = int(status_line.split()[1])
        self.headers = {k.strip().lower(): v.strip() for k, v in (h.split(":", 1) for h in header_lines if ":" in h)}
        if token is not None and self.status == 101:
            self.send_json({"type": "hello", "token": token})

    def _recv_exact(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError
            self.buf += chunk
        data, self.buf = self.buf[:n], self.buf[n:]
        return data

    def send(self, opcode: int, payload: bytes = b"") -> None:
        self.sock.sendall(ws.encode_frame(opcode, payload, mask=os.urandom(4)))

    def send_json(self, obj) -> None:
        self.send(ws.OP_TEXT, json.dumps(obj).encode())

    def recv(self) -> tuple[int, bytes]:
        b0, b1 = self._recv_exact(2)
        assert not b1 & 0x80, "server frames must not be masked"
        n = b1 & 0x7F
        if n == 126:
            n = struct.unpack("!H", self._recv_exact(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", self._recv_exact(8))[0]
        return b0 & 0x0F, self._recv_exact(n)

    def recv_json(self) -> dict:
        op, payload = self.recv()
        assert op == ws.OP_TEXT, (op, payload)
        return json.loads(payload)

    def at_eof(self) -> bool:
        try:
            return self.sock.recv(1) == b""
        except OSError:
            return True

    def close(self) -> None:
        self.sock.close()


class LiveDashboard(TmpTestCase):
    def setUp(self):
        super().setUp()
        init_repo(self.tmp)
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        self.port = probe.getsockname()[1]
        probe.close()
        self.dash = Dashboard(FakeEnv(self.tmp, overrides={"dashboard": {"port": self.port}}).cfg)
        self.dash.serve_in_thread()
        self.clients: list[TinyClient] = []

    def tearDown(self):
        for c in self.clients:
            c.close()
        self.dash.shutdown()
        super().tearDown()

    def client(self, **kw) -> TinyClient:
        c = TinyClient(self.port, **kw)
        self.clients.append(c)
        return c

    def wait_for(self, cond, timeout: float = 5.0) -> None:
        end = time.monotonic() + timeout
        while not cond():
            if time.monotonic() > end:
                self.fail("condition not reached")
            time.sleep(0.02)

    def test_round_trip(self):
        c = self.client(token=self.dash.token)
        self.assertEqual(c.status, 101)
        self.assertEqual(c.headers["sec-websocket-accept"], c.expected_accept)
        self.assertEqual(c.recv_json()["type"], "welcome")
        c.send_json({"type": "ping"})
        self.assertEqual(c.recv_json(), {"type": "pong"})
        c.send(ws.OP_PING, b"abc")
        self.assertEqual(c.recv(), (ws.OP_PONG, b"abc"))
        c.send_json({"type": "hello", "token": self.dash.token})
        self.assertEqual(c.recv_json()["type"], "welcome")
        self.assertEqual(len(self.dash.hub.connections()), 1)
        c.send(ws.OP_CLOSE, ws.close_payload(1000, "done"))
        op, payload = c.recv()
        self.assertEqual((op, close_code(payload)), (ws.OP_CLOSE, 1000))
        self.assertTrue(c.at_eof())
        self.wait_for(lambda: not self.dash.hub.connections())
        # the classic pages keep working next to the socket
        html = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/state").read()
        self.assertIn(b"tasks", html)

    def test_foreign_origin_and_host_are_rejected_before_upgrade(self):
        self.assertEqual(self.client(origin="http://evil.example").status, 403)
        self.assertEqual(self.client(origin="").status, 403)
        self.assertEqual(self.client(host="evil.example").status, 403)
        self.assertEqual(self.client(origin=f"http://localhost:{self.port}").status, 101)

    def test_bad_token_closes_4401(self):
        c = self.client(token="not-the-token")
        self.assertEqual(c.status, 101)
        op, payload = c.recv()
        self.assertEqual((op, close_code(payload)), (ws.OP_CLOSE, ws.CLOSE_UNAUTHORIZED))
        self.assertFalse(self.dash.hub.connections())

    def test_oversize_message_closes_1009(self):
        c = self.client(token=self.dash.token)
        c.recv_json()
        # The server rejects on the declared length, before reading the body, so send only the header.
        c.sock.sendall(bytes([0x81, 0x80 | 127]) + struct.pack("!Q", ws.MAX_MESSAGE_BYTES + 1) + MASK)
        op, payload = c.recv()
        self.assertEqual((op, close_code(payload)), (ws.OP_CLOSE, ws.CLOSE_TOO_BIG))

    def test_server_shutdown_closes_sockets_cleanly(self):
        a = self.client(token=self.dash.token)
        b = self.client(token=self.dash.token)
        a.recv_json(), b.recv_json()
        self.wait_for(lambda: len(self.dash.hub.connections()) == 2)
        answered = threading.Thread(target=lambda: (a.recv(), a.send(ws.OP_CLOSE, ws.close_payload(1001))))
        answered.start()
        started = time.monotonic()
        self.dash.shutdown()                 # b never answers its close frame -> forced after the grace period
        answered.join(5)
        self.assertLess(time.monotonic() - started, 5)
        op, payload = b.recv()
        self.assertEqual((op, close_code(payload)), (ws.OP_CLOSE, ws.CLOSE_GOING_AWAY))
        self.assertTrue(b.at_eof())
        self.assertFalse(self.dash.hub.connections())


if __name__ == "__main__":
    unittest.main()
