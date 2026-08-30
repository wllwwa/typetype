"""成绩 DTO 测试。"""

from src.backend.models.dto.score_dto import HistoryRecordDTO, ScoreSummaryDTO
from src.backend.models.entity.session_stat import SessionStat


class TestHistoryRecordDTO:
    """测试历史记录 DTO 转换"""

    def test_from_score_data_and_to_dict(self):
        """应可从领域对象转换为 QML 兼容字典"""
        score = SessionStat(
            time=60.0,
            key_stroke_count=300,
            char_count=240,
            wrong_char_count=10,
            date="2024-01-01 00:00:00",
        )

        dto = HistoryRecordDTO.from_score_data(score)
        result = dto.to_dict()

        assert list(result.keys()) == [
            "speed",
            "keyStroke",
            "codeLength",
            "wrongNum",
            "correctionCount",
            "backspaceCount",
            "keyAccuracy",
            "wordTypingRate",
            "biaoDingCount",
            "charNum",
            "time",
            "date",
        ]
        assert result == {
            "speed": 240.0,
            "keyStroke": 5.0,
            "codeLength": 1.25,
            "wrongNum": 10,
            "correctionCount": 0,
            "backspaceCount": 0,
            "keyAccuracy": 100.0,
            "charNum": 240,
            "time": 60.0,
            "date": "2024-01-01 00:00:00",
            "wordTypingRate": 0.0,
            "biaoDingCount": 0,
        }


class TestScoreSummaryDTO:
    """测试成绩摘要 DTO"""

    def test_from_score_data(self):
        """应生成固定顺序的摘要项"""
        score = SessionStat(
            time=60.0,
            key_stroke_count=300,
            char_count=240,
            wrong_char_count=10,
            date="2024-01-01 00:00:00",
        )

        dto = ScoreSummaryDTO.from_score_data(score)

        assert len(dto.items) == 12
        assert dto.items[0].label == "速度"
        assert dto.items[0].unit == "字/分"
        assert dto.items[1].label == "击键"
        assert dto.items[1].unit == "击/秒"
        assert dto.items[2].label == "码长"
        assert dto.items[2].unit == "击/字"
        assert dto.items[3].label == "错字"
        assert dto.items[3].unit == "字"
        assert dto.items[4].label == "回改"
        assert dto.items[4].unit == "次"
        assert dto.items[5].label == "退格"
        assert dto.items[5].unit == "次"
        assert dto.items[6].label == "键准"
        assert dto.items[6].unit == "%"
        assert dto.items[7].label == "字数"
        assert dto.items[7].unit == ""
        assert dto.items[8].label == "用时"
        assert dto.items[8].unit == "秒"
        assert dto.items[9].label == "键数"
        assert dto.items[9].unit == ""
        assert dto.items[10].label == "打词率"
        assert dto.items[10].unit == "%"
        assert dto.items[10].value_format == ".1f"
        assert dto.items[11].label == "标顶"
        assert dto.items[11].unit == "次"
        assert dto.items[11].value_format == "d"

    def test_to_clipboard_text(self):
        """应输出 52dazi 官网风格单行纯文本"""
        score = SessionStat(
            time=60.0,
            key_stroke_count=300,
            char_count=240,
            wrong_char_count=10,
            date="2024-01-01 00:00:00",
        )

        text = ScoreSummaryDTO.from_score_data(score).to_clipboard_text()

        # 不含换行符
        assert "\n" not in text
        assert text == (
            "第1段 速度190.00 击键5.00 码长1.25 字数240 错字10 "
            "用时01:00.000 键准100.00% 键法0% 打词0.00% 选重0 回改0 "
            "键数300 退格0 回车0 重打0 哈希1c153b59 极速打字通v2.1.6"
        )

    def test_to_clipboard_text_uses_identity_for_website_hash(self):
        """哈希应与官网使用相同的身份和统计小数格式。"""
        score = SessionStat(
            time=243.092,
            key_stroke_count=162,
            char_count=369,
            wrong_char_count=0,
            date="2024-01-01 00:00:00",
        )

        text = ScoreSummaryDTO.from_score_data(score).to_clipboard_text(
            segment_label="第99999段", identity="99999"
        )

        assert text == (
            "第99999段 速度91.08 击键0.67 码长0.44 字数369 错字0 "
            "用时04:03.092 键准100.00% 键法0% 打词0.00% 选重0 回改0 "
            "键数162 退格0 回车0 重打0 哈希bdf5229d 极速打字通v2.1.6"
        )

    def test_to_clipboard_text_supports_the_championship_segment_identity(self):
        """锦标赛应使用官网的 100000 段号，而不是极速杯的 99999。"""
        score = SessionStat(
            time=60.0,
            key_stroke_count=60,
            char_count=60,
            date="2024-01-01 00:00:00",
        )

        text = ScoreSummaryDTO.from_score_data(score).to_clipboard_text(
            segment_label="第100000段", identity="100000"
        )

        assert text.startswith("第100000段 速度60.00")
        assert "第99999段" not in text

    def test_to_clipboard_text_keeps_integer_fields_as_integers(self):
        """官网格式的字数、键数等计数项不应带小数。"""
        score = SessionStat(
            time=60.0,
            key_stroke_count=300,
            char_count=240,
            wrong_char_count=0,
            date="2024-01-01 00:00:00",
        )

        text = ScoreSummaryDTO.from_score_data(score).to_clipboard_text()

        assert "字数240" in text
        assert "键数300" in text
        assert "字数240.0" not in text
        assert "键数300.00" not in text

    def test_to_clipboard_text_has_no_legacy_extra_metrics(self):
        """官网剪贴板格式不混入 typetype 专属峰值和慢字字段。"""
        score = SessionStat(
            time=60.0,
            key_stroke_count=300,
            char_count=240,
            date="2024-01-01 00:00:00",
            peak_speed=400.0,
            peak_key_stroke=8.0,
            peak_code_length=2.0,
            slow_chars=[("测", 1.2)],
        )

        text = ScoreSummaryDTO.from_score_data(score).to_clipboard_text()

        assert "峰值" not in text
        assert "慢字" not in text
        # 无单位指标不附加单位
        assert "字数240" in text

    def test_to_plain_text(self):
        """应输出纯文本格式摘要"""
        score = SessionStat(
            time=60.0,
            key_stroke_count=300,
            char_count=240,
            wrong_char_count=10,
            date="2024-01-01 00:00:00",
        )

        text = ScoreSummaryDTO.from_score_data(score).to_plain_text()

        assert "速度:" in text
        assert "字/分" in text
        assert "打词率:" in text
        assert "\n" in text

    def test_to_html(self):
        """应输出 HTML 格式摘要"""
        score = SessionStat(
            time=60.0,
            key_stroke_count=300,
            char_count=240,
            wrong_char_count=10,
            date="2024-01-01 00:00:00",
        )

        text = ScoreSummaryDTO.from_score_data(score).to_html()

        assert "<b>" in text
        assert "</b>" in text
        assert "<br>" in text
        assert "打词率" in text
