"""The single source of runtime configuration.

One :class:`Settings` object, read from environment variables only — no
``.env`` file is consulted at runtime and none is shipped in the images.
**Every field has a default that works with nothing set**: the API starts and
serves the bundled fixture with zero environment variables present. Optional
subsystems (database, geometry cache) stay off until their URL is provided.

``main.py`` logs the resolved mode of each subsystem at startup (INFO), so
"why is it not using the database" is answered by the logs, not a debugger.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "contracts" / "fixtures"

#: CORS origins allowed with nothing configured: the Vite dev server and the
#: nginx-served bundle on their conventional local ports. In the shipped
#: same-origin deployment the browser never makes a cross-origin request, so
#: this list only matters for local development.
DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://localhost:8080"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    prahari_data_source: Literal["mock", "live"] = "mock"

    # Mock mode reads this JSON array of screened events once at startup and
    # holds it in memory. Overridable with PRAHARI_EVENTS_PATH.
    prahari_events_path: Path = FIXTURES_DIR / "conjunctions.real.json"

    # Persistence is optional. With DATABASE_URL set the API reads from
    # Postgres; unset (None or ""), it falls back to the in-memory JSON data
    # source and needs no database container at all. PRAHARI_DATA_SOURCE=live
    # forces the database backend regardless.
    database_url: str | None = None

    # Geometry cache is optional too. Unset -> the cache is off and every
    # /conjunctions/{id}/geometry request is computed directly. Set it (only
    # meaningful in live mode) to memoise those responses in Redis.
    redis_url: str | None = None

    # TTL for a cached geometry response. Cache misses and an unreachable
    # Redis both fall through to a direct computation.
    geometry_cache_ttl_seconds: int = 3600

    # Redis pub/sub channel the worker publishes screened events to; the
    # live-mode /stream endpoint subscribes to it.
    conjunction_stream_channel: str = "prahari:conjunction_events"

    screening_interval_hours: float = 6.0

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # Comma-separated; parsed by cors_origins_list. Default covers the Vite
    # dev server and the local nginx bundle.
    api_cors_origins: str = DEFAULT_CORS_ORIGINS

    screening_window_hours: float = 72.0
    coarse_filter_threshold_km: float = 25.0

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]

    @property
    def use_database(self) -> bool:
        """True when the API should read from Postgres rather than the JSON fixture.

        Driven by DATABASE_URL presence, with PRAHARI_DATA_SOURCE=live as an
        explicit override for parity with the pre-persistence switch.
        """
        return bool(self.database_url) or self.prahari_data_source == "live"

    @property
    def use_geometry_cache(self) -> bool:
        """True when geometry responses should be memoised in Redis."""
        return bool(self.redis_url)

    def startup_summary(self) -> list[str]:
        """One line per subsystem describing the mode it resolved to.

        Logged at INFO by ``main.py`` before the first request so the running
        configuration is visible without setting a debugger or echoing
        secrets — the database URL is reported present/absent, never printed.
        """
        if self.use_database:
            data_source = "database (DATABASE_URL set)"
            if not self.database_url:
                data_source = "database (PRAHARI_DATA_SOURCE=live, but DATABASE_URL is unset)"
        else:
            data_source = f"in-memory JSON fixture ({self.prahari_events_path})"
        cache = (
            "Redis (REDIS_URL set)" if self.use_geometry_cache
            else "disabled, geometry computed directly (REDIS_URL unset)"
        )
        return [
            f"data source : {data_source}",
            f"geometry cache : {cache}",
            f"CORS origins : {self.cors_origins_list}",
        ]


def get_settings() -> Settings:
    return Settings()
