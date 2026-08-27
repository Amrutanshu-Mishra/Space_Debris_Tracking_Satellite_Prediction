"""App settings, loaded from environment / .env. See .env.example for the full list."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "contracts" / "fixtures"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    prahari_data_source: Literal["mock", "live"] = "mock"

    database_url: str = "postgresql+asyncpg://prahari:prahari@localhost:5432/prahari"
    redis_url: str = "redis://localhost:6379/0"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_cors_origins: str = "http://localhost:5173"

    screening_window_hours: float = 72.0
    coarse_filter_threshold_km: float = 25.0

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


def get_settings() -> Settings:
    return Settings()
