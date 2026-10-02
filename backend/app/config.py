"""Application settings, loaded from the environment with sane local defaults."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Sales Data Processing & Analytics Pipeline"
    version: str = "1.0.0"
    environment: str = "development"

    # --- storage -------------------------------------------------------
    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'sales.db'}"
    upload_dir: Path = BACKEND_DIR / "data" / "uploads"
    log_dir: Path = BACKEND_DIR / "logs"

    # --- auth ----------------------------------------------------------
    jwt_secret: str = "dev-secret-change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24
    password_min_length: int = 8

    # --- processing ----------------------------------------------------
    worker_pool_size: int = 8
    row_processing_delay_ms: float = 2.0
    row_max_retries: int = 2
    row_retry_backoff_ms: float = 10.0
    progress_emit_every: int = 25
    db_insert_chunk_size: int = 1000
    variance_cv_threshold: float = 1.0
    # "id" matches repeated transaction_ids only; "id_and_content" also flags a
    # sale re-submitted under a fresh id (identical on every other field).
    duplicate_detection: str = "id_and_content"

    # --- limits --------------------------------------------------------
    max_upload_mb: int = 50
    upload_rate_limit: int = 20
    upload_rate_window_seconds: int = 60

    # --- misc ----------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"
    log_level: str = "INFO"
    log_json: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite:///"):
        Path(settings.database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
