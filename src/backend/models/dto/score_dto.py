"""成绩传输对象（DTO）。

用于隔离网络/界面传输结构，避免与领域模型耦合。
"""

import hashlib
import hmac
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models.entity.session_stat import SessionStat


_WEBSITE_HASH_SECRET = "1072970551"
_WEBSITE_VERSION = "极速打字通v2.1.6"


@dataclass
class ScoreSummaryItemDTO:
    """成绩摘要项 DTO。"""

    label: str
    value: float | int
    unit: str
    value_format: str


@dataclass
class ScoreSummaryDTO:
    """成绩摘要展示 DTO。"""

    items: list[ScoreSummaryItemDTO]
    peak_speed: float = 0.0
    peak_key_stroke: float = 0.0
    peak_code_length: float = 0.0
    slow_chars: list[tuple[str, float]] | None = None
    official_speed: float | None = None

    @classmethod
    def from_score_data(cls, score_data: "SessionStat") -> "ScoreSummaryDTO":
        """从领域对象构建成绩摘要 DTO。"""
        official_speed = score_data.speed
        if score_data.time > 0:
            official_speed = (
                max(score_data.char_count - 5 * score_data.wrong_char_count, 0)
                * 60
                / score_data.time
            )

        return cls(
            items=[
                ScoreSummaryItemDTO(
                    label="速度",
                    value=score_data.speed,
                    unit="字/分",
                    value_format=".2f",
                ),
                ScoreSummaryItemDTO(
                    label="击键",
                    value=score_data.keyStroke,
                    unit="击/秒",
                    value_format=".2f",
                ),
                ScoreSummaryItemDTO(
                    label="码长",
                    value=score_data.codeLength,
                    unit="击/字",
                    value_format=".2f",
                ),
                ScoreSummaryItemDTO(
                    label="错字",
                    value=score_data.wrong_char_count,
                    unit="字",
                    value_format="d",
                ),
                ScoreSummaryItemDTO(
                    label="回改",
                    value=score_data.correction_count,
                    unit="次",
                    value_format="d",
                ),
                ScoreSummaryItemDTO(
                    label="退格",
                    value=score_data.backspace_count,
                    unit="次",
                    value_format="d",
                ),
                ScoreSummaryItemDTO(
                    label="键准",
                    value=score_data.keyAccuracy,
                    unit="%",
                    value_format=".2f",
                ),
                ScoreSummaryItemDTO(
                    label="字数",
                    value=score_data.char_count,
                    unit="",
                    value_format="d",
                ),
                ScoreSummaryItemDTO(
                    label="用时",
                    value=score_data.time,
                    unit="秒",
                    value_format=".3f",
                ),
                ScoreSummaryItemDTO(
                    label="键数",
                    value=score_data.key_stroke_count,
                    unit="",
                    value_format=".2f",
                ),
                ScoreSummaryItemDTO(
                    label="打词率",
                    value=score_data.word_typing_rate,
                    unit="%",
                    value_format=".1f",
                ),
                ScoreSummaryItemDTO(
                    label="标顶",
                    value=score_data.biao_ding_count,
                    unit="次",
                    value_format="d",
                ),
            ],
            peak_speed=score_data.peak_speed,
            peak_key_stroke=score_data.peak_key_stroke,
            peak_code_length=score_data.peak_code_length
            if score_data.peak_code_length != float("inf")
            else 0.0,
            slow_chars=score_data.slow_chars or None,
            official_speed=official_speed,
        )

    def to_clipboard_text(
        self, segment_label: str = "第1段", identity: str = "1"
    ) -> str:
        """渲染为 52dazi 官网可直接识别的单行成绩文本。

        官网使用 ``identity-speed-hitSpeed-codeLength`` 计算成绩哈希，
        这里保留相同的小数格式和 HMAC-SHA1 末八位规则。官网暂未采集的
        键法、选重、回车和重打指标使用 0 作为兼容占位值。
        """
        speed_value = (
            self.official_speed
            if self.official_speed is not None
            else self._value("速度")
        )
        speed = f"{speed_value:.2f}"
        hit_speed = self._value("击键")
        code_length = self._value("码长")
        time_seconds = self._value("用时")
        key_count = self._value("键数")
        content_length = self._value("字数")
        wrong_count = self._value("错字")
        key_accuracy = self._value("键准")
        correction_count = self._value("回改")
        backspace_count = self._value("退格")
        phrase_rate = self._value("打词率")

        hit_speed_text = f"{hit_speed:.2f}"
        code_length_text = f"{code_length:.2f}"
        digest_input = f"{identity}-{speed}-{hit_speed_text}-{code_length_text}"
        score_hash = hmac.new(
            _WEBSITE_HASH_SECRET.encode("ascii"),
            digest_input.encode("utf-8"),
            hashlib.sha1,
        ).hexdigest()[-8:]

        return " ".join(
            [
                segment_label,
                f"速度{speed}",
                f"击键{hit_speed_text}",
                f"码长{code_length_text}",
                f"字数{int(content_length)}",
                f"错字{int(wrong_count)}",
                f"用时{self._format_website_time(time_seconds)}",
                f"键准{key_accuracy:.2f}%",
                "键法0%",
                f"打词{phrase_rate:.2f}%",
                "选重0",
                f"回改{int(correction_count)}",
                f"键数{int(key_count)}",
                f"退格{int(backspace_count)}",
                "回车0",
                "重打0",
                f"哈希{score_hash}",
                _WEBSITE_VERSION,
            ]
        )

    def _value(self, label: str) -> float:
        for item in self.items:
            if item.label == label:
                return float(item.value)
        return 0.0

    @staticmethod
    def _format_website_time(seconds: float) -> str:
        seconds = max(seconds, 0.0)
        minutes = int(seconds // 60)
        remaining = seconds - minutes * 60
        return f"{minutes:02d}:{remaining:06.3f}"

    def to_plain_text(self) -> str:
        """渲染为纯文本格式。"""
        return self._render(value_prefix="", value_suffix="", line_suffix="\n")

    def to_html(self) -> str:
        """渲染为 HTML 格式。"""
        return self._render(value_prefix="<b>", value_suffix="</b>", line_suffix="<br>")

    def _render(self, value_prefix: str, value_suffix: str, line_suffix: str) -> str:
        """按给定标记渲染文本。"""
        lines: list[str] = []
        for item in self.items:
            value_str = f"{item.value:{item.value_format}}"
            unit_part = f" {item.unit}" if item.unit else ""
            lines.append(
                f"{item.label}: {value_prefix}{value_str}{value_suffix}{unit_part}{line_suffix}"
            )
        if self.peak_speed > 0:
            lines.append(
                f"峰值: {value_prefix}{self.peak_speed:.2f}/{self.peak_key_stroke:.2f}/{self.peak_code_length:.2f}{value_suffix}{line_suffix}"
            )
        if self.slow_chars:
            slow_str = ", ".join(f"{c}({t}s)" for c, t in self.slow_chars)
            lines.append(f"慢字: {slow_str}{line_suffix}")
        return "".join(lines)


@dataclass
class HistoryRecordDTO:
    """历史记录传输对象。"""

    speed: float
    key_stroke: float
    code_length: float
    wrong_num: int
    backspace_count: int
    correction_count: int
    char_num: int
    time: float
    date: str
    key_accuracy: float
    word_typing_rate: float = 0.0
    biao_ding_count: int = 0

    @classmethod
    def from_score_data(cls, score_data: "SessionStat") -> "HistoryRecordDTO":
        """从领域对象构建历史记录 DTO。"""
        return cls(
            speed=round(score_data.speed, 2),
            key_stroke=round(score_data.keyStroke, 2),
            code_length=round(score_data.codeLength, 2),
            wrong_num=score_data.wrong_char_count,
            backspace_count=score_data.backspace_count,
            correction_count=score_data.correction_count,
            char_num=score_data.char_count,
            time=round(score_data.time, 2),
            date=score_data.date,
            key_accuracy=round(score_data.keyAccuracy, 2),
            word_typing_rate=score_data.word_typing_rate,
            biao_ding_count=score_data.biao_ding_count,
        )

    def to_dict(self) -> dict[str, float | int | str]:
        """输出与 QML 历史记录兼容的数据结构。"""
        return {
            "speed": self.speed,
            "keyStroke": self.key_stroke,
            "codeLength": self.code_length,
            "wrongNum": self.wrong_num,
            "correctionCount": self.correction_count,
            "backspaceCount": self.backspace_count,
            "keyAccuracy": self.key_accuracy,
            "wordTypingRate": self.word_typing_rate,
            "biaoDingCount": self.biao_ding_count,
            "charNum": self.char_num,
            "time": self.time,
            "date": self.date,
        }
