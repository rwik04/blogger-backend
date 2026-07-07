-- Adds a numeric relevance score to `topics`, used to size/rank the
-- dashboard "Hot Topics" view and to trim the daily autonomous cron's wide
-- candidate net down to the top N. Nullable — existing rows get a real score
-- via the one-off `backfill-topic-relevance` CLI rather than a fake default.
ALTER TABLE topics ADD COLUMN IF NOT EXISTS relevance_score integer;
