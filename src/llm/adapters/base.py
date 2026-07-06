from abc import ABC, abstractmethod
from typing import Any, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class BaseLLMAdapter(ABC):
    """Minimal provider-agnostic interface for LLM calls.

    Kept intentionally small (no tool-calling, streaming, or observability
    hooks) until a concrete use case needs them.
    """

    @abstractmethod
    def complete(self, messages: list[dict[str, Any]]) -> str:
        """Plain chat completion, returns the raw text response."""
        ...

    @abstractmethod
    def reason(self, messages: list[dict[str, Any]], schema: Type[T]) -> T:
        """Chat completion constrained to a structured Pydantic schema."""
        ...
