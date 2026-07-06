"""Table definitions for the blog pipeline, registered on the shared
`db.schema.metadata`. Mirrors `migrations/0001_researcher.sql` — that file is
the source of truth for what's actually applied to the database; these
`Table` objects are for querying/inserting via SQLAlchemy Core from
`db.repositories.research_repository`.

`blog_runs` / `agent_events` / `agent_steps` are minimal versions (this repo
had no prior schema for them) — just enough to support the Researcher stage;
expect other stages to extend `agent_steps`/`agent_events` usage, not
redefine them.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    JSON,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    TIMESTAMP,
    func,
)

from db.schema import metadata

blog_runs = Table(
    "blog_runs",
    metadata,
    Column("id", String, primary_key=True),
    Column("topic", Text, nullable=False),
    Column("audience_tag", String, nullable=True),
    Column("status", String, nullable=False, server_default="pending"),
    Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
)

agent_events = Table(
    "agent_events",
    metadata,
    Column("id", String, primary_key=True),
    Column("run_id", String, ForeignKey("blog_runs.id"), nullable=False),
    Column("step", String, nullable=False),
    Column("phase", String, nullable=False),  # started | done | failed
    Column("detail", JSON, nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
)

agent_steps = Table(
    "agent_steps",
    metadata,
    Column("id", String, primary_key=True),
    Column("run_id", String, ForeignKey("blog_runs.id"), nullable=False),
    Column("agent", String, nullable=False),  # e.g. "researcher"
    Column("status", String, nullable=False),
    Column("output", JSON, nullable=True),  # full ResearchBrief JSON — source of truth for replay/debugging
    Column("error", Text, nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
)

research_sources = Table(
    "research_sources",
    metadata,
    Column("id", String, primary_key=True),
    Column("run_id", String, ForeignKey("blog_runs.id"), nullable=False),
    Column("url", Text, nullable=False),
    Column("title", Text, nullable=True),
    Column("domain", String, nullable=True),
    Column("retrieved_at", TIMESTAMP(timezone=True), server_default=func.now()),
)

research_claims = Table(
    "research_claims",
    metadata,
    Column("id", String, primary_key=True),
    Column("run_id", String, ForeignKey("blog_runs.id"), nullable=False),
    Column("claim_text", Text, nullable=False),
    Column("confidence", String, nullable=False),
    Column("contradicted", Boolean, server_default="false"),
)

research_claim_sources = Table(
    "research_claim_sources",
    metadata,
    Column("claim_id", String, ForeignKey("research_claims.id"), nullable=False),
    Column("source_id", String, ForeignKey("research_sources.id"), nullable=False),
    PrimaryKeyConstraint("claim_id", "source_id"),
)
