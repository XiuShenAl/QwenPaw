# -*- coding: utf-8 -*-
from __future__ import annotations

import json

from qwenpaw.migrate.openclaw._json5 import _strip_json5_features, parse_json5


class TestStripJson5Features:
    def test_single_line_comment_removal(self):
        text = '{"key": "value"} // this is a comment'
        result = _strip_json5_features(text)
        assert json.loads(result) == {"key": "value"}

    def test_block_comment_removal(self):
        text = '{"key": /* inline comment */ "value"}'
        result = _strip_json5_features(text)
        assert json.loads(result) == {"key": "value"}

    def test_trailing_comma_in_object(self):
        text = '{"a": 1, "b": 2,}'
        result = _strip_json5_features(text)
        assert json.loads(result) == {"a": 1, "b": 2}

    def test_trailing_comma_in_array(self):
        text = '{"items": [1, 2, 3,]}'
        result = _strip_json5_features(text)
        assert json.loads(result) == {"items": [1, 2, 3]}

    def test_comments_inside_strings_preserved(self):
        text = '{"url": "http://example.com", "note": "/* not a comment */"}'
        result = _strip_json5_features(text)
        parsed = json.loads(result)
        assert parsed["url"] == "http://example.com"
        assert parsed["note"] == "/* not a comment */"

    def test_complex_mixed_case(self):
        text = """\
{
  // top-level comment
  "url": "http://example.com/path",
  "items": [
    "a", /* inline */ "b",
  ],
  "debug": true, // trailing
}"""
        result = _strip_json5_features(text)
        parsed = json.loads(result)
        assert parsed == {
            "url": "http://example.com/path",
            "items": ["a", "b"],
            "debug": True,
        }


class TestParseJson5:
    def test_parses_plain_json(self):
        assert parse_json5('{"x": 1}') == {"x": 1}

    def test_parses_json5_with_comments_and_trailing_commas(self):
        text = '{"a": 1, // comment\n"b": 2,}'
        result = parse_json5(text)
        assert result == {"a": 1, "b": 2}
