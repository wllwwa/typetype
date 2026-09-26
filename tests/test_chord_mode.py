"""和弦模式统计测试。

覆盖：
- TypingService.accumulate_logical_key 的纯业务累积
- TypingAdapter 在和弦模式 / 普通模式下的逻辑击键口径
- 码长、击键速度、键准随逻辑击键数重算
- 退格、暂停恢复、文本重载归零
"""

from unittest.mock import MagicMock

import pytest

from src.backend.config.runtime_config import RuntimeConfig
from src.backend.domain.services.typing_service import TypingService
from src.backend.presentation.adapters.typing_adapter import TypingAdapter

TARGET = "你好世界测试文本内容啊"


def _make_adapter(chord: bool) -> tuple[TypingService, TypingAdapter, RuntimeConfig]:
    rc = RuntimeConfig()
    rc.typing.chord_mode_enabled = chord
    service = TypingService()
    adapter = TypingAdapter(
        typing_service=service,
        score_gateway=MagicMock(),
        runtime_config=rc,
    )
    service.set_total_chars(len(TARGET))
    service.set_plain_doc(TARGET)
    service.start()
    return service, adapter, rc


# ---------------------------------------------------------------------------
# 纯业务层
# ---------------------------------------------------------------------------


def test_accumulate_logical_key_adds_count():
    service = TypingService()
    service.accumulate_logical_key()
    assert service.score_data.key_stroke_count == 1
    service.accumulate_logical_key(3)
    assert service.score_data.key_stroke_count == 4


def test_accumulate_logical_key_ignores_non_positive():
    service = TypingService()
    service.accumulate_logical_key(0)
    service.accumulate_logical_key(-5)
    assert service.score_data.key_stroke_count == 0


def test_chord_mode_code_length_uses_logical_keys():
    service = TypingService()
    service.set_total_chars(40)
    service.set_plain_doc("一" * 40)
    service.start()
    for i in range(30):
        service.handle_committed_text("一", 1)
        service.accumulate_logical_key(1)
    # 码长 = 逻辑击键 / 已输入字数 = 30 / 30 = 1.0
    assert service.code_length == pytest.approx(1.0)


def test_chord_mode_speed_uses_logical_keys():
    service = TypingService()
    service.set_total_chars(10)
    service.set_plain_doc("一" * 10)
    service.start()
    for _ in range(6):
        service.handle_committed_text("一", 1)
        service.accumulate_logical_key(1)
    service.score_data.time = 6.0
    # 速度按字数：6 字 / 6s；击键速度按逻辑击键：6 / 6 = 1.0
    assert service.key_stroke == pytest.approx(1.0)


def test_chord_mode_key_accuracy_uses_new_code_length():
    service = TypingService()
    service.set_total_chars(100)
    service.set_plain_doc("一" * 100)
    service.start()
    for _ in range(50):
        service.handle_committed_text("一", 1)
        service.accumulate_logical_key(1)
    service.accumulate_backspace()
    service.accumulate_correction()
    # codeLength = 50/50 = 1.0；wrong_keys = 1 + 1*1.0 = 2
    assert service.key_accuracy == pytest.approx((50 - 2) / 50 * 100)


def test_clear_resets_logical_key_count():
    service = TypingService()
    service.accumulate_logical_key(5)
    service.clear()
    assert service.score_data.key_stroke_count == 0


def test_set_total_chars_resets_char_counts_not_key_count():
    service = TypingService()
    service.accumulate_logical_key(5)
    service.set_total_chars(20)
    assert service.score_data.char_count == 0
    assert service.score_data.wrong_char_count == 0
    assert service.score_data.key_stroke_count == 5


# ---------------------------------------------------------------------------
# 适配层：普通模式不回归
# ---------------------------------------------------------------------------


def test_normal_mode_physical_key_counts_once():
    service, adapter, _ = _make_adapter(chord=False)
    assert adapter.chord_mode_enabled is False
    adapter.handlePressed()
    assert service.score_data.key_stroke_count == 1


def test_normal_mode_commit_does_not_add_logical_key():
    service, adapter, _ = _make_adapter(chord=False)
    adapter.handlePressed()
    adapter.handleCommittedText("你好", 2)
    # 普通模式击键只由 handlePressed 计入，提交不额外累加
    assert service.score_data.key_stroke_count == 1


def test_normal_mode_backspace_counts_backspace_only():
    service, adapter, _ = _make_adapter(chord=False)
    adapter.handleBackspace()
    assert service.score_data.backspace_count == 1
    assert service.score_data.key_stroke_count == 0


# ---------------------------------------------------------------------------
# 适配层：和弦模式
# ---------------------------------------------------------------------------


def test_chord_mode_single_char_commit_counts_one():
    service, adapter, _ = _make_adapter(chord=True)
    assert adapter.chord_mode_enabled is True
    adapter.handleCommittedText("你", 1)
    assert service.score_data.key_stroke_count == 1


def test_chord_mode_multi_char_commit_counts_by_char_count():
    service, adapter, _ = _make_adapter(chord=True)
    adapter.handleCommittedText("你好世界", 4)
    assert service.score_data.key_stroke_count == 4


def test_chord_mode_physical_keys_do_not_double_count():
    """和弦模式下多个物理按键不再逐个累加（由提交统一统计）。"""
    service, adapter, _ = _make_adapter(chord=True)
    adapter.handlePressed()
    adapter.handlePressed()
    adapter.handlePressed()
    assert service.score_data.key_stroke_count == 0
    adapter.handleCommittedText("你", 1)
    assert service.score_data.key_stroke_count == 1


def test_chord_mode_backspace_counts_logical_key_and_backspace():
    service, adapter, _ = _make_adapter(chord=True)
    adapter.handleCommittedText("你", 1)
    adapter.handleBackspace()
    assert service.score_data.key_stroke_count == 2
    assert service.score_data.backspace_count == 1


def test_chord_mode_toggle_takes_effect_on_next_event():
    """开关实时生效：切换只影响后续事件，不回头换算已发生统计。"""
    service, adapter, rc = _make_adapter(chord=False)
    adapter.handlePressed()
    adapter.handleCommittedText("你", 1)
    assert service.score_data.key_stroke_count == 1

    rc.typing.chord_mode_enabled = True
    adapter.handlePressed()  # 和弦模式：物理键不计数
    adapter.handleCommittedText("好", 1)  # 提交计 1
    assert service.score_data.key_stroke_count == 2


def test_chord_mode_pause_resume_no_double_or_lost_count():
    service, adapter, _ = _make_adapter(chord=True)
    adapter.handleCommittedText("你", 1)
    assert service.score_data.key_stroke_count == 1

    assert adapter.pauseTyping() is True
    adapter.handleStartStatus(True)  # 恢复（was_paused → 不清零）

    adapter.handleCommittedText("好", 1)
    assert service.score_data.key_stroke_count == 2


def test_chord_mode_delete_commit_does_not_count_key():
    """删除路径不由提交计数（退格键显式计一次）。"""
    service, adapter, _ = _make_adapter(chord=True)
    adapter.handleCommittedText("你", 1)
    adapter.handleCommittedText("", -1)
    assert service.score_data.key_stroke_count == 1
