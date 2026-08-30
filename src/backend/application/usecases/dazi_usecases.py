"""52dazi 载文与成绩上传用例。"""

from __future__ import annotations

from ..gateways.dazi_gateway import DaziGateway
from ...models.dto.dazi_dto import (
    DaziCompetitionText,
    DaziCompetitionType,
    DaziUploadOutcome,
)


class DaziAuthRequiredError(Exception):
    """尚未登录 52dazi。"""


def format_dazi_time(seconds: float) -> str:
    minutes = int(max(seconds, 0.0) // 60)
    remaining = max(seconds, 0.0) - minutes * 60
    return f"{minutes:02d}:{remaining:06.3f}"


def build_dazi_score_payload(
    title: str,
    content: str,
    score: dict,
    input_method: str,
    competition_type: int = 0,
) -> dict:
    """将 typetype 完成成绩映射为 52dazi resultPostData。"""
    key_strokes = float(score.get("key_stroke_count", 0.0) or 0.0)
    code_length = float(score.get("codeLength", 0.0) or 0.0)
    backspace = int(score.get("backspace_count", 0) or 0)
    corrections = int(score.get("correction_count", 0) or 0)
    wrong_keys = backspace + corrections * code_length
    key_accuracy = (
        max(0.0, (key_strokes - wrong_keys) / key_strokes) * 100
        if key_strokes > 0
        else 0.0
    )
    word_num = len(content)
    word_rate = float(score.get("word_typing_rate", 0.0) or 0.0)
    return {
        "textTitle": title,
        "competitionType": int(DaziCompetitionType.from_code(competition_type)),
        "speed": float(score.get("speed", 0.0) or 0.0),
        "keystrokes": float(score.get("keyStroke", 0.0) or 0.0),
        "maChang": code_length,
        "wordNum": word_num,
        "typingTime": format_dazi_time(float(score.get("time", 0.0) or 0.0)),
        "huiGai": corrections,
        "huiChe": 0,
        "jianShu": key_strokes,
        "jianZhun": f"{key_accuracy:.2f}%",
        "accuracy": key_accuracy,
        "repeatNum": 0,
        "daCi": f"{max(0.0, min(100.0, word_rate)):.2f}%",
        "wrongNum": int(score.get("wrong_char_count", 0) or 0),
        "inputMethod": input_method[:20],
        "backspace": backspace,
        "xuanChong": 0,
        "keyMethod": "0%",
        "challengeFlag": 0,
        "isFirstSubmit": 1,
        "isGroupText": 0,
    }


class LoadDaziTextUseCase:
    """载入指定 52dazi 比赛类型赛文。"""

    def __init__(self, gateway: DaziGateway):
        self._gateway = gateway

    def execute(self, competition_type: int) -> DaziCompetitionText:
        if not self._gateway.is_logged_in():
            raise DaziAuthRequiredError("请先在设置页登录 52dazi")
        return self._gateway.get_content(
            DaziCompetitionType.from_code(competition_type)
        )


class UploadDaziScoreUseCase:
    """显式上传已完成的 52dazi 赛文成绩。"""

    def __init__(self, gateway: DaziGateway):
        self._gateway = gateway

    def execute(
        self, title: str, content: str, score: dict, competition_type: int = 0
    ) -> DaziUploadOutcome:
        if not self._gateway.is_logged_in():
            raise DaziAuthRequiredError("请先在设置页登录 52dazi")
        if not self._gateway.config.upload_enabled:
            raise ValueError("52dazi 成绩上传已在设置中关闭")
        if not title or not content:
            raise ValueError("当前没有可上传的 52dazi 赛文成绩")
        payload = build_dazi_score_payload(
            title=title,
            content=content,
            score=score,
            input_method=self._gateway.config.input_method,
            competition_type=competition_type,
        )
        return self._gateway.upload_result(payload)
