"""
oc2 — AI coding assistant client.

Connects to OpenAI and Google Gemini via raw HTTPS (no third-party packages).
API keys are read from the environment (or .env file in this directory).

Usage
-----
    python main.py                        # Start interactive session
    python main.py --provider gemini      # Start with Gemini
    python main.py --model gpt-4o-mini    # Override model
    python main.py --config FILE          # Use alternate settings file
    python main.py --verbose              # Enable DEBUG logging
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# .env loader  (stdlib only — no python-dotenv)
# ---------------------------------------------------------------------------

def _load_env(path: str = ".env") -> None:
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                os.environ.setdefault(key, val)
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="oc2",
        description="AI coding assistant — OpenAI and Gemini",
    )
    parser.add_argument(
        "--provider",
        choices=["openai", "gemini"],
        default=None,
        help="Provider to use (overrides config)",
    )
    parser.add_argument(
        "--model",
        default=None,
        metavar="NAME",
        help="Model name (overrides config)",
    )
    parser.add_argument(
        "--config",
        default="config/settings.json",
        metavar="FILE",
        help="Path to settings JSON (default: config/settings.json)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable DEBUG logging",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def _load_settings(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    args = _parse_args()
    _load_env()
    _configure_logging(args.verbose)

    try:
        settings = _load_settings(args.config)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"error: invalid settings JSON — {exc}", file=sys.stderr)
        return 1

    # CLI flags override config
    if args.provider:
        settings["provider"] = args.provider
    if args.model:
        provider_name = settings.get("provider", "openai")
        settings.setdefault(provider_name, {})["model"] = args.model

    from src.client import Client
    try:
        client = Client(settings)
    except KeyError as exc:
        print(f"error: missing environment variable {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    client.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
