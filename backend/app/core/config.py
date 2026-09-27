from typing import List
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application Settings
    APP_NAME: str = "Bank Statement Parser"
    VERSION: str = "2.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Server Settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # CORS Settings
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    # Database Settings
    DATABASE_URL: str = "sqlite:///./database.db"

    # File Storage Settings
    UPLOAD_DIR: str = "./uploads"
    PAGE_IMAGES_DIR: str = "./page_images"
    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024  # 50MB
    MAX_PAGES: int = 100

    # Celery / Redis
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    TASK_TIME_LIMIT: int = 30 * 60  # Hard limit per statement, seconds

    # Groq API Settings
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    GROQ_TEMPERATURE: float = 0.1
    GROQ_MAX_TOKENS: int = 8192
    GROQ_REQUEST_TIMEOUT: int = 120
    GROQ_MAX_RETRIES: int = 3
    PAGE_CONCURRENCY: int = 3  # Pages sent to Groq in parallel per statement

    # PDF Rendering Settings
    PDF_DPI: int = 200
    JPEG_QUALITY: int = 85
    MAX_IMAGE_BYTES: int = 3 * 1024 * 1024  # Groq caps base64 images at 4MB

    # Processing Settings
    CLEANUP_TEMP_FILES: bool = True

    # PII Settings
    MASK_PII: bool = True
    PII_MASK_CHAR: str = "X"
    PII_SHOW_LAST: int = 4

    # Logging Settings
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "./logs"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins from comma-separated string."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def upload_path(self) -> Path:
        """Get upload directory as Path object."""
        path = Path(self.UPLOAD_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def page_images_path(self) -> Path:
        """Get page image scratch directory as Path object."""
        path = Path(self.PAGE_IMAGES_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def log_path(self) -> Path:
        """Get log directory as Path object."""
        path = Path(self.LOG_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
