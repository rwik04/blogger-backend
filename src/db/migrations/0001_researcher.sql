-- Minimal blog_runs / agent_events / agent_steps (no prior schema existed for
-- these in this repo) plus the Researcher-specific tables from RESEARCHER.md §5.
-- Source of truth for the actual DB; src/db/tables.py mirrors this for
-- SQLAlchemy Core access.

CREATE TABLE IF NOT EXISTS blog_runs (
    id            uuid PRIMARY KEY,
    topic         text NOT NULL,
    audience_tag  text,
    status        text NOT NULL DEFAULT 'pending',
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_events (
    id          uuid PRIMARY KEY,
    run_id      uuid NOT NULL REFERENCES blog_runs(id),
    step        text NOT NULL,
    phase       text NOT NULL CHECK (phase IN ('started', 'done', 'failed')),
    detail      jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_events_run_id ON agent_events(run_id);

CREATE TABLE IF NOT EXISTS agent_steps (
    id          uuid PRIMARY KEY,
    run_id      uuid NOT NULL REFERENCES blog_runs(id),
    agent       text NOT NULL,
    status      text NOT NULL,
    output      jsonb,
    error       text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_steps_run_id ON agent_steps(run_id);

CREATE TABLE IF NOT EXISTS research_sources (
    id            uuid PRIMARY KEY,
    run_id        uuid REFERENCES blog_runs(id),
    url           text NOT NULL,
    title         text,
    domain        text,
    retrieved_at  timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS research_claims (
    id            uuid PRIMARY KEY,
    run_id        uuid REFERENCES blog_runs(id),
    claim_text    text NOT NULL,
    confidence    text CHECK (confidence IN ('high', 'medium', 'low')),
    contradicted  boolean DEFAULT false
);

CREATE TABLE IF NOT EXISTS research_claim_sources (
    claim_id      uuid REFERENCES research_claims(id),
    source_id     uuid REFERENCES research_sources(id),
    PRIMARY KEY (claim_id, source_id)
);
