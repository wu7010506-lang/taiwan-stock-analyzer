from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_path: Path = Path("data/stocks.db")
    http_timeout_seconds: float = 20
    user_agent: str = "taiwan-stock-analyzer/0.1"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

