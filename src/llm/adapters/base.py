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
    def complete(self, messages: list[dict[str, Any]], reasoning_effort: str | None = None) -> str:
        """Plain chat completion, returns the raw text response.

        `reasoning_effort` ("low"/"medium"/"high") is forwarded to the
        provider only when set and supported — left `None` (provider
        default) unless a caller has a specific reason to tune it, e.g. a
        small/cheap task that doesn't need deep reasoning.
        """
        ...

    @abstractmethod
    def reason(self, messages: list[dict[str, Any]], schema: Type[T], reasoning_effort: str | None = None) -> T:
        """Chat completion constrained to a structured Pydantic schema.

        See `complete()` for `reasoning_effort` semantics.
        """
        ...
