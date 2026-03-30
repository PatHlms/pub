"""
Unit tests for src/providers/gemini.py

Run with:  pytest tests/ -v
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch

from src.providers.gemini import GeminiProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sse_response(*events) -> MagicMock:
    lines = []
    for ev in events:
        if ev == "[DONE]":
            lines.append(b"data: [DONE]\n")
        else:
            lines.append(f"data: {json.dumps(ev)}\n".encode())
        lines.append(b"\n")
    lines.append(b"")

    resp = MagicMock()
    resp.status = 200
    resp.readline.side_effect = lines
    return resp


def _gemini_chunk(*texts) -> dict:
    return {
        "candidates": [{
            "content": {
                "role": "model",
                "parts": [{"text": t} for t in texts],
            }
        }]
    }


def _make_provider(model: str = "gemini-2.0-flash") -> GeminiProvider:
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
        return GeminiProvider({"model": model, "max_tokens": 100})


# ---------------------------------------------------------------------------
# _to_gemini_contents
# ---------------------------------------------------------------------------

class TestToGeminiContents:
    def test_user_role_preserved(self):
        msgs = [{"role": "user", "content": "hello"}]
        result = GeminiProvider._to_gemini_contents(msgs)
        assert result == [{"role": "user", "parts": [{"text": "hello"}]}]

    def test_assistant_becomes_model(self):
        msgs = [{"role": "assistant", "content": "hi back"}]
        result = GeminiProvider._to_gemini_contents(msgs)
        assert result == [{"role": "model", "parts": [{"text": "hi back"}]}]

    def test_system_messages_skipped(self):
        msgs = [
            {"role": "system", "content": "be concise"},
            {"role": "user", "content": "question"},
        ]
        result = GeminiProvider._to_gemini_contents(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_multi_turn_conversation(self):
        msgs = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ]
        result = GeminiProvider._to_gemini_contents(msgs)
        assert [r["role"] for r in result] == ["user", "model", "user"]

    def test_empty_messages(self):
        assert GeminiProvider._to_gemini_contents([]) == []


# ---------------------------------------------------------------------------
# _parse_sse
# ---------------------------------------------------------------------------

class TestParseSse:
    def test_yields_text_parts(self):
        resp = _make_sse_response(_gemini_chunk("Hello"), "[DONE]")
        tokens = list(GeminiProvider._parse_sse(resp))
        assert tokens == ["Hello"]

    def test_multiple_parts_in_one_chunk(self):
        resp = _make_sse_response(_gemini_chunk("foo", "bar"), "[DONE]")
        tokens = list(GeminiProvider._parse_sse(resp))
        assert tokens == ["foo", "bar"]

    def test_multiple_chunks(self):
        resp = _make_sse_response(
            _gemini_chunk("one"),
            _gemini_chunk("two"),
            "[DONE]",
        )
        tokens = list(GeminiProvider._parse_sse(resp))
        assert tokens == ["one", "two"]

    def test_skips_empty_candidates(self):
        resp = _make_sse_response(
            {"candidates": []},
            _gemini_chunk("real"),
            "[DONE]",
        )
        tokens = list(GeminiProvider._parse_sse(resp))
        assert tokens == ["real"]

    def test_skips_parts_without_text(self):
        chunk = {"candidates": [{"content": {"parts": [{"inline_data": "..."}]}}]}
        resp = _make_sse_response(chunk, _gemini_chunk("ok"), "[DONE]")
        tokens = list(GeminiProvider._parse_sse(resp))
        assert tokens == ["ok"]

    def test_skips_malformed_json(self):
        lines = [
            b"data: not-json\n",
            b"\n",
            b'data: {"candidates":[{"content":{"parts":[{"text":"good"}]}}]}\n',
            b"\n",
            b"data: [DONE]\n",
            b"",
        ]
        resp = MagicMock()
        resp.readline.side_effect = lines
        tokens = list(GeminiProvider._parse_sse(resp))
        assert tokens == ["good"]

    def test_skips_non_data_lines(self):
        lines = [
            b": ping\n",
            b"\n",
            b'data: {"candidates":[{"content":{"parts":[{"text":"hi"}]}}]}\n',
            b"\n",
            b"data: [DONE]\n",
            b"",
        ]
        resp = MagicMock()
        resp.readline.side_effect = lines
        tokens = list(GeminiProvider._parse_sse(resp))
        assert tokens == ["hi"]


# ---------------------------------------------------------------------------
# model property
# ---------------------------------------------------------------------------

class TestModel:
    def test_default_model(self):
        p = _make_provider("gemini-2.0-flash")
        assert p.model == "gemini-2.0-flash"

    def test_set_model(self):
        p = _make_provider()
        p.model = "gemini-1.5-pro"
        assert p.model == "gemini-1.5-pro"

    def test_name(self):
        p = _make_provider()
        assert p.name == "gemini"


# ---------------------------------------------------------------------------
# chat_stream
# ---------------------------------------------------------------------------

class TestChatStream:
    def _make_conn(self, resp):
        conn = MagicMock()
        conn.getresponse.return_value = resp
        return conn

    def test_yields_tokens_on_success(self):
        resp = _make_sse_response(_gemini_chunk("Sure"), "[DONE]")
        conn = self._make_conn(resp)

        p = _make_provider()
        with patch("http.client.HTTPSConnection", return_value=conn):
            tokens = list(p.chat_stream([{"role": "user", "content": "hi"}]))

        assert tokens == ["Sure"]

    def test_system_instruction_included(self):
        resp = _make_sse_response("[DONE]")
        conn = self._make_conn(resp)

        p = _make_provider()
        with patch("http.client.HTTPSConnection", return_value=conn):
            list(p.chat_stream(
                [{"role": "user", "content": "q"}],
                system="Be precise.",
            ))

        _, kwargs = conn.request.call_args
        body = json.loads(kwargs["body"])
        assert body["systemInstruction"] == {"parts": [{"text": "Be precise."}]}

    def test_no_system_instruction_when_none(self):
        resp = _make_sse_response("[DONE]")
        conn = self._make_conn(resp)

        p = _make_provider()
        with patch("http.client.HTTPSConnection", return_value=conn):
            list(p.chat_stream([{"role": "user", "content": "q"}], system=None))

        _, kwargs = conn.request.call_args
        body = json.loads(kwargs["body"])
        assert "systemInstruction" not in body

    def test_api_key_in_url(self):
        resp = _make_sse_response("[DONE]")
        conn = self._make_conn(resp)

        p = _make_provider()
        with patch("http.client.HTTPSConnection", return_value=conn):
            list(p.chat_stream([{"role": "user", "content": "x"}]))

        path = conn.request.call_args[0][1]
        assert "key=test-key" in path

    def test_model_in_url(self):
        resp = _make_sse_response("[DONE]")
        conn = self._make_conn(resp)

        p = _make_provider("gemini-1.5-pro")
        with patch("http.client.HTTPSConnection", return_value=conn):
            list(p.chat_stream([{"role": "user", "content": "x"}]))

        path = conn.request.call_args[0][1]
        assert "gemini-1.5-pro" in path

    def test_raises_on_http_error(self):
        resp = MagicMock()
        resp.status = 403
        resp.read.return_value = b'{"error": "forbidden"}'
        conn = self._make_conn(resp)

        p = _make_provider()
        with patch("http.client.HTTPSConnection", return_value=conn):
            with pytest.raises(RuntimeError, match="403"):
                list(p.chat_stream([{"role": "user", "content": "x"}]))

    def test_connection_closed_after_use(self):
        resp = _make_sse_response("[DONE]")
        conn = self._make_conn(resp)

        p = _make_provider()
        with patch("http.client.HTTPSConnection", return_value=conn):
            list(p.chat_stream([{"role": "user", "content": "x"}]))

        conn.close.assert_called_once()
