-- Backs `api.supervisor.PipelineSupervisor`: a run that's paused stops the
-- auto-advance chain at the next stage boundary (research -> strategize ->
-- write -> finish) instead of requiring a manual "Run" click per stage.
ALTER TABLE blog_runs ADD COLUMN IF NOT EXISTS paused boolean NOT NULL DEFAULT false;
