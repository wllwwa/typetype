"""52dazi 协议客户端测试。"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from src.backend.application.gateways.dazi_gateway import DaziGateway
from src.backend.integration.dazi_client import (
    DaziClient,
    DaziParseError,
    DaziServerError,
    DaziTransportError,
    build_content_payload,
    build_login_payload,
    build_upload_payload,
    decrypt_payload,
    encrypt_payload,
    parse_content_response,
    parse_login_response,
    parse_upload_response,
)
from src.backend.models.dto.dazi_dto import (
    DaziCompetitionText,
    DaziCompetitionType,
    DaziUploadOutcome,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("hello", "aol12WGdEQJilT6t31FMAw=="),
        ("中文", "MAQAA9fnyD+FG7FIu9XlnQ=="),
        ("", "1hOp2mXJlkI5Mti018cSWQ=="),
        ("1234567890abcdef", "OcPkT9pHGEOTdLE4KyuB7OSVjdrSj/1BxC+DXVAbQNk="),
    ],
)
def test_encrypt_payload_known_vectors(value: str, expected: str) -> None:
    assert encrypt_payload(value) == expected
    assert decrypt_payload(expected) == value


def test_payloads_use_protocol_and_business_field_types() -> None:
    login = json.loads(decrypt_payload(build_login_payload("user", "pass")))
    assert login["from"] == "web"
    assert isinstance(login["timestamp"], int)
    assert login["version"] == "v2.1.6"
    assert login["subversions"] == 17108
    assert login["username"] == "user"
    assert login["password"] == "pass"

    content = json.loads(
        decrypt_payload(build_content_payload("token", DaziCompetitionType.JIANSHEN))
    )
    assert content["token"] == "token"
    assert content["competitionType"] == 4
    assert content["snumflag"] == "1"

    upload = json.loads(decrypt_payload(build_upload_payload("token", {"speed": 10})))
    assert upload["token"] == "token"
    assert upload["speed"] == 10


@pytest.mark.parametrize("code", [0, 2, 4, "bad", 99])
def test_invalid_competition_code_falls_back_to_jisu(code: int | str) -> None:
    expected = {
        0: 0,
        2: 2,
        4: 4,
        "bad": 0,
        99: 0,
    }[code]
    payload = json.loads(decrypt_payload(build_content_payload("t", code)))
    assert payload["competitionType"] == expected


def test_parse_content_supports_numeric_and_named_fields() -> None:
    body = json.dumps(
        {
            "error": 0,
            "msg": {"0": "数值正文\n", "1": "作者", "6": "12", "7": "标题"},
        }
    )
    result = parse_content_response(body, DaziCompetitionType.JINBIAO)
    assert (result.content, result.title, result.author, result.word_num) == (
        "数值正文",
        "标题",
        "作者",
        12,
    )

    named = json.dumps(
        {
            "error": 0,
            "msg": {"a_content": "正文", "a_name": "名称", "a_author": "作者"},
        }
    )
    result = parse_content_response(named, DaziCompetitionType.JISU)
    assert result.title == "名称"
    assert result.word_num == len("正文")


@pytest.mark.parametrize(
    "parser,body",
    [
        (parse_login_response, '{"error":0,"msg":"失败"}'),
        (parse_login_response, '{"error":0,"msg":{}}'),
        (parse_login_response, "not-json"),
        (parse_upload_response, '{"error":0,"msg":42}'),
    ],
)
def test_parse_rejects_invalid_success_responses(parser, body: str) -> None:
    with pytest.raises(DaziParseError):
        parser(body)


def test_parse_upload_supports_string_and_object_messages() -> None:
    assert parse_upload_response('{"error":0,"msg":"已上传"}').message == "已上传"
    result = parse_upload_response(
        '{"error":0,"msg":{"ranking":3,"rankTips":"排名更新"}}'
    )
    assert result.message == "排名更新"
    assert result.ranking == "3"


def test_server_error_supports_string_message_only() -> None:
    with pytest.raises(DaziServerError, match="拒绝"):
        parse_upload_response('{"error":1,"msg":"拒绝"}')
    with pytest.raises(DaziServerError, match="未知错误"):
        parse_upload_response('{"error":1,"msg":{"reason":"拒绝"}}')


def test_client_posts_plaintext_ciphertext_and_rotating_cookie() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["content-type"] == "text/plain; charset=UTF-8"
        assert request.headers["cookie"] == "PHPSESSID=old"
        assert b"{" not in request.content
        payload = json.loads(decrypt_payload(request.content.decode("ascii")))
        assert payload["token"] == "token"
        assert payload["competitionType"] == 2
        return httpx.Response(
            200,
            json={"error": 0, "msg": {"a_content": "正文", "a_name": "标题"}},
            headers={"set-cookie": "PHPSESSID=new; Path=/"},
        )

    client = DaziClient("http://dazi.test")
    client._client.close()
    client._client = httpx.Client(
        transport=httpx.MockTransport(handler), trust_env=False
    )
    result, cookie = client.get_content(
        "token", "PHPSESSID=old", DaziCompetitionType.JINBIAO
    )
    client.close()

    assert result.content == "正文"
    assert cookie == "PHPSESSID=new"
    assert requests[0].url.path == "/Api/Text/getContent"


@pytest.mark.parametrize(
    "error",
    [httpx.ReadTimeout("timeout"), httpx.ConnectError("offline")],
)
def test_client_wraps_transport_errors(error: httpx.HTTPError) -> None:
    client = DaziClient("http://dazi.test")
    client._client.close()
    client._client = httpx.Client(
        transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(error)),
        trust_env=False,
    )
    try:
        with pytest.raises(DaziTransportError):
            client.login("u", "p")
    finally:
        client.close()


def test_client_wraps_non_2xx() -> None:
    client = DaziClient("http://dazi.test")
    client._client.close()
    client._client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(503)),
        trust_env=False,
    )
    try:
        with pytest.raises(DaziTransportError):
            client.login("u", "p")
    finally:
        client.close()


def test_gateway_persists_rotated_cookie_after_content_and_upload() -> None:
    provider = MagicMock()
    provider.get_content.return_value = (
        DaziCompetitionText("正文", "标题", "", 2, DaziCompetitionType.JISU),
        "PHPSESSID=content",
    )
    provider.upload_result.return_value = (
        DaziUploadOutcome("成功"),
        "PHPSESSID=upload",
    )
    store = MagicMock()
    store.get_token.side_effect = lambda key: {
        "dazi_token": "token",
        "dazi_cookie": "old",
    }.get(key)
    runtime = SimpleNamespace(dazi=SimpleNamespace(username="user"))

    gateway = DaziGateway(runtime, provider, store)
    gateway.get_content(DaziCompetitionType.JISU)
    assert store.save_token.call_args_list[0].args == (
        "dazi_cookie",
        "PHPSESSID=content",
    )
    gateway.upload_result({"competitionType": 0})
    assert store.save_token.call_args_list[1].args == (
        "dazi_cookie",
        "PHPSESSID=upload",
    )
