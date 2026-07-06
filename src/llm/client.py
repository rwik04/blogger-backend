from typing import Any, Type, TypeVar

from pydantic import BaseModel

from llm.adapters.base import BaseLLMAdapter

T = TypeVar("T", bound=BaseModel)


def create_adapter(provider: str, api_key: str, model: str) -> BaseLLMAdapter:
    """Factory function to create the appropriate LLM adapter.

    Only "openai" is implemented for now; add a branch here (mirroring
    meridian's worker/llm/client.py) as new providers are actually needed.
    """
    provider = provider.lower()

    if provider == "openai":
        from llm.adapters.openai import OpenAIAdapter

        return OpenAIAdapter(api_key=api_key, model=model)

    raise ValueError(f"Unknown LLM provider: {provider}")


class LLMClient:
    def __init__(self, provider: str, api_key: str, model: str) -> None:
        self._adapter = create_adapter(provider, api_key, model)

    @property
    def adapter(self) -> BaseLLMAdapter:
        return self._adapter

    def complete(self, messages: list[dict[str, Any]]) -> str:
        return self._adapter.complete(messages)

    def reason(self, messages: list[dict[str, Any]], schema: Type[T]) -> T:
        return self._adapter.reason(messages, schema)
