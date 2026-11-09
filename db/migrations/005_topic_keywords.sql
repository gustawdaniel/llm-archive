-- Migration: 005_topic_keywords.sql
-- Description: llm_topics.description was already in the schema but unused -
-- add keywords alongside it. Both are generated from a deeper sample (real
-- user messages pooled across several member conversations, not just titles)
-- so they carry enough signal to drive a semantic merge pass that catches
-- near-duplicate topics raw embedding-centroid similarity misses.

ALTER TABLE llm_topics ADD COLUMN IF NOT EXISTS keywords TEXT[];
