from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/llm4ias"
    )


    gemini_api_key: str = Field(default="")
    gemini_model_name: str = Field(default="gemini-1.5-flash")


    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")


    agent_event_window_size: int = Field(default=1, ge=1)
    agent_poll_interval_seconds: float = Field(default=0.5, gt=0.0)


    modules_config_dir: Path = Field(
        default=Path(__file__).parent / "modules"
    )


    enable_summarization: bool = Field(default=False)

    summary_interval_seconds: float = Field(
        default=60.0,
        gt=0.0,
    )


    cors_allowed_origins: list[str] = Field(
        default_factory=list,
    )

    @field_validator("database_url")
    @classmethod
    def validate_asyncpg_scheme(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must use "
                "'postgresql+asyncpg://'"
            )
        return v

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
