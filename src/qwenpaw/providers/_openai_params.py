# -*- coding: utf-8 -*-
"""OpenAI SDK parameter whitelists and non-standard kwargs routing utility."""
from __future__ import annotations

from typing import Any

# OpenAI SDK chat.completions.create() accepted parameters.
# Parameters NOT in this set are routed into extra_body.
# Reference: openai-python SDK v2.33 (last verified)
# API: https://platform.openai.com/docs/api-reference/chat/create
# SDK: https://github.com/openai/openai-python
OPENAI_CHAT_CREATE_PARAMS: frozenset[str] = frozenset(
    {
        "messages",
        "model",
        "audio",
        "frequency_penalty",
        "function_call",
        "functions",
        "logit_bias",
        "logprobs",
        "max_completion_tokens",
        "max_tokens",
        "metadata",
        "modalities",
        "n",
        "parallel_tool_calls",
        "prediction",
        "presence_penalty",
        "prompt_cache_key",
        "prompt_cache_retention",
        "reasoning_effort",
        "response_format",
        "safety_identifier",
        "seed",
        "service_tier",
        "stop",
        "store",
        "stream",
        "stream_options",
        "temperature",
        "tool_choice",
        "tools",
        "top_logprobs",
        "top_p",
        "user",
        "verbosity",
        "web_search_options",
        # SDK-level params (not sent in body, handled by SDK transport)
        "extra_headers",
        "extra_query",
        "extra_body",
        "timeout",
    },
)

# OpenAI SDK responses.create() accepted parameters.
# Reference: openai-python SDK v2.33 (last verified)
# API: https://platform.openai.com/docs/api-reference/responses/create
OPENAI_RESPONSE_CREATE_PARAMS: frozenset[str] = frozenset(
    {
        "model",
        "input",
        "stream",
        "include",
        "instructions",
        "max_output_tokens",
        "metadata",
        "parallel_tool_calls",
        "previous_response_id",
        "reasoning",
        "store",
        "temperature",
        "text",
        "tool_choice",
        "tools",
        "top_p",
        "truncation",
        "user",
        # SDK-level params
        "extra_headers",
        "extra_query",
        "extra_body",
        "timeout",
    },
)


def _deep_merge(
    base: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any]:
    """Recursively merge *override* into *base* (returns a new dict).

    Intentional copy of Provider._deep_merge to avoid circular import
    between this utility module and provider.py.  Keep in sync.
    """
    result = dict(base)
    for key, val in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(val, dict)
        ):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def route_non_standard_to_extra_body(
    gen_kwargs: dict[str, Any],
    known_params: frozenset[str] = OPENAI_CHAT_CREATE_PARAMS,
) -> None:
    """Route non-standard kwargs in *gen_kwargs* into ``extra_body``.

    **Mutates** *gen_kwargs* in place.  Callers must pass a mutable copy
    (``get_effective_generate_kwargs()`` always returns a fresh dict).

    Routing rules:

    - Keys not in *known_params* are considered non-standard and moved
      into ``gen_kwargs["extra_body"]``.
    - User-explicit ``extra_body`` takes precedence over auto-routed keys
      of the same name (deep merge with explicit values winning).
    - If ``extra_body`` is configured as a non-dict, it is treated as
      empty to avoid deferred TypeErrors.
    """
    if not gen_kwargs:
        return
    extra_body = gen_kwargs.pop("extra_body", None)
    if not isinstance(extra_body, dict):
        extra_body = {}
    non_standard = {
        k: v for k, v in list(gen_kwargs.items()) if k not in known_params
    }
    for k in non_standard:
        del gen_kwargs[k]
    if non_standard or extra_body:
        merged = _deep_merge(non_standard, extra_body)
        if merged:
            gen_kwargs["extra_body"] = merged
