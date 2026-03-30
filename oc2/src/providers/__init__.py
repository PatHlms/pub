from .gemini import GeminiProvider
from .openai import OpenAIProvider

PROVIDER_REGISTRY: dict = {
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
}
