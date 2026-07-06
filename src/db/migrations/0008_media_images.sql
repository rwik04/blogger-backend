-- Backs `agents.finisher.nodes.fetch_media_images`: resolves each banner/
-- infographic prompt to a real Google Images URL (via SerpAPI) right after
-- `plan_media`, so the published blog can render actual images instead of
-- just text prompts. NULL when no SERPAPI_API_KEY is configured or the
-- search came up empty/failed — the prompt/alt_text are still useful on
-- their own in that case.
ALTER TABLE media_assets ADD COLUMN IF NOT EXISTS image_url text;
