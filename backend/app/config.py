"""Settings from environment variables / `.env` (see `.env.example`)."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env also holds variables for the hindsight-api server
    )

    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = "openai/gpt-oss-120b"
    groq_fallback_model: str = "qwen/qwen3-32b"

    hindsight_base_url: str = "http://localhost:8888"
    hindsight_api_key: SecretStr = SecretStr("")
    hindsight_bank_id: str = "munshi-rao-associates"

    db_path: Path = Path("data/munshi.db")
    data_dir: Path = Path("data/generated")

    def resolve(self, path: Path) -> Path:
        """Relative paths are relative to the project root, not the working directory."""
        return path if path.is_absolute() else PROJECT_ROOT / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
