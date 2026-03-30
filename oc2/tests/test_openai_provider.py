"""
Unit tests for src/providers/openai.py

Run with:  pytest tests/ -v
"""

import io
import json
import sys
import os

# Ensure project root is on path when run from oc2/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch

from src.providers.openai import OpenAIProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sse_response(*events) -> MagicMock:
    """
    Build a fake HTTPResponse whose readline() returns SSE lines derived from
    *events*.  Each event is either a dict (serialised to data: <json>) or the
    sentinel string "[DONE]".
    """
    lines = []
    for ev in events:
        if ev == "[DONE]":
            lines.append(b"data: [DONE]\n")
        else:
            lines.append(f"data: {json.dumps(ev)}\n".encode())
        lines.append(b"\n")          # blank line between SSE events
    lines.append(b"")                # EOF sentinel

    resp = MagicMock()
    resp.status = 200
    resp.readline.side_effect = lines
    return resp


def _openai_chunk(content: str) -> dict:
    return {
        "choices": [{"delta": {"content": content}, "finish_reason": None}]
    }


def _make_provider(model: str = "gpt-4o") -> OpenAIProvider:
    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
        return OpenAIProvider({"model": model, "max_tokens": 100})


# ---------------------------------------------------------------------------
# _parse_sse
# ---------------------------------------------------------------------------

class TestParseSse:
    def test_yields_content_tokens(self):
        resp = _make_sse_response(
            _openai_chunk("Hello"),
            _openai_chunk(", world"),
            "[DONE]",
        )
        tokens = list(OpenAIProvider._parse_sse(resp))
        assert tokens == ["Hello", ", world"]

    def test_stops_at_done(self):
        resp = _make_sse_response(
            _openai_chunk("first"),
            "[DONE]",
            _openai_chunk("never"),   # after [DONE] — must be ignored
        )
        tokens = list(OpenAIProvider._parse_sse(resp))
        assert tokens == ["first"]

    def test_skips_non_data_lines(self):
        lines = [
            b": keep-alive\n",
            b"\n",
            b'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":null}]}\n',
            b"\n",
            b"data: [DONE]\n",
            b"",
        ]
        resp = MagicMock()
        resp.readline.side_effect = lines
        tokens = list(OpenAIProvider._parse_sse(resp))
        assert tokens == ["hi"]

    def test_skips_empty_content_delta(self):
        resp = _make_sse_response(
            {"choices": [{"delta": {}, "finish_reason": None}]},
            _openai_chunk("real"),
            "[DONE]",
        )
        tokens = list(OpenAIProvider._parse_sse(resp))
        assert tokens == ["real"]

    def test_skips_malformed_json(self):
        lines = [
            b"data: not-json\n",
            b"\n",
            b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":null}]}\n',
            b"\n",
            b"data: [DONE]\n",
            b"",
        ]
        resp = MagicMock()
        resp.readline.side_effect = lines
        tokens = list(OpenAIProvider._parse_sse(resp))
        assert tokens == ["ok"]

    def test_stops_on_eof_without_done(self):
        resp = _make_sse_response(_openai_chunk("only"))
        # _make_sse_response appends b"" at end which readline() returns as EOF
        tokens = list(OpenAIProvider._parse_sse(resp))
        assert tokens == ["only"]

    def test_empty_stream(self):
        resp = MagicMock()
        resp.readline.side_effect = [b"data: [DONE]\n", b""]
        tokens = list(OpenAIProvider._parse_sse(resp))
        assert tokens == []


# ---------------------------------------------------------------------------
# model property
# ---------------------------------------------------------------------------

class TestModel:
    def test_default_model(self):
        p = _make_provider("gpt-4o-mini")
        assert p.model == "gpt-4o-mini"

    def test_set_model(self):
        p = _make_provider()
        p.model = "gpt-3.5-turbo"
        assert p.model == "gpt-3.5-turbo"

    def test_name(self):
        p = _make_provider()
        assert p.name == "openai"


# ---------------------------------------------------------------------------
# chat_stream
# ---------------------------------------------------------------------------

class TestChatStream:
    def _make_conn(self, resp):
        conn = MagicMock()
        conn.getresponse.return_value = resp
        return conn

    def test_yields_tokens_on_success(self):
        resp = _make_sse_response(
            _openai_chunk("The "),
            _openai_chunk("answer"),
            "[DONE]",
        )
        conn = self._make_conn(resp)

        p = _make_provider()
        with patch("http.client.HTTPSConnection", return_value=conn):
            tokens = list(p.chat_stream([{"role": "user", "content": "hi"}]))

        assert tokens == ["The ", "answer"]

    def test_prepends_system_message(self):
        resp = _make_sse_response("[DONE]")
        conn = self._make_conn(resp)

        p = _make_provider()
        with patch("http.client.HTTPSConnection", return_value=conn):
            list(p.chat_stream(
                [{"role": "user", "content": "q"}],
                system="Be concise.",
            ))

        _, kwargs = conn.request.call_args
        body = json.loads(kwargs["body"])
        assert body["messages"][0] == {"role": "system", "content": "Be concise."}
        assert body["messages"][1] == {"role": "user", "content": "q"}

    def test_no_system_message_when_none(self):
        resp = _make_sse_response("[DONE]")
        conn = self._make_conn(resp)

        p = _make_provider()
        with patch("http.client.HTTPSConnection", return_value=conn):
            list(p.chat_stream([{"role": "user", "content": "q"}], system=None))

        _, kwargs = conn.request.call_args
        body = json.loads(kwargs["body"])
        assert all(m["role"] != "system" for m in body["messages"])

    def test_uses_current_model(self):
        resp = _make_sse_response("[DONE]")
        conn = self._make_conn(resp)

        p = _make_provider("gpt-4o-mini")
        with patch("http.client.HTTPSConnection", return_value=conn):
            list(p.chat_stream([{"role": "user", "content": "x"}]))

        _, kwargs = conn.request.call_args
        body = json.loads(kwargs["body"])
        assert body["model"] == "gpt-4o-mini"

    def test_raises_on_http_error(self):
        resp = MagicMock()
        resp.status = 401
        resp.read.return_value = b'{"error": "invalid key"}'
        conn = self._make_conn(resp)

        p = _make_provider()
        with patch("http.client.HTTPSConnection", return_value=conn):
            with pytest.raises(RuntimeError, match="401"):
                list(p.chat_stream([{"role": "user", "content": "x"}]))

    def test_connection_closed_after_use(self):
        resp = _make_sse_response("[DONE]")
        conn = self._make_conn(resp)

        p = _make_provider()
        with patch("http.client.HTTPSConnection", return_value=conn):
            list(p.chat_stream([{"role": "user", "content": "x"}]))

        conn.close.assert_called_once()

    def test_connection_closed_on_error(self):
        resp = MagicMock()
        resp.status = 500
        resp.read.return_value = b"server error"
        conn = self._make_conn(resp)

        p = _make_provider()
        with patch("http.client.HTTPSConnection", return_value=conn):
            with pytest.raises(RuntimeError):
                list(p.chat_stream([{"role": "user", "content": "x"}]))

        conn.close.assert_called_once()
