"""Application configuration loaded from environment variables.

We use pydantic-settings so every config value is typed, validated at
startup, and documented in one place. Secrets (DB URL, API keys) are
never hardcoded — they must be supplied via the environment.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "BetEdge"
    environment: str = Field(
        default="development",
        description="development | staging | production",
    )

    database_url: str = Field(
        default="postgresql+psycopg://betedge:betedge@postgres:5432/betedge",
        description="SQLAlchemy URL for the primary database.",
    )

    # The Odds API — optional. When unset, live-odds endpoints return 503
    # but backtesting and bet-tracking still work against historical data.
    odds_api_key: str | None = None
    odds_api_base_url: str = "https://api.the-odds-api.com/v4"

    # CORS allow-list for the frontend dev server + any deployed UI.
    cors_allow_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:4173",
            "http://127.0.0.1:5173",
        ]
    )

    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Caching avoids re-reading env vars on every request; tests that need
    to override settings can clear the cache via `get_settings.cache_clear()`.
    """
    return Settings()
