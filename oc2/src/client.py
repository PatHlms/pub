"""
Interactive REPL for oc2.

Commands
--------
  /help                   Show this help
  /provider <name>        Switch provider  (openai | gemini)
  /model <name>           Switch model
  /file <path>            Attach file contents to next message
  /clear                  Clear conversation history
  /quit  /exit            Exit
"""

import logging
import os
import sys

from .providers import PROVIDER_REGISTRY
from .providers.base import Provider

log = logging.getLogger(__name__)

_HELP = """\
Commands:
  /help                  Show this help
  /provider <name>       Switch provider  (openai | gemini)
  /model <name>          Switch model
  /file <path>           Attach file contents to next message
  /clear                 Clear conversation history
  /quit  /exit           Exit
"""


class Client:

    def __init__(self, settings: dict) -> None:
        self._settings = settings
        self._system: str = settings.get("system", "You are a helpful coding assistant.")
        self._history_limit: int = settings.get("history_limit", 20)
        self._history: list[dict] = []
        self._pending_files: list[str] = []   # paths attached via /file

        provider_name = settings.get("provider", "openai")
        self._provider: Provider = self._build_provider(provider_name)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> None:
        print(f"oc2  •  {self._provider.name}/{self._provider.model}")
        print('Type /help for commands, /quit to exit.\n')

        while True:
            try:
                user_input = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not user_input:
                continue

            if user_input.startswith("/"):
                if self._handle_command(user_input):
                    break
                continue

            self._chat(user_input)

    # ------------------------------------------------------------------
    # Command handling
    # ------------------------------------------------------------------

    def _handle_command(self, line: str) -> bool:
        """Return True if the client should exit."""
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/quit", "/exit"):
            return True

        if cmd == "/help":
            print(_HELP)

        elif cmd == "/clear":
            self._history.clear()
            self._pending_files.clear()
            print("History cleared.")

        elif cmd == "/provider":
            if not arg:
                print(f"Current provider: {self._provider.name}")
                print(f"Available: {', '.join(PROVIDER_REGISTRY)}")
            else:
                self._switch_provider(arg)

        elif cmd == "/model":
            if not arg:
                print(f"Current model: {self._provider.model}")
            else:
                self._provider.model = arg
                print(f"Model set to {arg}.")

        elif cmd == "/file":
            if not arg:
                print("Usage: /file <path>")
            else:
                self._attach_file(arg)

        else:
            print(f"Unknown command: {cmd}  (type /help)")

        return False

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def _chat(self, user_text: str) -> None:
        content = self._build_content(user_text)
        self._history.append({"role": "user", "content": content})
        self._pending_files.clear()

        messages = self._history[-self._history_limit:]

        print(f"\n{self._provider.name}> ", end="", flush=True)
        collected: list[str] = []
        try:
            for token in self._provider.chat_stream(messages, system=self._system):
                print(token, end="", flush=True)
                collected.append(token)
        except Exception as exc:
            log.error("Provider error: %s", exc)
            print(f"\n[error: {exc}]")
            # Remove the message we just added so history stays consistent
            self._history.pop()
            return

        print("\n")
        assistant_text = "".join(collected)
        self._history.append({"role": "assistant", "content": assistant_text})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_content(self, user_text: str) -> str:
        if not self._pending_files:
            return user_text
        parts = []
        for path, body in self._pending_files:
            parts.append(f"<file path=\"{path}\">\n{body}\n</file>")
        parts.append(user_text)
        return "\n\n".join(parts)

    def _attach_file(self, path: str) -> None:
        expanded = os.path.expanduser(path)
        try:
            with open(expanded, "r", encoding="utf-8", errors="replace") as fh:
                body = fh.read()
            self._pending_files.append((path, body))
            lines = body.count("\n") + 1
            print(f"Attached {path}  ({lines} lines).")
        except OSError as exc:
            print(f"Cannot read file: {exc}")

    def _switch_provider(self, name: str) -> None:
        if name not in PROVIDER_REGISTRY:
            print(f"Unknown provider {name!r}. Available: {', '.join(PROVIDER_REGISTRY)}")
            return
        try:
            self._provider = self._build_provider(name)
            print(f"Switched to {self._provider.name}/{self._provider.model}.")
        except KeyError as exc:
            print(f"Missing environment variable for {name}: {exc}")

    def _build_provider(self, name: str) -> Provider:
        cls = PROVIDER_REGISTRY[name]
        cfg = self._settings.get(name, {})
        return cls(cfg)
