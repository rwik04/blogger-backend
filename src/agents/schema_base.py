"""Shared base for every pydantic model passed as an OpenAI structured-output
schema across agents (`LLMClient.reason(messages, schema)`).

OpenAI's strict JSON-schema mode requires `additionalProperties: false` on
every object in the schema tree — pydantic only emits that when
`extra="forbid"` is set, and it must be set on every nested model too, not
just the top-level one. Kept at the `agents/` level (not inside any single
agent's package) so every agent's structured-output schemas — Researcher,
Strategist, and whatever comes next — share one definition instead of
duplicating it per agent.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
