from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TBOS_", env_file=".env", env_file_encoding="utf-8",
    )

    database_url: str = "postgresql+psycopg://tbos:tbos_dev_password@localhost:5432/tbos"
    redis_url: str = "redis://localhost:6379/0"
    # The Odds API key — read only from env var TBOS_ODDS_API_KEY, never hardcoded.
    odds_api_key: str | None = None


settings = Settings()
