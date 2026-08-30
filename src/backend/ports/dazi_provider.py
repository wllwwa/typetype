"""52dazi 外部服务 Port。"""

from typing import Protocol

from ..models.dto.dazi_dto import (
    DaziCompetitionText,
    DaziCompetitionType,
    DaziLoginResult,
    DaziUploadOutcome,
)

DEFAULT_DAZI_BASE_URL = "https://www.jsxiaoshi.com/index.php"


class DaziProvider(Protocol):
    """52dazi HTTP 客户端需要提供的最小能力。"""

    def login(self, username: str, password: str) -> DaziLoginResult: ...

    def get_content(
        self, token: str, cookie: str, competition_type: DaziCompetitionType
    ) -> tuple[DaziCompetitionText, str]: ...

    def upload_result(
        self, token: str, cookie: str, payload: dict
    ) -> tuple[DaziUploadOutcome, str]: ...

    def update_base_url(self, base_url: str) -> None: ...

    def close(self) -> None: ...
