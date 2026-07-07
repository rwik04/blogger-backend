-- Backs the "direct" question type added to `agents.finisher.nodes.assemble_questions`:
-- previously every quiz question was statement-based (numbered statements +
-- combination options); now candidate generation also produces plain
-- single-answer MCQs when a claim is a single checkable fact rather than
-- forcing everything into the statement/combination format. Existing rows
-- default to 'statement_based' since that was the only format before this.
ALTER TABLE quiz_questions ADD COLUMN IF NOT EXISTS question_type text NOT NULL DEFAULT 'statement_based';
