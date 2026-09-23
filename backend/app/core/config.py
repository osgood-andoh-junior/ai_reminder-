from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./scheduler.db"
    environment: str = "development"
    secret_key: str = ""
    frontend_url: str = "http://localhost:3000"
    openai_api_key: str = ""
    ai_enabled: bool = True
    openai_model: str = "gpt-4.1-mini"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:3000/api/calendar/google/callback"
    token_encryption_key: str = ""
    cookie_secure: bool = False
    session_hours: int = 168
    agent_max_iterations: int = 8
    rate_limit_per_minute: int = 120
    preference_weight: float = 100
    early_weight: float = 20
    fragmentation_weight: float = 10
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = ""
    reminder_poll_interval_seconds: int = Field(default=10, ge=1, le=300)

    @field_validator("database_url")
    @classmethod
    def driver(cls, value):
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value[len("postgres://") :]
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://") :]
        return value

    def validate_production(self):
        if self.environment == "production":
            if len(self.secret_key) < 32 or not self.cookie_secure:
                raise RuntimeError("Production requires SECRET_KEY (32+ characters) and COOKIE_SECURE=true")
            if not self.frontend_url.startswith("https://"):
                raise RuntimeError("Production requires an HTTPS FRONTEND_URL")


@lru_cache
def settings():
    return Settings()
