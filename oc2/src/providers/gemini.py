"""
Google Gemini provider — raw HTTPS, no third-party packages.

API reference: https://ai.google.dev/api/generate-content
Streaming:     SSE via ?alt=sse, each event is  data: <json>
"""

import http.client
import json
import logging
import os
import ssl
from typing import Iterator

from .base import Provider

log = logging.getLogger(__name__)

_HOST = "generativelanguage.googleapis.com"


class GeminiProvider(Provider):

    name = "gemini"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._model: str = config.get("model", "gemini-2.0-flash")
        self._max_tokens: int = config.get("max_tokens", 4096)
        self._api_key: str = os.environ["GEMINI_API_KEY"]
        self._ssl_ctx = ssl.create_default_context()

    # ------------------------------------------------------------------
    # Provider interface
    # ------------------------------------------------------------------

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str) -> None:
        self._model = value

    def chat_stream(
        self,
        messages: list[dict],
        system: str | None = None,
    ) -> Iterator[str]:
        path = (
            f"/v1beta/models/{self._model}"
            f":streamGenerateContent?alt=sse&key={self._api_key}"
        )

        payload_dict: dict = {
            "contents": self._to_gemini_contents(messages),
            "generationConfig": {"maxOutputTokens": self._max_tokens},
        }
        if system:
            payload_dict["systemInstruction"] = {
                "parts": [{"text": system}]
            }

        payload = json.dumps(payload_dict).encode()

        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(payload)),
        }

        conn = http.client.HTTPSConnection(_HOST, context=self._ssl_ctx)
        try:
            conn.request("POST", path, body=payload, headers=headers)
            resp = conn.getresponse()

            if resp.status != 200:
                body = resp.read().decode(errors="replace")
                raise RuntimeError(
                    f"Gemini HTTP {resp.status}: {body}"
                )

            yield from self._parse_sse(resp)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _to_gemini_contents(messages: list[dict]) -> list[dict]:
        """Convert OpenAI-format messages to Gemini contents array."""
        contents = []
        for msg in messages:
            role = msg["role"]
            if role == "system":
                # System messages are passed via systemInstruction; skip here
                continue
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({
                "role": gemini_role,
                "parts": [{"text": msg["content"]}],
            })
        return contents

    @staticmethod
    def _parse_sse(resp) -> Iterator[str]:
        while True:
            raw = resp.readline()
            if not raw:
                break
            line = raw.decode("utf-8").rstrip("\r\n")
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                log.debug("Unparseable SSE chunk: %r", data)
                continue
            candidates = chunk.get("candidates", [])
            if not candidates:
                continue
            parts = candidates[0].get("content", {}).get("parts", [])
            for part in parts:
                text = part.get("text")
                if text:
                    yield text
