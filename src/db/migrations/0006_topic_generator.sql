-- Topic Generator agent tables from TOPIC_GENERATOR.md §5/§6. Source of
-- truth for the actual DB; src/db/tables.py mirrors this for SQLAlchemy
-- Core access.
--
-- Requires the DB user running migrations to have privileges to create
-- extensions (typically fine on RDS for the master user; if this statement
-- fails, run it once with elevated credentials before re-running migrations).
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- `topic_batches` is this stage's own lightweight "run" concept — it exists
-- before any `blog_runs` row does (topic generation happens pre-Researcher),
-- so it can't reuse `blog_runs`/`agent_events`, which FK to `blog_runs.id`.
CREATE TABLE IF NOT EXISTS topic_batches (
    id                uuid PRIMARY KEY,
    mode              text NOT NULL CHECK (mode IN ('autonomous', 'directed')),
    user_instruction  text,
    count             integer NOT NULL DEFAULT 8,
    auto_approve      boolean NOT NULL DEFAULT false,
    status            text NOT NULL DEFAULT 'pending',
    error             text,
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS topic_batch_events (
    id          uuid PRIMARY KEY,
    batch_id    uuid NOT NULL REFERENCES topic_batches(id),
    step        text NOT NULL,
    phase       text NOT NULL CHECK (phase IN ('started', 'done', 'failed')),
    detail      jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_topic_batch_events_batch_id ON topic_batch_events(batch_id);

CREATE TABLE IF NOT EXISTS topics (
    id                  uuid PRIMARY KEY,
    batch_id            uuid REFERENCES topic_batches(id),
    title               text NOT NULL,
    one_line_summary    text,
    subject             text,
    gs_papers           jsonb,
    why_this_topic      text,
    current_relevance   text,
    trigger_source_url  text,
    dedup_status        text NOT NULL DEFAULT 'new'
                            CHECK (dedup_status IN ('new', 'similar_to_existing', 'needs_review')),
    similarity_score    double precision,
    status              text NOT NULL DEFAULT 'suggested'
                            CHECK (status IN ('suggested', 'selected', 'generated', 'rejected')),
    created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_topics_batch_id ON topics(batch_id);
CREATE INDEX IF NOT EXISTS idx_topics_title_trgm ON topics USING gin (title gin_trgm_ops);

-- Nullable: a run's topic was always meant to trace back to something
-- (TOPIC_GENERATOR.md §6) — set when a run is started from a selected
-- candidate, left null for today's raw-string `POST /runs`.
ALTER TABLE blog_runs ADD COLUMN IF NOT EXISTS topic_id uuid REFERENCES topics(id);
