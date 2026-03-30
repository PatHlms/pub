"""
Abstract base class for AI provider backends.

All providers accept messages in OpenAI format:
  [{"role": "user"|"assistant"|"system", "content": "..."}]

and yield response text tokens via chat_stream().
"""

from abc import ABC, abstractmethod
from typing import Iterator


class Provider(ABC):

    def __init__(self, config: dict) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------

    @abstractmethod
    def chat_stream(
        self,
        messages: list[dict],
        system: str | None = None,
    ) -> Iterator[str]:
        """Yield response text tokens as they arrive."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier, e.g. 'openai' or 'gemini'."""
        ...

    @property
    @abstractmethod
    def model(self) -> str:
        """Currently active model name."""
        ...

    @model.setter
    @abstractmethod
    def model(self, value: str) -> None: ...
