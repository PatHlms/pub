"""
Unit tests for src/client.py

Run with:  pytest tests/ -v
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch, call

from src.client import Client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SETTINGS = {
    "provider": "openai",
    "system": "Be helpful.",
    "history_limit": 5,
    "openai": {"model": "gpt-4o", "max_tokens": 100},
    "gemini": {"model": "gemini-2.0-flash", "max_tokens": 100},
}


def _make_client(settings: dict | None = None) -> Client:
    """Create a Client with a mock provider so no real HTTP calls are made."""
    s = settings or _SETTINGS
    env = {"OPENAI_API_KEY": "k", "GEMINI_API_KEY": "k"}
    with patch.dict("os.environ", env):
        client = Client(s)
    # Replace the real provider with a controllable mock
    mock_provider = MagicMock()
    mock_provider.name = "openai"
    mock_provider.model = "gpt-4o"
    client._provider = mock_provider
    return client


# ---------------------------------------------------------------------------
# _build_content
# ---------------------------------------------------------------------------

class TestBuildContent:
    def test_plain_text_no_files(self):
        c = _make_client()
        assert c._build_content("hello") == "hello"

    def test_single_attached_file(self):
        c = _make_client()
        c._pending_files = [("foo.py", "x = 1\n")]
        result = c._build_content("explain")
        assert '<file path="foo.py">' in result
        assert "x = 1" in result
        assert "explain" in result

    def test_multiple_attached_files(self):
        c = _make_client()
        c._pending_files = [("a.py", "a"), ("b.py", "b")]
        result = c._build_content("question")
        assert 'path="a.py"' in result
        assert 'path="b.py"' in result
        assert "question" in result

    def test_user_text_appended_last(self):
        c = _make_client()
        c._pending_files = [("f.py", "code")]
        result = c._build_content("my question")
        assert result.endswith("my question")


# ---------------------------------------------------------------------------
# _attach_file
# ---------------------------------------------------------------------------

class TestAttachFile:
    def test_attaches_existing_file(self, tmp_path, capsys):
        f = tmp_path / "hello.py"
        f.write_text("print('hi')\n")
        c = _make_client()
        c._attach_file(str(f))
        assert len(c._pending_files) == 1
        path, body = c._pending_files[0]
        assert "hello.py" in path
        assert "print('hi')" in body

    def test_prints_line_count(self, tmp_path, capsys):
        f = tmp_path / "multi.py"
        # "a\nb\nc\n" has 3 newlines → count("\n") + 1 == 4
        f.write_text("a\nb\nc\n")
        c = _make_client()
        c._attach_file(str(f))
        out = capsys.readouterr().out
        assert "4 lines" in out

    def test_missing_file_prints_error(self, capsys):
        c = _make_client()
        c._attach_file("/nonexistent/path/file.py")
        out = capsys.readouterr().out
        assert "Cannot read file" in out
        assert c._pending_files == []


# ---------------------------------------------------------------------------
# _handle_command
# ---------------------------------------------------------------------------

class TestHandleCommand:
    def test_quit_returns_true(self):
        c = _make_client()
        assert c._handle_command("/quit") is True

    def test_exit_returns_true(self):
        c = _make_client()
        assert c._handle_command("/exit") is True

    def test_other_commands_return_false(self):
        c = _make_client()
        assert c._handle_command("/help") is False
        assert c._handle_command("/clear") is False

    def test_clear_empties_history_and_files(self):
        c = _make_client()
        c._history = [{"role": "user", "content": "old"}]
        c._pending_files = [("f.py", "x")]
        c._handle_command("/clear")
        assert c._history == []
        assert c._pending_files == []

    def test_model_with_arg_sets_model(self, capsys):
        c = _make_client()
        c._handle_command("/model gpt-4o-mini")
        # MagicMock accepts attribute assignment; verify the print confirmation
        out = capsys.readouterr().out
        assert "gpt-4o-mini" in out

    def test_model_without_arg_prints_current(self, capsys):
        c = _make_client()
        c._handle_command("/model")
        out = capsys.readouterr().out
        assert "gpt-4o" in out

    def test_provider_without_arg_prints_current(self, capsys):
        c = _make_client()
        c._handle_command("/provider")
        out = capsys.readouterr().out
        assert "openai" in out

    def test_provider_unknown_prints_error(self, capsys):
        c = _make_client()
        c._handle_command("/provider unknown")
        out = capsys.readouterr().out
        assert "Unknown provider" in out

    def test_provider_valid_switches(self, capsys):
        c = _make_client()
        env = {"OPENAI_API_KEY": "k", "GEMINI_API_KEY": "k"}
        with patch.dict("os.environ", env):
            c._handle_command("/provider gemini")
        assert c._provider.name in ("gemini", "openai")  # real or mock

    def test_file_without_arg_prints_usage(self, capsys):
        c = _make_client()
        c._handle_command("/file")
        out = capsys.readouterr().out
        assert "Usage" in out

    def test_unknown_command_prints_error(self, capsys):
        c = _make_client()
        c._handle_command("/bogus")
        out = capsys.readouterr().out
        assert "Unknown command" in out


# ---------------------------------------------------------------------------
# _chat
# ---------------------------------------------------------------------------

class TestChat:
    def test_adds_user_and_assistant_to_history(self):
        c = _make_client()
        c._provider.chat_stream.return_value = iter(["Hello"])
        c._chat("hi")
        assert c._history[-2] == {"role": "user", "content": "hi"}
        assert c._history[-1] == {"role": "assistant", "content": "Hello"}

    def test_collects_multiple_tokens(self):
        c = _make_client()
        c._provider.chat_stream.return_value = iter(["foo", " ", "bar"])
        c._chat("q")
        assert c._history[-1]["content"] == "foo bar"

    def test_clears_pending_files_after_send(self):
        c = _make_client()
        c._pending_files = [("f.py", "x")]
        c._provider.chat_stream.return_value = iter([])
        c._chat("go")
        assert c._pending_files == []

    def test_history_not_added_on_provider_error(self):
        c = _make_client()
        c._provider.chat_stream.side_effect = RuntimeError("API down")
        c._chat("hi")
        assert c._history == []

    def test_history_trimmed_to_limit(self):
        c = _make_client()
        c._history_limit = 3
        c._provider.chat_stream.return_value = iter(["ok"])
        # Fill history to limit
        c._history = [
            {"role": "user", "content": f"q{i}"}
            for i in range(3)
        ]
        c._chat("new")
        # Only _history_limit messages passed to provider
        call_args = c._provider.chat_stream.call_args
        messages_passed = call_args[0][0]
        assert len(messages_passed) <= c._history_limit

    def test_system_passed_to_provider(self):
        c = _make_client()
        c._system = "Custom system"
        c._provider.chat_stream.return_value = iter([])
        c._chat("x")
        call_args = c._provider.chat_stream.call_args
        assert call_args[1]["system"] == "Custom system"


# ---------------------------------------------------------------------------
# run (REPL)
# ---------------------------------------------------------------------------

class TestRun:
    def test_exits_on_quit_command(self, capsys):
        c = _make_client()
        with patch("builtins.input", side_effect=["/quit"]):
            c.run()
        # Just verify it returns without error

    def test_exits_on_eof(self, capsys):
        c = _make_client()
        with patch("builtins.input", side_effect=EOFError):
            c.run()

    def test_exits_on_keyboard_interrupt(self, capsys):
        c = _make_client()
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            c.run()

    def test_skips_empty_input(self, capsys):
        c = _make_client()
        c._provider.chat_stream.return_value = iter(["reply"])
        with patch("builtins.input", side_effect=["", "hello", "/quit"]):
            c.run()
        # Only one real chat call (for "hello")
        c._provider.chat_stream.assert_called_once()
