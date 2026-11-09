from functools import lru_cache

from pydantic import EmailStr, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://localhost:5432/wedding_rsvp"
    cors_origins: list[str] = Field(default_factory=list)
    rsvp_recipient: EmailStr = "bhuisompa001@gmail.com"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: str = ""
    mail_from: str = ""
    outbox_poll_seconds: float = Field(default=3, gt=0, le=300)
    outbox_max_attempts: int = Field(default=8, ge=1, le=100)
    outbox_lease_seconds: int = Field(default=120, ge=10, le=3600)
    rate_limit_requests: int = Field(default=10, ge=1, le=1000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str) and value and not value.lstrip().startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    def validate_email_configuration(self) -> None:
        missing = [
            name
            for name, value in (
                ("SMTP_USERNAME", self.smtp_username),
                ("SMTP_PASSWORD", self.smtp_password),
                ("MAIL_FROM", self.mail_from),
            )
            if not value.strip()
        ]
        if missing:
            raise ValueError(f"Missing required email configuration: {', '.join(missing)}")

    @property
    def sqlalchemy_database_url(self) -> str:
        url = make_url(self.database_url)
        if url.drivername in {"postgres", "postgresql"}:
            url = url.set(drivername="postgresql+psycopg")
        return url.render_as_string(hide_password=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
