import logging.config

from .config import settings


def setup_logging() -> None:
    """Configure console + rotating file logging for the API and the worker."""
    log_dir = settings.log_path
    level = settings.LOG_LEVEL.upper()
    detailed = "%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s"

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "detailed": {"format": detailed},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "detailed",
            },
            "app_file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "formatter": "detailed",
                "filename": str(log_dir / "app.log"),
                "when": "midnight",
                "backupCount": 30,
                "encoding": "utf8",
            },
            "error_file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "level": "ERROR",
                "formatter": "detailed",
                "filename": str(log_dir / "error.log"),
                "when": "midnight",
                "backupCount": 30,
                "encoding": "utf8",
            },
        },
        "root": {
            "level": level,
            "handlers": ["console", "app_file", "error_file"],
        },
        "loggers": {
            # Groq SDK logs every request through httpx at INFO
            "httpx": {"level": "WARNING"},
        },
    })
