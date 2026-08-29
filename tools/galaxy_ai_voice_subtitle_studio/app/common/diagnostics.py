from __future__ import annotations

import logging
import os
import re
import tempfile
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import BinaryIO, Iterator


LOGGER_NAME = "galaxy_ai_studio"
_HANDLER_MARKER = "_galaxy_diagnostics_handler"
_BASE_LOGGER = logging.getLogger(LOGGER_NAME)
_BASE_LOGGER.addHandler(logging.NullHandler())
_BASE_LOGGER.propagate = False
_SENSITIVE_KEY = r"(?:api[_-]?key|token|secret|password|authorization|credential|cookie)"
_QUOTED_SENSITIVE_ASSIGNMENT = re.compile(
    rf"(?i)([\"']?{_SENSITIVE_KEY}[\"']?\s*[:=]\s*)([\"'])(.*?)(\2)"
)
_AUTHORIZATION_ASSIGNMENT = re.compile(
    r"(?i)(\bauthorization\s*[:=]\s*)(?:Bearer|Basic|Digest|Token)?\s*[^\s,;}]+"
)
_SENSITIVE_ASSIGNMENT = re.compile(
    rf"(?i)([\"']?{_SENSITIVE_KEY}"
    r"[\"']?\s*[:=]\s*)([\"']?)([^\s,;}]+)"
)
_BEARER_VALUE = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_CREDENTIAL_PHRASE = re.compile(
    rf"(?i)(\b(?:openai|deepseek|nvidia|hugging\s*face|hf)?\s*{_SENSITIVE_KEY}"
    r"(?:\s+provided)?\s*:\s*)([^\s,;}]+)"
)
_PROVIDER_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_-])(?:sk-[A-Za-z0-9_-]{8,}|nvapi-[A-Za-z0-9_-]{8,}|hf_[A-Za-z0-9]{8,})(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)


def redact_sensitive_text(value: object) -> str:
    text = str(value)

    def replace_quoted(match: re.Match[str]) -> str:
        quote = match.group(2)
        return f"{match.group(1)}{quote}***{quote}"

    def replace(match: re.Match[str]) -> str:
        quote = match.group(2)
        return f"{match.group(1)}{quote}***{quote}"

    text = _QUOTED_SENSITIVE_ASSIGNMENT.sub(replace_quoted, text)
    text = _AUTHORIZATION_ASSIGNMENT.sub(r"\1***", text)
    text = _SENSITIVE_ASSIGNMENT.sub(replace, text)
    text = _CREDENTIAL_PHRASE.sub(r"\1***", text)
    text = _BEARER_VALUE.sub("Bearer ***", text)
    return _PROVIDER_TOKEN.sub("***", text)


@contextmanager
def redacted_binary_log(path: Path) -> Iterator[BinaryIO]:
    """Capture subprocess output and sanitize the retained log on every exit path."""

    log_path = Path(path)
    stream = log_path.open("wb")
    try:
        yield stream
    finally:
        stream.close()
        try:
            raw = log_path.read_bytes()
            safe = redact_sensitive_text(raw.decode("utf-8", errors="replace"))
            temporary = log_path.with_name(f"{log_path.name}.tmp")
            temporary.write_text(safe, encoding="utf-8")
            temporary.replace(log_path)
        except OSError:
            pass


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
