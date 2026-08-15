from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_path: Path = Path("data/stocks.db")
    http_timeout_seconds: float = 20
    user_agent: str = "taiwan-stock-analyzer/0.1"
    finmind_token: str | None = None
    admin_api_key: str | None = None
    require_admin_key: bool = False
    daily_sync_enabled: bool = True
    daily_sync_hour: int = 15
    daily_sync_minute: int = 40
    daily_sync_timezone: str = "Asia/Taipei"
    daily_sync_retry_minutes: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
