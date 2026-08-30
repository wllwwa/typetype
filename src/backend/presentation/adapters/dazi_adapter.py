"""52dazi Qt 适配层。"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThreadPool, Signal, Slot

from ...application.gateways.dazi_gateway import DaziGateway
from ...application.usecases.dazi_usecases import (
    LoadDaziTextUseCase,
    UploadDaziScoreUseCase,
)
from ...models.dto.dazi_dto import DaziCompetitionText, DaziUploadOutcome
from ...workers.base_worker import BaseWorker


class DaziAdapter(QObject):
    """登录、竞赛载文和成绩上传的线程协调层。"""

    textLoaded = Signal(str, str, int)  # content, title, competition_type
    loadFailed = Signal(str)
    loginResult = Signal(bool, str)
    loginStateChanged = Signal()
    configChanged = Signal()
    uploadResult = Signal(bool, str, str)  # success, message, ranking
    uploadingChanged = Signal()
    loadingChanged = Signal()

    def __init__(
        self,
        gateway: DaziGateway,
        load_usecase: LoadDaziTextUseCase,
        upload_usecase: UploadDaziScoreUseCase,
    ) -> None:
        super().__init__()
        self._gateway = gateway
        self._load_usecase = load_usecase
        self._upload_usecase = upload_usecase
        self._thread_pool = QThreadPool.globalInstance()
        self._active_workers: set[BaseWorker] = set()
        self._loading = False
        self._uploading = False
        self._current_text: DaziCompetitionText | None = None

    @property
    def config(self):
        return self._gateway.config

    @property
    def logged_in(self) -> bool:
        return self._gateway.is_logged_in()

    @property
    def current_user(self) -> str:
        return self.config.display_name or self.config.username

    @property
    def active(self) -> bool:
        return self._current_text is not None

    @property
    def loading(self) -> bool:
        return self._loading

    @property
    def uploading(self) -> bool:
        return self._uploading

    @property
    def current_text(self) -> DaziCompetitionText | None:
        return self._current_text

    def _set_loading(self, value: bool) -> None:
        if self._loading != value:
            self._loading = value
            self.loadingChanged.emit()

    def _set_uploading(self, value: bool) -> None:
        if self._uploading != value:
            self._uploading = value
            self.uploadingChanged.emit()

    def _run_worker(self, task, error_prefix: str) -> BaseWorker:
        worker = BaseWorker(task=task, error_prefix=error_prefix)
        worker.setAutoDelete(False)
        self._active_workers.add(worker)
        worker.signals.finished.connect(lambda done=worker: self._release_worker(done))
        return worker

    def _start_worker(self, worker: BaseWorker) -> None:
        self._thread_pool.start(worker)

    def _release_worker(self, worker: BaseWorker) -> None:
        self._active_workers.discard(worker)

    def clear_active(self) -> None:
        self._current_text = None

    @Slot(str, str)
    def login(self, username: str, password: str) -> None:
        worker = self._run_worker(
            lambda: self._gateway.login(username, password), "52dazi 登录失败"
        )
        worker.signals.succeeded.connect(self._on_login_succeeded)
        worker.signals.failed.connect(
            lambda message: self.loginResult.emit(False, message)
        )
        self._start_worker(worker)

    def _on_login_succeeded(self, _result) -> None:
        self.loginStateChanged.emit()
        self.configChanged.emit()
        self.loginResult.emit(True, "52dazi 登录成功")

    @Slot()
    def logout(self) -> None:
        self.clear_active()
        self._gateway.logout()
        self.loginStateChanged.emit()
        self.configChanged.emit()

    @Slot(int)
    def loadText(self, competition_type: int) -> None:
        if self._loading:
            return
        self.clear_active()
        self._set_loading(True)
        worker = self._run_worker(
            lambda: self._load_usecase.execute(competition_type), "52dazi 载入赛文失败"
        )
        worker.signals.succeeded.connect(self._on_text_loaded)
        worker.signals.failed.connect(self._on_load_failed)
        worker.signals.finished.connect(lambda: self._set_loading(False))
        self._start_worker(worker)

    def _on_text_loaded(self, result: DaziCompetitionText) -> None:
        self._current_text = result
        self.textLoaded.emit(result.content, result.title, int(result.competition_type))

    def _on_load_failed(self, message: str) -> None:
        self.loadFailed.emit(message)

    @Slot(str, str, dict)
    def uploadScore(
        self, title: str, content: str, score: dict, competition_type: int = 0
    ) -> None:
        if self._uploading:
            return
        self._set_uploading(True)
        worker = self._run_worker(
            lambda: self._upload_usecase.execute(
                title, content, score, competition_type
            ),
            "52dazi 成绩上传失败",
        )
        worker.signals.succeeded.connect(self._on_upload_succeeded)
        worker.signals.failed.connect(
            lambda message: self.uploadResult.emit(False, message, "")
        )
        worker.signals.finished.connect(lambda: self._set_uploading(False))
        self._start_worker(worker)

    def _on_upload_succeeded(self, result: DaziUploadOutcome) -> None:
        message = result.message or "52dazi 成绩上传成功"
        self.uploadResult.emit(True, message, result.ranking)

    @Slot(str, int, bool)
    def updateConfig(
        self, base_url: str, competition_type: int, upload_enabled: bool
    ) -> None:
        self._gateway.update_config(
            base_url=base_url,
            competition_type=competition_type,
            upload_enabled=upload_enabled,
        )
        self.configChanged.emit()

    @Slot(str)
    def updateInputMethod(self, input_method: str) -> None:
        self._gateway.update_config(input_method=input_method)
        self.configChanged.emit()
