import json
import logging
import time
from typing import Any, Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from llm.adapters.base import BaseLLMAdapter

T = TypeVar("T", bound=BaseModel)

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BASE_DELAY_S = 1.0

class OpenAIAdapter(BaseLLMAdapter):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def complete(self, messages: list[dict[str, Any]], reasoning_effort: str | None = None) -> str:
        kwargs: dict[str, Any] = {}
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            **kwargs,
        )
        return response.choices[0].message.content or ""

    def reason(self, messages: list[dict[str, Any]], schema: Type[T], reasoning_effort: str | None = None) -> T:
        last_error: Exception | None = None
        kwargs: dict[str, Any] = {}
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": schema.__name__,
                            "schema": schema.model_json_schema(),
                            "strict": True,
                        },
                    },
                    **kwargs,
                )
                content = response.choices[0].message.content or ""
                parsed = json.loads(content)
                return schema.model_validate(parsed)
            except (json.JSONDecodeError, ValidationError) as exc:
                logger.warning(
                    "Structured output parse failure for %s (attempt %d/%d): %s",
                    schema.__name__,
                    attempt,
                    _MAX_RETRIES,
                    exc,
                )
                last_error = exc
            except Exception as exc:
                logger.warning(
                    "OpenAI API error (attempt %d/%d): %s", attempt, _MAX_RETRIES, exc
                )
                last_error = exc

            if attempt < _MAX_RETRIES:
                time.sleep(_BASE_DELAY_S * (2 ** (attempt - 1)))

        raise ValueError(
            f"Failed to get valid structured output for {schema.__name__} "
            f"after {_MAX_RETRIES} attempts"
        ) from last_error
