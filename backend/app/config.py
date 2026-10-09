from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://localhost/dooh"
    media_dir: Path = BACKEND_DIR.parent / "media"
    admin_password: str = "change-me"
    secret_key: str = "dev-secret-change-me"
    admin_token_days: int = 30

    # A screen counts as offline after this many seconds without a heartbeat
    # (3 missed heartbeats at the 60 s interval).
    offline_after_seconds: int = 180
    default_item_seconds: int = 10

    def resolved_media_dir(self) -> Path:
        path = self.media_dir
        if not path.is_absolute():
            path = (BACKEND_DIR / path).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
