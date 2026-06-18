# -*- coding: utf-8 -*-
"""Lightweight JSON5 parser with graceful fallback."""
from __future__ import annotations

import json
import re


def parse_json5(text: str) -> dict:
    """Parse JSON5, fallback to built-in stripper if pyjson5 unavailable."""
    try:
        import pyjson5

        return pyjson5.loads(text)
    except ImportError:
        return json.loads(_strip_json5_features(text))


def _process_normal(ch, text, i, n, result):
    """Process character in normal state. Returns (next_state, next_i)."""
    if ch == '"':
        result.append(ch)
        return "in_string", i + 1
    nxt = text[i : i + 2] if i + 1 < n else ""
    if nxt == "//":
        return "in_line_comment", i + 2
    if nxt == "/*":
        return "in_block_comment", i + 2
    result.append(ch)
    return "normal", i + 1


def _process_string(ch, text, i, n, result):
    """Process character in string state. Returns (next_state, next_i)."""
    result.append(ch)
    if ch == "\\" and i + 1 < n:
        result.append(text[i + 1])
        return "in_string", i + 2
    if ch == '"':
        return "normal", i + 1
    return "in_string", i + 1


_STATE_HANDLERS = {
    "normal": _process_normal,
    "in_string": _process_string,
}


def _strip_json5_features(text: str) -> str:
    """Remove JSON5 comments and trailing commas via state machine."""
    result: list[str] = []
    i = 0
    n = len(text)
    state = "normal"

    while i < n:
        ch = text[i]
        handler = _STATE_HANDLERS.get(state)
        if handler is not None:
            state, i = handler(ch, text, i, n, result)
        elif state == "in_line_comment":
            if ch == "\n":
                result.append("\n")
                state = "normal"
            i += 1
        elif state == "in_block_comment":
            if i + 1 < n and text[i : i + 2] == "*/":
                state = "normal"
                i += 2
            else:
                i += 1

    stripped = "".join(result)
    return re.sub(r",\s*([}\]])", r"\1", stripped)
