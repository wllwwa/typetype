"""52dazi 协议客户端。

52dazi 的网页接口把 JSON 使用 AES-128-CBC + ZeroPadding 加密后以纯文本
请求体发送，响应则是明文 JSON。客户端只负责协议和 HTTP，不负责成绩业务。
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
from Crypto.Cipher import AES

from ..models.dto.dazi_dto import (
    DaziCompetitionText,
    DaziCompetitionType,
    DaziLoginResult,
    DaziUploadOutcome,
)
from ..ports.dazi_provider import DEFAULT_DAZI_BASE_URL

AES_KEY = b"c9ec834c80f77237"
AES_IV = b"db4d6bfde3057dca"
_PROTOCOL_VERSION = "v2.1.6"
_SUBVERSIONS = 17108


class DaziError(Exception):
    """52dazi 请求或响应错误。"""


class DaziTransportError(DaziError):
    """网络连接、超时或 HTTP 错误。"""


class DaziParseError(DaziError):
    """响应格式错误。"""


class DaziServerError(DaziError):
    """服务器业务错误。"""


def zero_pad(data: bytes, block_size: int = 16) -> bytes:
    """按 52dazi 约定补零，整块数据也额外补一块。"""
    padding = block_size - len(data) % block_size
    return data + b"\x00" * padding


def encrypt_payload(value: Any) -> str:
    """将字符串或 JSON 值编码为 52dazi 加密请求体。"""
    if isinstance(value, str):
        plaintext = value
    else:
        plaintext = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    encrypted = cipher.encrypt(zero_pad(plaintext.encode("utf-8")))
    return base64.b64encode(encrypted).decode("ascii")


def decrypt_payload(encoded: str) -> str:
    """解密请求体，主要供协议测试和离线调试使用。"""
    try:
        encrypted = base64.b64decode(encoded, validate=True)
        if not encrypted or len(encrypted) % 16:
            raise ValueError("密文长度不是 AES 块大小的倍数")
        cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
        return cipher.decrypt(encrypted).rstrip(b"\x00").decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise DaziParseError(f"加密请求体解析失败: {exc}") from exc


def _base_fields(token: str | None = None) -> dict[str, Any]:
    import time

    fields: dict[str, Any] = {
        "from": "web",
        "timestamp": int(time.time()),
        "version": _PROTOCOL_VERSION,
        "subversions": _SUBVERSIONS,
    }
    if token is not None:
        fields["token"] = token
    return fields


def build_login_payload(username: str, password: str) -> str:
    fields = _base_fields()
    fields.update(username=username, password=password)
    return encrypt_payload(fields)


def build_content_payload(
    token: str, competition_type: DaziCompetitionType | int | str
) -> str:
    fields = _base_fields(token)
    fields.update(
        competitionType=int(DaziCompetitionType.from_code(competition_type)),
        snumflag="1",
    )
    return encrypt_payload(fields)


def build_upload_payload(token: str, payload: dict) -> str:
    fields = _base_fields(token)
    fields.update(payload)
    return encrypt_payload(fields)


def _parse_response(body: str) -> Any:
    try:
        raw = json.loads(body)
    except json.JSONDecodeError as exc:
        raise DaziParseError("服务器响应不是有效 JSON") from exc
    if not isinstance(raw, dict) or "error" not in raw or "msg" not in raw:
        raise DaziParseError("服务器响应缺少 error/msg 字段")
    if raw["error"] != 0:
        msg = raw["msg"] if isinstance(raw["msg"], str) else "未知错误"
        raise DaziServerError(msg)
    return raw["msg"]


def parse_login_response(body: str, cookie: str = "") -> DaziLoginResult:
    msg = _parse_response(body)
    if not isinstance(msg, dict) or not isinstance(msg.get("token"), str):
        raise DaziParseError("登录响应缺少 token")
    display_name = msg.get("name", "")
    return DaziLoginResult(
        token=msg["token"],
        cookie=cookie,
        display_name=display_name if isinstance(display_name, str) else "",
    )


def parse_content_response(
    body: str, competition_type: DaziCompetitionType
) -> DaziCompetitionText:
    msg = _parse_response(body)
    if not isinstance(msg, dict):
        raise DaziParseError("赛文响应不是对象")
    content = msg.get("a_content", msg.get("0", ""))
    title = msg.get("a_name", msg.get("7", ""))
    author = msg.get("a_author", msg.get("1", ""))
    if not isinstance(content, str):
        raise DaziParseError("赛文内容类型错误")
    content = content.replace("\n", "").replace("\r", "")
    title = title if isinstance(title, str) else ""
    author = author if isinstance(author, str) else ""
    if not title:
        title = competition_type.label
    raw_word_num = msg.get("6")
    try:
        word_num = int(raw_word_num)
    except (TypeError, ValueError):
        word_num = len(content)
    return DaziCompetitionText(content, title, author, word_num, competition_type)


def parse_upload_response(body: str) -> DaziUploadOutcome:
    msg = _parse_response(body)
    if isinstance(msg, str):
        return DaziUploadOutcome(message=msg)
    if not isinstance(msg, dict):
        raise DaziParseError("上传响应格式错误")
    ranking = msg.get("ranking", "")
    if ranking is None:
        ranking = ""
    if not isinstance(ranking, str):
        ranking = str(ranking)
    tips = msg.get("rankTips", "")
    return DaziUploadOutcome(
        message=tips if isinstance(tips, str) else "",
        ranking=ranking,
    )


class DaziClient:
    """使用独立 httpx 客户端的 52dazi 协议实现。"""

    def __init__(self, base_url: str = DEFAULT_DAZI_BASE_URL, timeout: float = 20.0):
        if not isinstance(base_url, str) or not base_url.startswith(
            ("http://", "https://")
        ):
            raise ValueError("52dazi 网关地址必须使用 http 或 https")
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 3.0)),
            trust_env=False,
        )

    def _post(self, path: str, body: str, cookie: str = "") -> tuple[str, str]:
        try:
            headers = {"Content-Type": "text/plain; charset=UTF-8"}
            if cookie:
                headers["Cookie"] = cookie
            response = self._client.post(
                f"{self.base_url}/{path}", content=body, headers=headers
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise DaziTransportError("52dazi 请求超时，请检查网络后重试") from exc
        except httpx.HTTPError as exc:
            raise DaziTransportError(f"52dazi 网络请求失败: {exc}") from exc
        new_cookie = ""
        for value in response.headers.get_list("set-cookie"):
            candidate = value.split(";", 1)[0].strip()
            if candidate.startswith("PHPSESSID="):
                new_cookie = candidate
                break
        return response.text, new_cookie

    def login(self, username: str, password: str) -> DaziLoginResult:
        body, cookie = self._post(
            "Api/User/login", build_login_payload(username, password)
        )
        return parse_login_response(body, cookie)

    def get_content(
        self, token: str, cookie: str, competition_type: DaziCompetitionType
    ) -> tuple[DaziCompetitionText, str]:
        body, new_cookie = self._post(
            "Api/Text/getContent",
            build_content_payload(token, competition_type),
            cookie,
        )
        return parse_content_response(body, competition_type), new_cookie

    def upload_result(
        self, token: str, cookie: str, payload: dict
    ) -> tuple[DaziUploadOutcome, str]:
        body, new_cookie = self._post(
            "Api/Rank/uploadResult", build_upload_payload(token, payload), cookie
        )
        return parse_upload_response(body), new_cookie

    def close(self) -> None:
        self._client.close()

    def update_base_url(self, base_url: str) -> None:
        if not isinstance(base_url, str) or not base_url.startswith(
            ("http://", "https://")
        ):
            raise ValueError("52dazi 网关地址必须使用 http 或 https")
        self.base_url = base_url.rstrip("/")
