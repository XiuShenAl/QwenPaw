# -*- coding: utf-8 -*-
"""Tests for _openai_params module: whitelist routing and deep merge."""
from __future__ import annotations

from qwenpaw.providers._openai_params import (
    OPENAI_CHAT_CREATE_PARAMS,
    OPENAI_RESPONSE_CREATE_PARAMS,
    _deep_merge,
    route_non_standard_to_extra_body,
)


class TestDeepMerge:
    def test_flat_override(self) -> None:
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        assert _deep_merge(base, override) == {"a": 1, "b": 3, "c": 4}

    def test_nested_dict_recursive(self) -> None:
        base = {"opts": {"x": 1, "y": 2}}
        override = {"opts": {"y": 3, "z": 4}}
        assert _deep_merge(base, override) == {
            "opts": {"x": 1, "y": 3, "z": 4},
        }

    def test_override_replaces_non_dict(self) -> None:
        base = {"a": {"nested": True}}
        override = {"a": "scalar"}
        assert _deep_merge(base, override) == {"a": "scalar"}

    def test_does_not_mutate_base(self) -> None:
        base = {"a": {"b": 1}}
        override = {"a": {"c": 2}}
        _deep_merge(base, override)
        assert base == {"a": {"b": 1}}


class TestRouteNonStandardToExtraBody:
    def test_empty_dict_is_noop(self) -> None:
        kwargs: dict = {}
        route_non_standard_to_extra_body(kwargs)
        assert not kwargs

    def test_standard_params_preserved(self) -> None:
        kwargs = {"seed": 42, "stop": ["\n"], "temperature": 0.7}
        route_non_standard_to_extra_body(kwargs)
        assert kwargs == {"seed": 42, "stop": ["\n"], "temperature": 0.7}

    def test_non_standard_routed_to_extra_body(self) -> None:
        kwargs = {"seed": 42, "enable_search": True, "custom_flag": "yes"}
        route_non_standard_to_extra_body(kwargs)
        assert kwargs == {
            "seed": 42,
            "extra_body": {"enable_search": True, "custom_flag": "yes"},
        }

    def test_explicit_extra_body_wins_over_auto_routed(self) -> None:
        kwargs = {
            "enable_search": False,
            "extra_body": {"enable_search": True, "other": 1},
        }
        route_non_standard_to_extra_body(kwargs)
        assert kwargs == {
            "extra_body": {"enable_search": True, "other": 1},
        }

    def test_deep_merge_nested_dict_conflict(self) -> None:
        kwargs = {
            "search_options": {"enable_citation": True},
            "extra_body": {"search_options": {"source": "web"}},
        }
        route_non_standard_to_extra_body(kwargs)
        assert kwargs == {
            "extra_body": {
                "search_options": {"enable_citation": True, "source": "web"},
            },
        }

    def test_extra_body_non_dict_degrades_to_empty(self) -> None:
        kwargs = {"enable_search": True, "extra_body": "invalid"}
        route_non_standard_to_extra_body(kwargs)
        assert kwargs == {"extra_body": {"enable_search": True}}

    def test_extra_body_none_treated_as_empty(self) -> None:
        kwargs = {"enable_search": True, "extra_body": None}
        route_non_standard_to_extra_body(kwargs)
        assert kwargs == {"extra_body": {"enable_search": True}}

    def test_response_api_whitelist(self) -> None:
        kwargs = {
            "temperature": 0.5,
            "top_p": 0.9,
            "enable_thinking": True,
        }
        route_non_standard_to_extra_body(kwargs, OPENAI_RESPONSE_CREATE_PARAMS)
        assert kwargs == {
            "temperature": 0.5,
            "top_p": 0.9,
            "extra_body": {"enable_thinking": True},
        }

    def test_no_extra_body_when_nothing_to_route(self) -> None:
        kwargs = {"temperature": 0.5, "seed": 123}
        route_non_standard_to_extra_body(kwargs)
        assert "extra_body" not in kwargs


class TestWhitelistCompleteness:
    """Sanity checks on the whitelists themselves."""

    def test_chat_params_contains_sdk_transport(self) -> None:
        for param in ("extra_headers", "extra_query", "extra_body", "timeout"):
            assert param in OPENAI_CHAT_CREATE_PARAMS

    def test_response_params_contains_sdk_transport(self) -> None:
        for param in ("extra_headers", "extra_query", "extra_body", "timeout"):
            assert param in OPENAI_RESPONSE_CREATE_PARAMS

    def test_chat_params_contains_common_params(self) -> None:
        for param in (
            "temperature",
            "max_tokens",
            "top_p",
            "seed",
            "stop",
            "stream",
            "tools",
        ):
            assert param in OPENAI_CHAT_CREATE_PARAMS

    def test_original_commit_params_present(self) -> None:
        """Params from original commit 881b9dbd must all be present."""
        for param in (
            "prompt_cache_key",
            "prompt_cache_retention",
            "safety_identifier",
            "verbosity",
        ):
            assert param in OPENAI_CHAT_CREATE_PARAMS
