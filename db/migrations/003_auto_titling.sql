-- Migration: 003_auto_titling.sql
-- Description: Add original_title and title_generated_at for background LLM titling.

ALTER TABLE llm_conversations
    ADD COLUMN IF NOT EXISTS original_title TEXT,
    ADD COLUMN IF NOT EXISTS title_generated_at TIMESTAMPTZ;

-- Backfill original_title from current title if NULL
UPDATE llm_conversations
SET original_title = title
WHERE original_title IS NULL AND title IS NOT NULL;

-- Index for finding conversations needing titling
CREATE INDEX IF NOT EXISTS idx_llm_conversations_title_sync
    ON llm_conversations (updated_at DESC)
    WHERE title_generated_at IS NULL;
