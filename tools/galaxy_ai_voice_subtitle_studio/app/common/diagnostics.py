from __future__ import annotations

import logging
import os
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOGGER_NAME = "galaxy_ai_studio"
_HANDLER_MARKER = "_galaxy_diagnostics_handler"
_BASE_LOGGER = logging.getLogger(LOGGER_NAME)
_BASE_LOGGER.addHandler(logging.NullHandler())
_BASE_LOGGER.propagate = False


def default_log_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "GalaxyAIStudio" / "logs" / "galaxy-studio.log"
    return Path(tempfile.gettempdir()) / "GalaxyAIStudio" / "logs" / "galaxy-studio.log"


def configure_logging(path: Path | None = None) -> Path:
    log_path = (path or default_log_path()).resolve()
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return log_path

    for handler in tuple(logger.handlers):
        if not getattr(handler, _HANDLER_MARKER, False):
            continue
        if Path(handler.baseFilename) == log_path:
            return log_path
        logger.removeHandler(handler)
        handler.close()

    try:
        handler = RotatingFileHandler(
            log_path,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
            delay=True,
        )
    except OSError:
        return log_path
    setattr(handler, _HANDLER_MARKER, True)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.info("Application logging initialized")
    return log_path


def get_logger(module: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{module}")


def log_operation_failure(logger: logging.Logger, operation: str, error: BaseException) -> None:
    logger.error("%s failed (%s)", operation, type(error).__name__)
