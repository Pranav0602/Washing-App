"""Environment variable reading helpers.

Every configuration value in this project comes from the environment. Nothing is
hardcoded and nothing has a usable production default: :func:`require` raises so a
deployment with a missing secret fails loudly at boot instead of silently running
insecurely.
"""

from __future__ import annotations

import os
from typing import TypeVar

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}

T = TypeVar("T")


class MissingSettingError(RuntimeError):
    """Raised when a required environment variable is absent or empty."""


def get(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def require(name: str) -> str:
    value = get(name)
    if value is None:
        raise MissingSettingError(
            f"Required environment variable {name!r} is not set. "
            "Copy .env.example to .env and fill it in."
        )
    return value


def get_bool(name: str, default: bool = False) -> bool:
    raw = get(name)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ValueError(f"Environment variable {name!r} must be a boolean, got {raw!r}")


def get_int(name: str, default: int) -> int:
    raw = get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name!r} must be an integer, got {raw!r}") from exc


def get_float(name: str, default: float) -> float:
    raw = get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name!r} must be a number, got {raw!r}") from exc


def get_list(name: str, default: list[str] | None = None, separator: str = ",") -> list[str]:
    raw = get(name)
    if raw is None:
        return list(default or [])
    return [item.strip() for item in raw.split(separator) if item.strip()]


def get_choice(name: str, choices: tuple[str, ...], default: str) -> str:
    raw = get(name, default)
    if raw not in choices:
        raise ValueError(f"Environment variable {name!r} must be one of {choices}, got {raw!r}")
    return raw


def load_dotenv_if_present(path: str = ".env") -> None:
    """Load a .env file without overriding variables already in the environment."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dotenv is a declared dependency
        return
    load_dotenv(path, override=False)