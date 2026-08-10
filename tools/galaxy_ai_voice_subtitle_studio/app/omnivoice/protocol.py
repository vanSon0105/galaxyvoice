from __future__ import annotations

import json
from typing import Any


PROTOCOL_VERSION = 1


class ProtocolError(ValueError):
    pass


def encode_message(message: dict[str, Any]) -> str:
    _validate_message(message)
    return json.dumps(message, ensure_ascii=True, separators=(",", ":")) + "\n"


def decode_message(raw: str) -> dict[str, Any]:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProtocolError(f"Invalid JSON message: {error}") from error
    _validate_message(message)
    return message


def request_message(request_id: str, command: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "type": command,
        "payload": payload,
    }


def _validate_message(message: object) -> None:
    if not isinstance(message, dict):
        raise ProtocolError("Protocol message must be a JSON object.")
    message_type = message.get("type")
    if not isinstance(message_type, str) or not message_type.strip():
        raise ProtocolError("Protocol message needs a non-empty type.")
    version = message.get("protocol_version")
    if version is not None and version != PROTOCOL_VERSION:
        raise ProtocolError(f"Unsupported protocol version: {version}")
