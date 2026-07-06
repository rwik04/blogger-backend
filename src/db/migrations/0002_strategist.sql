-- Strategist agent tables from STRATEGIST.md §4. Source of truth for the
-- actual DB; src/db/tables.py mirrors this for SQLAlchemy Core access.

CREATE TABLE IF NOT EXISTS seo_plans (
    id                  uuid PRIMARY KEY,
    run_id              uuid NOT NULL REFERENCES blog_runs(id),
    primary_keyword     text NOT NULL,
    secondary_keywords  jsonb,
    meta_title          text,
    meta_description    text,
    slug                text
);

CREATE INDEX IF NOT EXISTS idx_seo_plans_run_id ON seo_plans(run_id);

CREATE TABLE IF NOT EXISTS outline_sections (
    id               uuid PRIMARY KEY,
    run_id           uuid NOT NULL REFERENCES blog_runs(id),
    section_id       text NOT NULL,
    heading          text NOT NULL,
    target_keyword   text,
    grounded         boolean NOT NULL DEFAULT true,
    order_index      integer NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_outline_sections_run_id ON outline_sections(run_id);
