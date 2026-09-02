#!/usr/bin/env python3
"""为浏览器提供 Wayland 下的物理击键事件。

这个脚本是独立于 Qt 主程序的轻量服务，只依赖 Linux evdev 和 Python 标准库。
它固定监听 127.0.0.1，通过 WebSocket 或 HTTP 长轮询推送两种聚合事件：
stroke、backspace。
服务不传输具体键码，也不保存按键记录。

用法：
    uv run python scripts/wayland_typing_bridge.py
    uv run python scripts/wayland_typing_bridge.py --origin https://example.com
    uv run python scripts/wayland_typing_bridge.py --device /dev/input/by-id/...
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from collections import deque
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backend.ports.key_codes import KeyCodes  # noqa: E402

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PROTOCOL_VERSION = 1
EV_KEY = 1
MAX_HTTP_HEADER_BYTES = 16 * 1024
MAX_FRAME_BYTES = 4096
EVENT_BUFFER_SIZE = 128
POLL_TIMEOUT_SECONDS = 25


class PhysicalKeyCounter:
    """将 evdev 原始事件折叠为网页需要的聚合事件。"""

    def __init__(self) -> None:
        self._pressed_shortcut_modifiers: dict[int, set[int]] = {}

    def handle(self, device_id: int, key_code: int, value: int) -> str | None:
        if KeyCodes.is_shortcut_modifier(key_code):
            pressed = self._pressed_shortcut_modifiers.setdefault(device_id, set())
            if value in (1, 2):
                pressed.add(key_code)
            elif value == 0:
                pressed.discard(key_code)
                if not pressed:
                    self._pressed_shortcut_modifiers.pop(device_id, None)

        # value=2 是 evdev 自动连发，不能重复增加码长。
        if value != 1:
            return None
        if KeyCodes.is_modifier(key_code) or KeyCodes.is_navigation(key_code):
            return None
        if self._pressed_shortcut_modifiers.get(
            device_id
        ) and not KeyCodes.is_backspace(key_code):
            return None
        return "backspace" if KeyCodes.is_backspace(key_code) else "stroke"

    def remove_device(self, device_id: int) -> None:
        self._pressed_shortcut_modifiers.pop(device_id, None)


def keyboard_capabilities(caps: dict[int, list[int]], permissive: bool = False) -> bool:
    """按现有 GlobalKeyListener 的规则判断输入设备是否像键盘。"""

    if EV_KEY not in caps or (not permissive and 3 in caps):  # 3 = EV_ABS
        return False
    if 2 in caps:  # 2 = EV_REL，带鼠标相对位移的设备排除
        return False
    return any(code < 256 for code in caps[EV_KEY])


class EvdevKeyboardSource:
    """把 evdev fd 接入 asyncio 事件循环。"""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        on_event: Callable[[str], Awaitable[None] | None],
        device_paths: list[str] | None = None,
    ) -> None:
        self._loop = loop
        self._on_event = on_event
        self._device_paths = device_paths or []
        self._devices: list[object] = []
        self._counter = PhysicalKeyCounter()

    @property
    def device_count(self) -> int:
        return len(self._devices)

    def start(self) -> None:
        if sys.platform != "linux":
            raise RuntimeError("Wayland 浏览器桥接服务只支持 Linux。")

        from evdev import InputDevice, list_devices

        paths = self._device_paths or list_devices()
        candidates: list[object] = []
        for path in paths:
            try:
                device = InputDevice(path)
                if keyboard_capabilities(device.capabilities()):
                    candidates.append(device)
                else:
                    device.close()
            except OSError:
                continue

        # 严格扫描没有结果时，允许带 EV_ABS 的键盘（如带触摸条的蓝牙键盘）。
        if not candidates and not self._device_paths:
            for path in list_devices():
                try:
                    device = InputDevice(path)
                    if keyboard_capabilities(device.capabilities(), permissive=True):
                        candidates.append(device)
                    else:
                        device.close()
                except OSError:
                    continue

        if not candidates:
            raise RuntimeError(
                "未找到可访问的键盘输入设备。请确认用户已加入 input 组，"
                "或使用 --device 指定 /dev/input/by-id/ 下的键盘设备。"
            )

        self._devices = candidates
        for device in self._devices:
            self._loop.add_reader(device.fd, self._read_device, device)

    def _read_device(self, device: object) -> None:
        try:
            for event in device.read():
                if event.type != EV_KEY:
                    continue
                event_kind = self._counter.handle(device.fd, event.code, event.value)
                if event_kind is None:
                    continue
                result = self._on_event(event_kind)
                if result is not None:
                    asyncio.create_task(result)
        except (BlockingIOError, OSError):
            self._remove_device(device)

    def _remove_device(self, device: object) -> None:
        if device not in self._devices:
            return
        self._loop.remove_reader(device.fd)
        self._counter.remove_device(device.fd)
        self._devices.remove(device)
        device.close()

    def stop(self) -> None:
        for device in self._devices.copy():
            self._remove_device(device)


def websocket_frame(payload: bytes, opcode: int = 0x1) -> bytes:
    """生成服务端到客户端的无掩码 WebSocket 帧。"""

    length = len(payload)
    if length < 126:
        return bytes((0x80 | opcode, length)) + payload
    if length <= 0xFFFF:
        return bytes((0x80 | opcode, 126)) + length.to_bytes(2, "big") + payload
    return bytes((0x80 | opcode, 127)) + length.to_bytes(8, "big") + payload


async def read_websocket_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    header = await reader.readexactly(2)
    first, second = header
    opcode = first & 0x0F
    length = second & 0x7F
    masked = bool(second & 0x80)
    if length == 126:
        length = int.from_bytes(await reader.readexactly(2), "big")
    elif length == 127:
        length = int.from_bytes(await reader.readexactly(8), "big")
    if not masked or length > MAX_FRAME_BYTES:
        raise ValueError("invalid WebSocket frame")
    mask = await reader.readexactly(4)
    data = bytearray(await reader.readexactly(length))
    for index in range(length):
        data[index] ^= mask[index % 4]
    return opcode, bytes(data)


def parse_handshake(request: bytes) -> tuple[str, dict[str, str]]:
    if len(request) > MAX_HTTP_HEADER_BYTES:
        raise ValueError("HTTP header too large")
    lines = request.decode("ascii").split("\r\n")
    method, target, _ = lines[0].split(" ", 2)
    if method != "GET":
        raise ValueError("only GET is supported")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            break
        name, value = line.split(":", 1)
        headers[name.lower().strip()] = value.strip()
    return target, headers


def origin_is_allowed(origin: str, allowed_origins: list[str]) -> bool:
    return bool(origin) and ("*" in allowed_origins or origin in allowed_origins)


class LocalWebSocketServer:
    """通过本机 WebSocket 或 HTTP 长轮询广播聚合按键事件。"""

    def __init__(self, token: str, allowed_origins: list[str] | None = None) -> None:
        self._token = token
        self._allowed_origins = allowed_origins or ["*"]
        self._clients: set[asyncio.StreamWriter] = set()
        self._events: deque[dict[str, object]] = deque(maxlen=EVENT_BUFFER_SIZE)
        self._event_condition = asyncio.Condition()
        self._sequence = 0
        self._poll_waiters = 0

    def publish(self, event_kind: str) -> Awaitable[None] | None:
        if not self._clients and self._poll_waiters == 0:
            return None
        return self.broadcast(event_kind)

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request = await reader.readuntil(b"\r\n\r\n")
            target, headers = parse_handshake(request)
            parsed_target = urlsplit(target)
            query = parse_qs(parsed_target.query)
            request_token = query.get("token", [""])[0]
            if parsed_target.path == "/events":
                origin = headers.get("origin") or headers.get("x-typetype-origin", "")
                if not hmac.compare_digest(
                    request_token, self._token
                ) or not origin_is_allowed(origin, self._allowed_origins):
                    await self._reject(writer, "403 Forbidden")
                    return
                await self._handle_long_poll(writer, query)
                return

            if (
                headers.get("upgrade", "").lower() != "websocket"
                or headers.get("sec-websocket-version") != "13"
                or not headers.get("sec-websocket-key")
                or not hmac.compare_digest(request_token, self._token)
                or not origin_is_allowed(
                    headers.get("origin", ""), self._allowed_origins
                )
            ):
                await self._reject(writer, "403 Forbidden")
                return

            accept = base64.b64encode(
                hashlib.sha1(
                    (
                        headers["sec-websocket-key"]
                        + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                    ).encode("ascii")
                ).digest()
            ).decode("ascii")
            writer.write(
                (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                ).encode("ascii")
            )
            await writer.drain()
            self._clients.add(writer)
            await self._send_json(
                writer,
                {
                    "type": "hello",
                    "version": PROTOCOL_VERSION,
                    "server": "typetype-wayland-bridge",
                },
            )
            while True:
                opcode, payload = await read_websocket_frame(reader)
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    writer.write(websocket_frame(payload, opcode=0xA))
                    await writer.drain()
        except (
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
            ValueError,
            OSError,
        ):
            pass
        finally:
            self._clients.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def broadcast(self, event_kind: str) -> None:
        async with self._event_condition:
            self._sequence += 1
            event: dict[str, object] = {
                "type": "key",
                "kind": event_kind,
                "timestamp": time.time_ns() // 1_000_000,
                "sequence": self._sequence,
            }
            self._events.append(event)
            self._event_condition.notify_all()

        if not self._clients:
            return
        payload = json.dumps(event, separators=(",", ":"))
        frame = websocket_frame(payload.encode("utf-8"))
        clients = tuple(self._clients)
        for writer in clients:
            try:
                writer.write(frame)
                await writer.drain()
            except (ConnectionError, OSError):
                self._clients.discard(writer)
                writer.close()

    async def _handle_long_poll(
        self,
        writer: asyncio.StreamWriter,
        query: dict[str, list[str]],
    ) -> None:
        try:
            requested_sequence = int(query.get("since", ["0"])[0])
        except ValueError:
            await self._reject(writer, "400 Bad Request")
            return
        probe = requested_sequence < 0
        since = max(0, requested_sequence)

        self._poll_waiters += 1
        try:
            async with self._event_condition:
                events = [] if probe else self._events_since(since)
                if not events and not probe:
                    try:
                        await asyncio.wait_for(
                            self._event_condition.wait(), POLL_TIMEOUT_SECONDS
                        )
                    except TimeoutError:
                        pass
                    events = self._events_since(since)
                cursor = self._sequence
        finally:
            self._poll_waiters -= 1

        await self._send_http_json(
            writer,
            {
                "version": PROTOCOL_VERSION,
                "cursor": cursor,
                "events": events,
            },
        )

    def _events_since(self, sequence: int) -> list[dict[str, object]]:
        return [event for event in self._events if int(event["sequence"]) > sequence]

    @staticmethod
    async def _send_json(
        writer: asyncio.StreamWriter, payload: dict[str, object]
    ) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        writer.write(websocket_frame(data))
        await writer.drain()

    @staticmethod
    async def _send_http_json(
        writer: asyncio.StreamWriter, payload: dict[str, object]
    ) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        writer.write(
            (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json; charset=utf-8\r\n"
                "Cache-Control: no-store\r\n"
                "Connection: close\r\n"
                f"Content-Length: {len(data)}\r\n\r\n"
            ).encode("ascii")
            + data
        )
        await writer.drain()

    @staticmethod
    async def _reject(writer: asyncio.StreamWriter, status: str) -> None:
        writer.write(f"HTTP/1.1 {status}\r\nContent-Length: 0\r\n\r\n".encode("ascii"))
        await writer.drain()


def token_path() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "typetype" / "wayland-typing-bridge-token"


def load_or_create_token(path: Path | None = None) -> str:
    path = path or token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    if path.exists():
        try:
            path.chmod(0o600)
        except OSError:
            pass
        token = path.read_text(encoding="ascii").strip()
        if token:
            return token
    token = secrets.token_urlsafe(24)
    path.write_text(token + "\n", encoding="ascii")
    path.chmod(0o600)
    return token


async def run_service(args: argparse.Namespace) -> None:
    token = args.token or load_or_create_token()
    bridge = LocalWebSocketServer(token, args.origin)
    loop = asyncio.get_running_loop()
    server = await asyncio.start_server(bridge.handle_client, HOST, args.port)
    source = EvdevKeyboardSource(loop, bridge.publish, args.device)
    try:
        source.start()
        print(f"Wayland 浏览器桥接服务已启动: ws://{HOST}:{args.port}")
        print(f"token: {token}")
        print(f"设备数: {source.device_count}；按 Ctrl+C 停止")
        await asyncio.Future()
    finally:
        source.stop()
        server.close()
        await server.wait_closed()


def main() -> None:
    parser = argparse.ArgumentParser(description="Wayland 浏览器物理击键桥接服务")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="本机端口")
    parser.add_argument(
        "--origin",
        action="append",
        default=[],
        help="允许的网页 Origin，可重复；省略时依靠 token 校验",
    )
    parser.add_argument("--token", help="连接 token，省略时使用用户配置目录中的 token")
    parser.add_argument(
        "--device", action="append", help="指定 evdev 键盘路径，可重复；默认自动发现"
    )
    args = parser.parse_args()
    try:
        asyncio.run(run_service(args))
    except KeyboardInterrupt:
        print("\nWayland 浏览器桥接服务已停止")


if __name__ == "__main__":
    main()
