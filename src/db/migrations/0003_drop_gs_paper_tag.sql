-- Strategist's outline is being kept generic/blog-focused for now — UPSC-specific
-- GS-paper tagging (General Studies paper number) is deferred to a future,
-- audience-specific variant rather than baked into the base outline schema.
-- (0002_strategist.sql has been updated to not create this column for fresh
-- databases; this migration drops it from databases where 0002 already ran.)

ALTER TABLE outline_sections DROP COLUMN IF EXISTS gs_paper_tag;
