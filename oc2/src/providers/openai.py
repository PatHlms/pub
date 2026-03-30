"""
OpenAI provider — raw HTTPS, no third-party packages.

API reference: https://platform.openai.com/docs/api-reference/chat
Streaming:     SSE, each event is  data: <json>  terminated by  data: [DONE]
"""

import http.client
import json
import logging
import os
import ssl
from typing import Iterator

from .base import Provider

log = logging.getLogger(__name__)

_HOST = "api.openai.com"
_PATH = "/v1/chat/completions"


class OpenAIProvider(Provider):

    name = "openai"

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._model: str = config.get("model", "gpt-4o")
        self._max_tokens: int = config.get("max_tokens", 4096)
        self._api_key: str = os.environ["OPENAI_API_KEY"]
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
        payload_messages = []
        if system:
            payload_messages.append({"role": "system", "content": system})
        payload_messages.extend(messages)

        payload = json.dumps({
            "model": self._model,
            "messages": payload_messages,
            "max_tokens": self._max_tokens,
            "stream": True,
        }).encode()

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "Content-Length": str(len(payload)),
        }

        conn = http.client.HTTPSConnection(_HOST, context=self._ssl_ctx)
        try:
            conn.request("POST", _PATH, body=payload, headers=headers)
            resp = conn.getresponse()

            if resp.status != 200:
                body = resp.read().decode(errors="replace")
                raise RuntimeError(
                    f"OpenAI HTTP {resp.status}: {body}"
                )

            yield from self._parse_sse(resp)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

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
            delta = chunk.get("choices", [{}])[0].get("delta", {})
            text = delta.get("content")
            if text:
                yield text
