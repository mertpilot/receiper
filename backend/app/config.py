from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass
class Settings:
    app_name: str
    environment: str
    database_url: str
    jwt_secret: str
    jwt_algorithm: str
    access_token_expire_minutes: int
    upload_root: str
    max_upload_mb: int
    allowed_origins: list[str]
    pairing_ttl_minutes: int
    dashboard_base_url: str


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


@lru_cache
def get_settings() -> Settings:
    raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
    origins = [part.strip() for part in raw_origins.split(",") if part.strip()]
    if not origins:
        origins = ["*"]

    return Settings(
        app_name=os.getenv("APP_NAME", "Receiper Cloud"),
        environment=os.getenv("APP_ENV", "development"),
        database_url=_normalize_database_url(os.getenv("DATABASE_URL", "sqlite:///./data/receiper.db")),
        jwt_secret=os.getenv("JWT_SECRET", "change-me-in-production"),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        access_token_expire_minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "43200")),
        upload_root=os.getenv("UPLOAD_ROOT", "data/uploads"),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "10")),
        allowed_origins=origins,
        pairing_ttl_minutes=int(os.getenv("PAIRING_TTL_MINUTES", "5")),
        dashboard_base_url=os.getenv("DASHBOARD_BASE_URL", ""),
    )

