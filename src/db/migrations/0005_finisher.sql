-- Finisher agent tables from FINISHER.md §6. Source of truth for the actual
-- DB; src/db/tables.py mirrors this for SQLAlchemy Core access.
--
-- quiz_questions.statements/options are embedded jsonb, not normalized —
-- unlike blog_section_claims, there's no cross-run claim-id-mismatch
-- problem here (statements/options only ever belong to their own question),
-- so normalizing them would add join overhead for no benefit.
--
-- published_blogs is created here in a staged state (published_at/canonical_url
-- both NULL) — there's no publish action yet (no Supervisor), so this just
-- reserves the row that final_title/final_tags/subject map onto.

CREATE TABLE IF NOT EXISTS seo_audits (
    id                         uuid PRIMARY KEY,
    run_id                     uuid NOT NULL REFERENCES blog_runs(id),
    keyword_density            jsonb,
    heading_issues             jsonb,
    meta_description_ok        boolean,
    internal_link_suggestions  jsonb,
    created_at                 timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_seo_audits_run_id ON seo_audits(run_id);

CREATE TABLE IF NOT EXISTS quiz_questions (
    id                   uuid PRIMARY KEY,
    run_id               uuid NOT NULL REFERENCES blog_runs(id),
    stem                 text NOT NULL,
    statements           jsonb NOT NULL,   -- [{text, is_true, claim_id}]
    options              jsonb NOT NULL,   -- [{label, text}]
    correct_option       text NOT NULL,
    explanation          text,
    related_section_id   text,
    created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_quiz_questions_run_id ON quiz_questions(run_id);

CREATE TABLE IF NOT EXISTS media_assets (
    id           uuid PRIMARY KEY,
    run_id       uuid NOT NULL REFERENCES blog_runs(id),
    kind         text NOT NULL CHECK (kind IN ('banner', 'infographic')),
    section_id   text,
    prompt       text,
    alt_text     text,
    status       text NOT NULL DEFAULT 'pending',
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_media_assets_run_id ON media_assets(run_id);

CREATE TABLE IF NOT EXISTS published_blogs (
    id             uuid PRIMARY KEY,
    run_id         uuid NOT NULL REFERENCES blog_runs(id),
    final_title    text,
    tags           jsonb,
    subject        text,
    published_at   timestamptz,
    canonical_url  text,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_published_blogs_run_id ON published_blogs(run_id);
