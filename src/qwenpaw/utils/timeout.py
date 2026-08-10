# -*- coding: utf-8 -*-
"""Shared positive-timeout parsing for tool args and console chat tasks."""
from __future__ import annotations

import math
from typing import Any

from qwenpaw.constant import DEFAULT_STREAM_TASK_TIMEOUT_SECONDS


def parse_positive_timeout_seconds(
    value: Any,
    *,
    field_name: str = "timeout",
) -> int:
    """Parse a required timeout value to positive ``int`` seconds.

    Accepts ``int`` / ``float`` / numeric strings (LLM mis-serialization).
    Rejects ``None``, bools, non-numeric values, and non-positive timeouts.
    Does not apply a default — callers decide what ``None`` means.
    """
    err = (
        f"'{field_name}' must be a positive number (seconds), "
        f"got {value!r}"
    )
    # bool is an int subclass — do not treat True/False as 1/0 seconds.
    if isinstance(value, bool):
        raise ValueError(err)
    if isinstance(value, (int, float)):
        as_float = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(err)
        try:
            as_float = float(text)
        except ValueError as exc:
            raise ValueError(err) from exc
    else:
        raise ValueError(err)
    if not math.isfinite(as_float):
        raise ValueError(err)
    # Truncation can turn (0, 1) into 0 — reject after int(), not before.
    as_int = int(as_float)
    if as_int <= 0:
        raise ValueError(err)
    return as_int


def resolve_stream_task_timeout(
    raw_timeout: Any,
    *,
    field_name: str = "timeout",
    default_seconds: int = DEFAULT_STREAM_TASK_TIMEOUT_SECONDS,
) -> int:
    """Resolve background chat-task timeout in seconds.

    ``None`` (omitted / null) uses ``default_seconds``. Otherwise parses via
    :func:`parse_positive_timeout_seconds`. Omitting timeout is never
    unbounded; callers that need a longer budget must pass an explicit
    positive value.
    """
    if raw_timeout is None:
        return int(default_seconds)
    return parse_positive_timeout_seconds(
        raw_timeout,
        field_name=field_name,
    )
