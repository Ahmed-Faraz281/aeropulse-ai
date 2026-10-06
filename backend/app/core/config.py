import json
from typing import List, Optional, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "Intelligent Air Quality Monitoring System"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"

    DATABASE_URL: str = "sqlite:///./air_quality.db"

    SECRET_KEY: str = "development-secret-key-change-in-production-min-32-chars-long"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ]

    # Development Seed Accounts (overridable in .env)
    ADMIN_USERNAME: str = "admin"
    ADMIN_EMAIL: str = "admin@aeropulse.org"
    ADMIN_PASSWORD: str = "Admin@12345"

    ANALYST_USERNAME: str = "analyst"
    ANALYST_EMAIL: str = "analyst@aeropulse.org"
    ANALYST_PASSWORD: str = "Analyst@12345"

    VIEWER_USERNAME: str = "viewer"
    VIEWER_EMAIL: str = "viewer@aeropulse.org"
    VIEWER_PASSWORD: str = "Viewer@12345"

    # OpenAQ API v3 Integration Settings (Phase 17 Step 1)
    OPENAQ_API_KEY: Optional[str] = None
    OPENAQ_BASE_URL: str = "https://api.openaq.org/v3"
    OPENAQ_TIMEOUT_SECONDS: float = 20.0
    OPENAQ_MAX_RETRIES: int = 1

    # Phase 17 Step 3: ML General Model & Retraining Policy
    MODEL_DIR: str = "backend/app/ml/models"
    ML_RETRAIN_OBSERVATION_THRESHOLD: int = 200
    ML_RETRAIN_STALE_OBSERVATION_THRESHOLD: int = 50
    ML_MODEL_STALENESS_DAYS: int = 7

    # Phase 18: Intelligent Continuous Monitoring & Automation
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_INTERVAL_MINUTES: int = 60
    SCHEDULER_POLL_MINUTE: int = 15
    SCHEDULER_MAX_STATIONS_PER_RUN: int = 10

    @field_validator("SCHEDULER_INTERVAL_MINUTES")
    @classmethod
    def validate_interval(cls, v: int) -> int:
        if v < 1:
            raise ValueError("SCHEDULER_INTERVAL_MINUTES must be >= 1")
        return v

    @field_validator("SCHEDULER_POLL_MINUTE")
    @classmethod
    def validate_poll_minute(cls, v: int) -> int:
        if v < 0 or v > 59:
            raise ValueError("SCHEDULER_POLL_MINUTE must be between 0 and 59")
        return v

    @field_validator("SCHEDULER_MAX_STATIONS_PER_RUN")
    @classmethod
    def validate_max_stations(cls, v: int) -> int:
        if v < 1:
            raise ValueError("SCHEDULER_MAX_STATIONS_PER_RUN must be >= 1")
        return v

    # Phase 19: Production Data Quality, Reliability & Trust Layer
    FRESHNESS_FRESH_THRESHOLD_HOURS: float = 3.0
    FRESHNESS_STALE_THRESHOLD_HOURS: float = 24.0

    @field_validator("FRESHNESS_FRESH_THRESHOLD_HOURS")
    @classmethod
    def validate_fresh_threshold(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("FRESHNESS_FRESH_THRESHOLD_HOURS must be > 0")
        return v

    @field_validator("FRESHNESS_STALE_THRESHOLD_HOURS")
    @classmethod
    def validate_stale_threshold(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("FRESHNESS_STALE_THRESHOLD_HOURS must be > 0")
        return v



    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            v_stripped = v.strip()
            if v_stripped.startswith("[") and v_stripped.endswith("]"):
                return json.loads(v_stripped)
            return [i.strip() for i in v.split(",") if i.strip()]
        return v


settings = Settings()
