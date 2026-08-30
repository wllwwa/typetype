"""52dazi 业务用例测试。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.backend.application.usecases.dazi_usecases import (
    DaziAuthRequiredError,
    UploadDaziScoreUseCase,
    build_dazi_score_payload,
)
from src.backend.models.dto.dazi_dto import DaziUploadOutcome


def _score(**overrides: float | int) -> dict:
    score: dict = {
        "speed": 120.0,
        "keyStroke": 8.0,
        "codeLength": 2.0,
        "time": 65.25,
        "key_stroke_count": 520,
        "wrong_char_count": 3,
        "backspace_count": 4,
        "correction_count": 2,
        "word_typing_rate": 88.8,
    }
    score.update(overrides)
    return score


def test_score_payload_contains_full_result_post_data() -> None:
    payload = build_dazi_score_payload(
        "标题", "一二三四", _score(), "搜狗输入法", competition_type=4
    )
    assert set(payload) == {
        "textTitle",
        "competitionType",
        "speed",
        "keystrokes",
        "maChang",
        "wordNum",
        "typingTime",
        "huiGai",
        "huiChe",
        "jianShu",
        "jianZhun",
        "accuracy",
        "repeatNum",
        "daCi",
        "wrongNum",
        "inputMethod",
        "backspace",
        "xuanChong",
        "keyMethod",
        "challengeFlag",
        "isFirstSubmit",
        "isGroupText",
    }
    assert payload["competitionType"] == 4
    assert payload["wordNum"] == len("一二三四")
    assert payload["typingTime"] == "01:05.250"
    assert payload["jianZhun"] == "98.46%"
    assert payload["accuracy"] == pytest.approx(98.461538, rel=1e-5)
    assert payload["inputMethod"] == "搜狗输入法"


def test_score_payload_handles_zero_time_and_zero_keystrokes() -> None:
    payload = build_dazi_score_payload(
        "标题", "正文", _score(time=0, key_stroke_count=0), "输入法"
    )
    assert payload["speed"] == 120.0
    assert payload["keystrokes"] == 8.0
    assert payload["maChang"] == 2.0
    assert payload["jianShu"] == 0.0
    assert payload["accuracy"] == 0.0
    assert payload["jianZhun"] == "0.00%"


def test_score_payload_truncates_input_method_to_20_characters() -> None:
    payload = build_dazi_score_payload("t", "c", {}, "123456789012345678901234")
    assert payload["inputMethod"] == "12345678901234567890"


def _usecase(logged_in: bool = True, upload_enabled: bool = True):
    gateway = MagicMock()
    gateway.is_logged_in.return_value = logged_in
    gateway.config = SimpleNamespace(
        input_method="输入法", upload_enabled=upload_enabled
    )
    gateway.upload_result.return_value = DaziUploadOutcome("成功", "1")
    return UploadDaziScoreUseCase(gateway), gateway


@pytest.mark.parametrize(
    ("logged_in", "upload_enabled", "title", "content", "error"),
    [
        (False, True, "标题", "正文", DaziAuthRequiredError),
        (True, False, "标题", "正文", ValueError),
        (True, True, "", "正文", ValueError),
        (True, True, "标题", "", ValueError),
    ],
)
def test_upload_rejects_invalid_state(
    logged_in: bool,
    upload_enabled: bool,
    title: str,
    content: str,
    error: type[Exception],
) -> None:
    usecase, gateway = _usecase(logged_in, upload_enabled)
    with pytest.raises(error):
        usecase.execute(title, content, _score())
    gateway.upload_result.assert_not_called()


def test_upload_usecase_passes_competition_type_to_gateway_payload() -> None:
    usecase, gateway = _usecase()
    result = usecase.execute("标题", "正文", _score(), competition_type=2)
    assert result.message == "成功"
    payload = gateway.upload_result.call_args.args[0]
    assert payload["competitionType"] == 2
