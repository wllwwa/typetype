"""Wayland 浏览器桥接服务的纯逻辑测试。"""

import asyncio
import base64
import hashlib
import json

from scripts.wayland_typing_bridge import (
    LocalWebSocketServer,
    PhysicalKeyCounter,
    keyboard_capabilities,
    origin_is_allowed,
    parse_handshake,
    read_websocket_frame,
    websocket_frame,
)
from src.backend.ports.key_codes import KeyCodes


def test_counter_filters_repeat_navigation_and_modifiers() -> None:
    counter = PhysicalKeyCounter()

    assert counter.handle(1, 30, 1) == "stroke"
    assert counter.handle(1, 30, 2) is None
    assert counter.handle(1, KeyCodes.EVDEV_UP, 1) is None
    assert counter.handle(1, KeyCodes.EVDEV_LEFT_SHIFT, 1) is None
    assert counter.handle(1, 30, 1) == "stroke"
    assert counter.handle(1, KeyCodes.EVDEV_LEFT_SHIFT, 0) is None
    assert counter.handle(1, KeyCodes.EVDEV_BACKSPACE, 1) == "backspace"


def test_counter_drops_ctrl_shortcuts_but_keeps_backspace() -> None:
    counter = PhysicalKeyCounter()

    assert counter.handle(1, KeyCodes.EVDEV_LEFT_CTRL, 1) is None
    assert counter.handle(1, 30, 1) is None
    assert counter.handle(1, KeyCodes.EVDEV_BACKSPACE, 1) == "backspace"
    assert counter.handle(1, KeyCodes.EVDEV_LEFT_CTRL, 0) is None
    assert counter.handle(1, 30, 1) == "stroke"


def test_counter_remove_device_clears_modifier_state() -> None:
    counter = PhysicalKeyCounter()
    counter.handle(7, KeyCodes.EVDEV_LEFT_META, 1)
    counter.remove_device(7)

    assert counter.handle(7, 30, 1) == "stroke"


def test_keyboard_capabilities_matches_global_listener_rules() -> None:
    keyboard = {1: [30, 48]}
    touch_keyboard = {1: [30, 48], 3: [0, 1]}
    mouse = {1: [272], 2: [0, 1]}

    assert keyboard_capabilities(keyboard)
    assert not keyboard_capabilities(touch_keyboard)
    assert keyboard_capabilities(touch_keyboard, permissive=True)
    assert not keyboard_capabilities(mouse, permissive=True)


def test_websocket_frame_has_server_unmasked_payload() -> None:
    payload = b'{"type":"key"}'
    frame = websocket_frame(payload)

    assert frame[0] == 0x81
    assert frame[1] == len(payload)
    assert frame[2:] == payload


def test_read_websocket_frame_unmasks_client_payload() -> None:
    async def read_frame() -> tuple[int, bytes]:
        payload = b"ping"
        mask = b"abcd"
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        reader = asyncio.StreamReader()
        reader.feed_data(bytes((0x81, 0x80 | len(payload))) + mask + masked)
        reader.feed_eof()
        return await read_websocket_frame(reader)

    assert asyncio.run(read_frame()) == (0x1, b"ping")


def test_parse_handshake_and_origin_check() -> None:
    key = base64.b64encode(hashlib.sha1(b"test").digest()).decode("ascii")
    request = (
        "GET /?token=secret HTTP/1.1\r\n"
        "Host: 127.0.0.1:8765\r\n"
        "Upgrade: websocket\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Origin: https://typing.example.com\r\n\r\n"
    ).encode("ascii")
    target, headers = parse_handshake(request)

    assert target == "/?token=secret"
    assert headers["origin"] == "https://typing.example.com"
    assert origin_is_allowed(headers["origin"], ["https://typing.example.com"])
    assert not origin_is_allowed(headers["origin"], ["https://other.example.com"])
    assert origin_is_allowed(headers["origin"], ["*"])


def test_local_server_accepts_authenticated_websocket_upgrade() -> None:
    async def handshake() -> bytes:
        server = LocalWebSocketServer("secret", ["https://typing.example.com"])
        tcp_server = await asyncio.start_server(server.handle_client, "127.0.0.1", 0)
        port = tcp_server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        request = (
            "GET /?token=secret HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            "Origin: https://typing.example.com\r\n\r\n"
        ).encode("ascii")
        writer.write(request)
        await writer.drain()
        response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 1)
        writer.close()
        await writer.wait_closed()
        tcp_server.close()
        await tcp_server.wait_closed()
        return response

    response = asyncio.run(handshake())
    assert response.startswith(b"HTTP/1.1 101 Switching Protocols")


def test_long_poll_probe_skips_old_events_and_returns_new_event() -> None:
    async def request_events(
        port: int,
        since: int,
    ) -> dict[str, object]:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        request = (
            f"GET /events?token=secret&since={since} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            "X-Typetype-Origin: https://www.52dazi.cn\r\n\r\n"
        ).encode("ascii")
        writer.write(request)
        await writer.drain()
        response = await asyncio.wait_for(reader.read(), 1)
        writer.close()
        await writer.wait_closed()
        _, body = response.split(b"\r\n\r\n", 1)
        return json.loads(body)

    async def long_poll() -> tuple[dict[str, object], dict[str, object]]:
        bridge = LocalWebSocketServer("secret", ["https://www.52dazi.cn"])
        tcp_server = await asyncio.start_server(bridge.handle_client, "127.0.0.1", 0)
        port = tcp_server.sockets[0].getsockname()[1]
        await bridge.broadcast("stroke")

        probe = await request_events(port, -1)
        poll_task = asyncio.create_task(request_events(port, int(probe["cursor"])))
        await asyncio.sleep(0)
        await bridge.broadcast("backspace")
        events = await poll_task

        tcp_server.close()
        await tcp_server.wait_closed()
        return probe, events

    probe, result = asyncio.run(long_poll())
    assert probe == {"version": 1, "cursor": 1, "events": []}
    assert result["cursor"] == 2
    assert result["events"] == [
        {
            "type": "key",
            "kind": "backspace",
            "timestamp": result["events"][0]["timestamp"],
            "sequence": 2,
        }
    ]
