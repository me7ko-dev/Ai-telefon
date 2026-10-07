import logging
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

_INSECURE = {"smeni-me", "smeni-me-s-dalag-sluchaen-niz", "smeni-me-tool-secret", ""}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    admin_password: str = "smeni-me"
    secret_key: str = "smeni-me-s-dalag-sluchaen-niz"
    tool_secret: str = "smeni-me-tool-secret"
    database_url: str = "sqlite:///./data/app.db"
    panel_business_slug: str = "demo"
    seed_demo: bool = True
    public_base_url: str = "http://localhost:8000"
    elevenlabs_api_key: str = ""
    elevenlabs_api_url: str = "https://api.elevenlabs.io"

    def warn_if_insecure(self) -> None:
        for name in ("admin_password", "secret_key", "tool_secret"):
            if getattr(self, name) in _INSECURE:
                log.warning("%s е със стойност по подразбиране – смени я в .env преди да излагаш API-то навън.", name.upper())


@lru_cache
def get_settings() -> Settings:
    return Settings()
