-- Migration: 002_sync_health.sql
-- Description: distinguish "when was this conversation's content last active"
-- (updated_at, derived from message timestamps) from "when did the server
-- last actually persist an ingest for it" (last_ingested_at, server clock).
-- Needed because /api/v1/stats used MAX(updated_at) per device as a sync
-- health signal, which is wrong: a backlog conversation re-synced today still
-- carries its original (old) message timestamps, making healthy sync look stale.

ALTER TABLE llm_conversations
    ADD COLUMN IF NOT EXISTS last_ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_llm_conversations_last_ingested ON llm_conversations (last_ingested_at DESC);
