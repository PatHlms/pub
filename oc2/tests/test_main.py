"""
Unit tests for top-level helpers in main.py

Run with:  pytest tests/ -v
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

# Import the helpers directly from main
import importlib.util, types

_spec = importlib.util.spec_from_file_location(
    "oc2_main",
    os.path.join(os.path.dirname(__file__), "..", "main.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_load_env = _mod._load_env
_load_settings = _mod._load_settings


# ---------------------------------------------------------------------------
# _load_env
# ---------------------------------------------------------------------------

class TestLoadEnv:
    def _write_env(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False)
        f.write(content)
        f.close()
        return f.name

    def test_loads_simple_key_value(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("MYKEY=myvalue\n")
        monkeypatch.delenv("MYKEY", raising=False)
        _load_env(str(env_file))
        assert os.environ.get("MYKEY") == "myvalue"

    def test_strips_double_quotes(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text('QUOTED="hello world"\n')
        monkeypatch.delenv("QUOTED", raising=False)
        _load_env(str(env_file))
        assert os.environ.get("QUOTED") == "hello world"

    def test_strips_single_quotes(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("SQUOTE='value'\n")
        monkeypatch.delenv("SQUOTE", raising=False)
        _load_env(str(env_file))
        assert os.environ.get("SQUOTE") == "value"

    def test_skips_comment_lines(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# This is a comment\nREAL=yes\n")
        monkeypatch.delenv("REAL", raising=False)
        _load_env(str(env_file))
        assert os.environ.get("REAL") == "yes"

    def test_skips_blank_lines(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("\n\nBLANK=1\n\n")
        monkeypatch.delenv("BLANK", raising=False)
        _load_env(str(env_file))
        assert os.environ.get("BLANK") == "1"

    def test_does_not_override_existing_env(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("PRESET=from_file\n")
        monkeypatch.setenv("PRESET", "existing")
        _load_env(str(env_file))
        assert os.environ.get("PRESET") == "existing"

    def test_missing_file_does_not_raise(self):
        _load_env("/no/such/file/.env")  # must not raise

    def test_value_with_equals_sign(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=a=b=c\n")
        monkeypatch.delenv("KEY", raising=False)
        _load_env(str(env_file))
        # partition("=") keeps everything after the first "="
        assert os.environ.get("KEY") == "a=b=c"

    def test_multiple_keys(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("A=1\nB=2\nC=3\n")
        for k in ("A", "B", "C"):
            monkeypatch.delenv(k, raising=False)
        _load_env(str(env_file))
        assert os.environ.get("A") == "1"
        assert os.environ.get("B") == "2"
        assert os.environ.get("C") == "3"


# ---------------------------------------------------------------------------
# _load_settings
# ---------------------------------------------------------------------------

class TestLoadSettings:
    def test_loads_valid_json(self, tmp_path):
        cfg = tmp_path / "settings.json"
        data = {"provider": "openai", "openai": {"model": "gpt-4o"}}
        cfg.write_text(json.dumps(data))
        result = _load_settings(str(cfg))
        assert result == data

    def test_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            _load_settings("/no/such/settings.json")

    def test_raises_on_invalid_json(self, tmp_path):
        cfg = tmp_path / "bad.json"
        cfg.write_text("{ not valid json }")
        with pytest.raises(json.JSONDecodeError):
            _load_settings(str(cfg))

    def test_empty_object_is_valid(self, tmp_path):
        cfg = tmp_path / "empty.json"
        cfg.write_text("{}")
        assert _load_settings(str(cfg)) == {}

    def test_nested_structure_preserved(self, tmp_path):
        data = {
            "provider": "gemini",
            "gemini": {"model": "gemini-2.0-flash", "max_tokens": 4096},
            "history_limit": 20,
        }
        cfg = tmp_path / "settings.json"
        cfg.write_text(json.dumps(data))
        result = _load_settings(str(cfg))
        assert result["gemini"]["max_tokens"] == 4096
