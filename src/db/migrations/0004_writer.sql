-- Writer agent tables from WRITER.md §6. Source of truth for the actual DB;
-- src/db/tables.py mirrors this for SQLAlchemy Core access.
--
-- blog_section_claims.claim_id is `text`, not a uuid FK to research_claims —
-- it stores the ResearchBrief's own claim id (e.g. "claim-7"), which never
-- lines up with research_claims' randomly generated row ids. See the
-- Writer agent implementation plan for the reasoning.

CREATE TABLE IF NOT EXISTS blog_drafts (
    id                uuid PRIMARY KEY,
    run_id            uuid NOT NULL REFERENCES blog_runs(id),
    version           integer NOT NULL,
    created_by_agent  text NOT NULL DEFAULT 'writer',
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_blog_drafts_run_id ON blog_drafts(run_id);

CREATE TABLE IF NOT EXISTS blog_sections (
    id                uuid PRIMARY KEY,
    draft_id          uuid NOT NULL REFERENCES blog_drafts(id),
    section_id        text NOT NULL,
    heading           text NOT NULL,
    body_markdown     text NOT NULL,
    order_index       integer NOT NULL,
    word_count        integer,
    tone_notes        text,
    retries_used      integer NOT NULL DEFAULT 0,
    unsupported_gaps  jsonb
);

CREATE INDEX IF NOT EXISTS idx_blog_sections_draft_id ON blog_sections(draft_id);

CREATE TABLE IF NOT EXISTS blog_section_claims (
    section_id  uuid NOT NULL REFERENCES blog_sections(id),
    claim_id    text NOT NULL,
    PRIMARY KEY (section_id, claim_id)
);
