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
    Float,
    ForeignKey,
    Integer,
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
    Column("topic_id", String, ForeignKey("topics.id"), nullable=True),
    # Checked by `api.supervisor.PipelineSupervisor` at every stage boundary
    # (after research/strategize/write, before starting the next stage) — an
    # in-flight stage always runs to completion, this only stops the chain
    # from auto-advancing to the next one.
    Column("paused", Boolean, nullable=False, server_default="false"),
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

# --- Strategist tables — STRATEGIST.md §4 -----------------------------------

seo_plans = Table(
    "seo_plans",
    metadata,
    Column("id", String, primary_key=True),
    Column("run_id", String, ForeignKey("blog_runs.id"), nullable=False),
    Column("primary_keyword", Text, nullable=False),
    Column("secondary_keywords", JSON, nullable=True),
    Column("meta_title", Text, nullable=True),
    Column("meta_description", Text, nullable=True),
    Column("slug", Text, nullable=True),
)

outline_sections = Table(
    "outline_sections",
    metadata,
    Column("id", String, primary_key=True),
    Column("run_id", String, ForeignKey("blog_runs.id"), nullable=False),
    Column("section_id", String, nullable=False),
    Column("heading", Text, nullable=False),
    Column("target_keyword", Text, nullable=True),
    Column("grounded", Boolean, server_default="true"),
    Column("order_index", Integer, nullable=False),
)

# --- Writer tables — WRITER.md §6 -------------------------------------------

blog_drafts = Table(
    "blog_drafts",
    metadata,
    Column("id", String, primary_key=True),
    Column("run_id", String, ForeignKey("blog_runs.id"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_by_agent", String, nullable=False, server_default="writer"),
    Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
)

blog_sections = Table(
    "blog_sections",
    metadata,
    Column("id", String, primary_key=True),
    Column("draft_id", String, ForeignKey("blog_drafts.id"), nullable=False),
    Column("section_id", String, nullable=False),
    Column("heading", Text, nullable=False),
    Column("body_markdown", Text, nullable=False),
    Column("order_index", Integer, nullable=False),
    Column("word_count", Integer, nullable=True),
    Column("tone_notes", Text, nullable=True),
    Column("retries_used", Integer, nullable=False, server_default="0"),
    Column("unsupported_gaps", JSON, nullable=True),
)

blog_section_claims = Table(
    "blog_section_claims",
    metadata,
    Column("section_id", String, ForeignKey("blog_sections.id"), nullable=False),
    # The ResearchBrief's own claim id (e.g. "claim-7"), not a uuid FK to
    # research_claims — those row ids are freshly generated at persist time
    # and never line up with the brief's ids the Writer actually sees.
    Column("claim_id", String, nullable=False),
    PrimaryKeyConstraint("section_id", "claim_id"),
)

# --- Finisher tables — FINISHER.md §6 ---------------------------------------

seo_audits = Table(
    "seo_audits",
    metadata,
    Column("id", String, primary_key=True),
    Column("run_id", String, ForeignKey("blog_runs.id"), nullable=False),
    Column("keyword_density", JSON, nullable=True),
    Column("heading_issues", JSON, nullable=True),
    Column("meta_description_ok", Boolean, nullable=True),
    Column("internal_link_suggestions", JSON, nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
)

quiz_questions = Table(
    "quiz_questions",
    metadata,
    Column("id", String, primary_key=True),
    Column("run_id", String, ForeignKey("blog_runs.id"), nullable=False),
    Column("question_type", String, nullable=False, server_default="statement_based"),
    Column("stem", Text, nullable=False),
    Column("statements", JSON, nullable=False),
    Column("options", JSON, nullable=False),
    Column("correct_option", String, nullable=False),
    Column("explanation", Text, nullable=True),
    Column("related_section_id", String, nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
)

media_assets = Table(
    "media_assets",
    metadata,
    Column("id", String, primary_key=True),
    Column("run_id", String, ForeignKey("blog_runs.id"), nullable=False),
    Column("kind", String, nullable=False),  # "banner" | "infographic"
    Column("section_id", String, nullable=True),
    Column("prompt", Text, nullable=True),
    Column("alt_text", Text, nullable=True),
    Column("status", String, nullable=False, server_default="pending"),
    Column("image_url", Text, nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
)

published_blogs = Table(
    "published_blogs",
    metadata,
    Column("id", String, primary_key=True),
    Column("run_id", String, ForeignKey("blog_runs.id"), nullable=False),
    Column("final_title", Text, nullable=True),
    Column("tags", JSON, nullable=True),
    Column("subject", String, nullable=True),
    Column("published_at", TIMESTAMP(timezone=True), nullable=True),
    Column("canonical_url", Text, nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
)

# --- Topic Generator tables — TOPIC_GENERATOR.md §5/§6 ----------------------
# `topic_batches`/`topic_batch_events` are this stage's own lightweight "run"
# concept — topic generation happens before any `blog_runs` row exists, so
# it can't reuse `blog_runs`/`agent_events` (which FK to `blog_runs.id`).

topic_batches = Table(
    "topic_batches",
    metadata,
    Column("id", String, primary_key=True),
    Column("mode", String, nullable=False),  # "autonomous" | "directed"
    Column("user_instruction", Text, nullable=True),
    Column("count", Integer, nullable=False, server_default="8"),
    Column("auto_approve", Boolean, nullable=False, server_default="false"),
    Column("status", String, nullable=False, server_default="pending"),
    Column("error", Text, nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
)

topic_batch_events = Table(
    "topic_batch_events",
    metadata,
    Column("id", String, primary_key=True),
    Column("batch_id", String, ForeignKey("topic_batches.id"), nullable=False),
    Column("step", String, nullable=False),
    Column("phase", String, nullable=False),  # started | done | failed
    Column("detail", JSON, nullable=True),
    Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
)

topics = Table(
    "topics",
    metadata,
    Column("id", String, primary_key=True),
    Column("batch_id", String, ForeignKey("topic_batches.id"), nullable=True),
    Column("title", Text, nullable=False),
    Column("one_line_summary", Text, nullable=True),
    Column("subject", String, nullable=True),
    Column("gs_papers", JSON, nullable=True),
    Column("why_this_topic", Text, nullable=True),
    Column("current_relevance", Text, nullable=True),
    Column("trigger_source_url", Text, nullable=True),
    Column("dedup_status", String, nullable=False, server_default="new"),
    Column("similarity_score", Float, nullable=True),
    Column("status", String, nullable=False, server_default="suggested"),
    Column("created_at", TIMESTAMP(timezone=True), server_default=func.now()),
)
