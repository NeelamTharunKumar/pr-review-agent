from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    GITHUB_TOKEN: str
    GITHUB_WEBHOOK_SECRET: str
    GROQ_API_KEY: str
    GEMINI_API_KEY: str

    DATABASE_URL: str = "sqlite:///./reviews.db"
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"
    AGENTIC_MODE: bool = False
    MAX_DIFF_LINES_PER_FILE: int = 1000

    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    USE_CELERY: bool = False

    LLM_PRIMARY: str = "groq"
    LLM_FALLBACK: str = "gemini"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
