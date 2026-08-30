"""52dazi 应用层网关。"""

from __future__ import annotations

from ...config.dazi_config import DaziConfig
from ...config.runtime_config import RuntimeConfig
from ...models.dto.dazi_dto import (
    DaziCompetitionText,
    DaziCompetitionType,
    DaziLoginResult,
    DaziUploadOutcome,
)
from ...ports.dazi_provider import DaziProvider
from ...ports.token_store import TokenStore


class DaziGateway:
    """封装 52dazi 会话秘密和配置持久化。"""

    TOKEN_KEY = "dazi_token"
    COOKIE_KEY = "dazi_cookie"

    def __init__(
        self,
        runtime_config: RuntimeConfig,
        provider: DaziProvider,
        token_store: TokenStore,
    ) -> None:
        self._runtime_config = runtime_config
        self._provider = provider
        self._token_store = token_store

    @property
    def config(self) -> DaziConfig:
        return self._runtime_config.dazi

    def is_logged_in(self) -> bool:
        return bool(
            self._token_store.get_token(self.TOKEN_KEY) and self.config.username
        )

    def login(self, username: str, password: str) -> DaziLoginResult:
        result = self._provider.login(username, password)
        self._token_store.save_token(self.TOKEN_KEY, result.token)
        if result.cookie:
            self._token_store.save_token(self.COOKIE_KEY, result.cookie)
        self._runtime_config.update_dazi_user(
            username=username,
            display_name=result.display_name or username,
        )
        return result

    def logout(self) -> None:
        for key in (self.TOKEN_KEY, self.COOKIE_KEY):
            try:
                self._token_store.delete_token(key)
            except Exception:
                pass
        self._runtime_config.clear_dazi_user()

    def update_config(
        self,
        *,
        base_url: str | None = None,
        input_method: str | None = None,
        competition_type: int | None = None,
        upload_enabled: bool | None = None,
    ) -> None:
        self._runtime_config.update_dazi_config(
            base_url=base_url,
            input_method=input_method,
            competition_type=competition_type,
            upload_enabled=upload_enabled,
        )
        self._provider.update_base_url(self.config.base_url)

    def get_content(self, competition_type: DaziCompetitionType) -> DaziCompetitionText:
        token = self._token_store.get_token(self.TOKEN_KEY) or ""
        cookie = self._token_store.get_token(self.COOKIE_KEY) or ""
        result, new_cookie = self._provider.get_content(token, cookie, competition_type)
        self._save_cookie(new_cookie)
        return result

    def upload_result(self, payload: dict) -> DaziUploadOutcome:
        token = self._token_store.get_token(self.TOKEN_KEY) or ""
        cookie = self._token_store.get_token(self.COOKIE_KEY) or ""
        result, new_cookie = self._provider.upload_result(token, cookie, payload)
        self._save_cookie(new_cookie)
        return result

    def _save_cookie(self, cookie: str) -> None:
        if cookie:
            self._token_store.save_token(self.COOKIE_KEY, cookie)
