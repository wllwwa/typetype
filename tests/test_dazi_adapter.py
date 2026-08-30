"""52dazi Qt 适配层测试。"""

from types import SimpleNamespace
from unittest.mock import MagicMock
import time

from PySide6.QtCore import QCoreApplication, QThreadPool

from src.backend.models.dto.dazi_dto import (
    DaziCompetitionText,
    DaziCompetitionType,
    DaziUploadOutcome,
)
from src.backend.presentation.adapters.dazi_adapter import DaziAdapter


class ImmediateThreadPool:
    def __init__(self) -> None:
        self.started_workers = []

    def start(self, worker) -> None:
        self.started_workers.append(worker)
        worker.run()


def _build_adapter() -> tuple[DaziAdapter, MagicMock, MagicMock, MagicMock]:
    gateway = MagicMock()
    gateway.config = SimpleNamespace(
        base_url="https://example.test",
        input_method="输入法",
        upload_enabled=True,
        username="user",
        display_name="用户",
    )
    gateway.is_logged_in.return_value = True
    load_usecase = MagicMock()
    upload_usecase = MagicMock()
    adapter = DaziAdapter(gateway, load_usecase, upload_usecase)
    adapter._thread_pool = ImmediateThreadPool()
    return adapter, gateway, load_usecase, upload_usecase


def test_login_connects_signals_before_immediate_worker_runs() -> None:
    adapter, gateway, _, _ = _build_adapter()
    gateway.login.return_value = SimpleNamespace()
    results: list[tuple[bool, str]] = []
    adapter.loginResult.connect(
        lambda success, message: results.append((success, message))
    )

    adapter.login("user", "password")

    assert results == [(True, "52dazi 登录成功")]
    assert adapter._active_workers == set()


def test_load_worker_emits_result_and_clears_loading() -> None:
    adapter, _, load_usecase, _ = _build_adapter()
    load_usecase.execute.return_value = DaziCompetitionText(
        "正文", "标题", "作者", 2, DaziCompetitionType.JINBIAO
    )
    loaded: list[tuple[str, str, int]] = []
    adapter.textLoaded.connect(
        lambda text, title, code: loaded.append((text, title, code))
    )

    adapter.loadText(2)

    assert loaded == [("正文", "标题", 2)]
    assert adapter.loading is False
    assert adapter.active is True
    assert adapter.current_text.competition_type == DaziCompetitionType.JINBIAO
    assert adapter.current_segment_identity == "100000"


def test_duplicate_upload_is_ignored_until_finished() -> None:
    adapter, _, _, upload_usecase = _build_adapter()
    upload_usecase.execute.return_value = DaziUploadOutcome("排名", "3")
    results: list[tuple[bool, str, str]] = []
    adapter.uploadResult.connect(
        lambda success, message, ranking: results.append((success, message, ranking))
    )

    # 使用不会自动执行的线程池，验证第二次请求不会入队。
    pool = ImmediateThreadPool()
    original_start = pool.start
    pool.start = lambda worker: pool.started_workers.append(worker)
    adapter._thread_pool = pool
    adapter.uploadScore("标题", "正文", {"speed": 1}, competition_type=4)
    adapter.uploadScore("标题", "正文", {"speed": 1}, competition_type=4)

    assert len(pool.started_workers) == 1
    assert adapter.uploading is True
    pool.started_workers[0].signals.succeeded.emit(DaziUploadOutcome("排名", "3"))
    pool.started_workers[0].signals.finished.emit()
    assert adapter.uploading is False
    assert results == [(True, "排名", "3")]
    del original_start


def test_new_load_invalidates_previous_dazi_text() -> None:
    adapter, _, load_usecase, _ = _build_adapter()
    adapter._on_text_loaded(
        DaziCompetitionText("旧正文", "旧标题", "", 3, DaziCompetitionType.JISU)
    )
    load_usecase.execute.side_effect = RuntimeError("offline")

    adapter.loadText(0)

    assert adapter.active is False
    assert adapter.loading is False


def test_dazi_signals_arrive_via_real_threadpool() -> None:
    app = QCoreApplication.instance() or QCoreApplication(["test-dazi"])
    adapter, _, load_usecase, _ = _build_adapter()
    adapter._thread_pool = QThreadPool.globalInstance()
    load_usecase.execute.return_value = DaziCompetitionText(
        "正文", "标题", "", 2, DaziCompetitionType.JISU
    )
    loaded: list[tuple[str, str, int]] = []
    adapter.textLoaded.connect(
        lambda text, title, code: loaded.append((text, title, code))
    )

    adapter.loadText(0)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not loaded:
        app.processEvents()
        time.sleep(0.005)

    assert loaded == [("正文", "标题", 0)]
    assert adapter.loading is False
    assert not adapter._active_workers
