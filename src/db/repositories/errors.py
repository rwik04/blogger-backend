"""Shared not-found exceptions for the per-agent repositories.

Every downstream agent repository (`StrategistRepository`, `WriterRepository`,
`FinisherRepository`) needs to distinguish "the run doesn't exist at all"
(`RunNotFoundError`, in `db.repositories.base`) from "the run exists but a
specific upstream stage hasn't completed for it yet" — the latter was
previously redefined identically (same name, same docstring shape) in each
of those three modules. Consolidated here so callers (notably the API layer)
can catch one exception type per stage regardless of which repository raised
it, instead of registering a handler per duplicate class.
"""

from __future__ import annotations


class AgentOutputNotFoundError(Exception):
    """Raised when a `run_id` has no persisted `agent_steps` row for a given
    upstream agent — i.e. that agent hasn't successfully completed for this
    run yet. Subclassed per agent purely for clearer error messages/`isinstance`
    checks; callers that only care about "which HTTP status" can catch the
    base class.
    """


class ResearchBriefNotFoundError(AgentOutputNotFoundError):
    """Raised when a `run_id` has no persisted `agent_steps` row for the Researcher —
    i.e. `research`/`agents.researcher` hasn't successfully completed for this run yet.
    """


class StrategistOutputNotFoundError(AgentOutputNotFoundError):
    """Raised when a `run_id` has no persisted `agent_steps` row for the Strategist —
    i.e. `strategize`/`agents.strategist` hasn't successfully completed for this run yet.
    """


class WriterOutputNotFoundError(AgentOutputNotFoundError):
    """Raised when a `run_id` has no persisted `agent_steps` row for the Writer —
    i.e. `write`/`agents.writer` hasn't successfully completed for this run yet.
    """


class FinisherOutputNotFoundError(AgentOutputNotFoundError):
    """Raised when a `run_id` has no persisted `agent_steps` row for the Finisher —
    i.e. `finish`/`agents.finisher` hasn't successfully completed for this run yet.
    """


class SectionNotFoundError(Exception):
    """Raised when a requested `section_id` doesn't exist in a run's latest draft."""


class TopicBatchNotFoundError(Exception):
    """Raised when a `batch_id` has no `topic_batches` row."""


class TopicNotFoundError(Exception):
    """Raised when a `topic_id` has no `topics` row."""
