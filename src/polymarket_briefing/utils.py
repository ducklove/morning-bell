from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


def read_secret(env_var: str, *aliases: str, keys_path: str = "keys") -> str | None:
    """Read a secret from the environment, falling back to a local `keys` file.

    The `keys` file holds `NAME=value` lines (comments starting with `#` are
    ignored). `env_var` and any `aliases` are matched case-insensitively.
    """
    value = os.environ.get(env_var)
    if value:
        return value
    names = {env_var.strip().lower()} | {alias.strip().lower() for alias in aliases}
    path = Path(keys_path)
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        if key.strip().lower() in names:
            return raw_value.strip().strip('"').strip("'")
    return None


def parse_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def as_list(value: Any) -> list[Any]:
    parsed = parse_jsonish(value)
    if parsed is None:
        return []
    if isinstance(parsed, list):
        return parsed
    return [parsed]


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def pct(probability: float | None) -> str:
    if probability is None:
        return "확률 없음"
    return f"{probability * 100:.1f}%"


def pp(delta: float | None) -> str:
    if delta is None:
        return ""
    sign = "+" if delta >= 0 else ""
    return f" ({sign}{delta:.1f}pp)"

