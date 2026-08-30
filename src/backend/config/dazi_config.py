"""52dazi 非秘密运行时配置。"""

from dataclasses import dataclass

from ..models.dto.dazi_dto import DaziCompetitionType
from ..ports.dazi_provider import DEFAULT_DAZI_BASE_URL


@dataclass
class DaziConfig:
    """52dazi 网关、账号展示和成绩上传设置。"""

    base_url: str = DEFAULT_DAZI_BASE_URL
    input_method: str = ""
    username: str = ""
    display_name: str = ""
    competition_type: int = int(DaziCompetitionType.JISU)
    upload_enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.base_url, str) or not self.base_url.startswith(
            ("http://", "https://")
        ):
            self.base_url = DEFAULT_DAZI_BASE_URL
        self.base_url = self.base_url.rstrip("/")
        if not isinstance(self.input_method, str):
            self.input_method = ""
        if not isinstance(self.username, str):
            self.username = ""
        if not isinstance(self.display_name, str):
            self.display_name = ""
        self.input_method = self.input_method[:20]
        self.competition_type = int(
            DaziCompetitionType.from_code(self.competition_type)
        )
        if not isinstance(self.upload_enabled, bool):
            self.upload_enabled = True
