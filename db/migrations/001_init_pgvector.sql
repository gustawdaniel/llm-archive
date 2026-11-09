-- Migration: 001_init_pgvector.sql
-- Description: Centralized PostgreSQL 16 schema for LLM Archive with pgvector, full-text search, and relational turn models.

-- 1. Required Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- 2. Conversations Table
CREATE TABLE IF NOT EXISTS llm_conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    platform VARCHAR(50) NOT NULL,
    external_id VARCHAR(255) NOT NULL,
    title TEXT NOT NULL,
    project_path TEXT,
    git_branch VARCHAR(255),
    device VARCHAR(100),
    model VARCHAR(100),
    started_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    raw_metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_platform_external UNIQUE (platform, external_id)
);

CREATE INDEX IF NOT EXISTS idx_llm_conversations_platform ON llm_conversations (platform);
CREATE INDEX IF NOT EXISTS idx_llm_conversations_project ON llm_conversations (project_path);
CREATE INDEX IF NOT EXISTS idx_llm_conversations_updated ON llm_conversations (updated_at DESC);

-- 3. Messages Table
CREATE TABLE IF NOT EXISTS llm_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES llm_conversations(id) ON DELETE CASCADE,
    external_message_id VARCHAR(255),
    parent_external_id VARCHAR(255),
    step_index INTEGER NOT NULL,
    role VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    reasoning_content TEXT,
    tool_calls JSONB DEFAULT '[]'::jsonb,
    attachments JSONB DEFAULT '[]'::jsonb,
    sources JSONB DEFAULT '[]'::jsonb,
    token_usage JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_conv_step UNIQUE (conversation_id, step_index)
);

CREATE INDEX IF NOT EXISTS idx_llm_messages_conv ON llm_messages (conversation_id);

-- 4. Documents Table (Obsidian/Markdown sync mirror)
CREATE TABLE IF NOT EXISTS llm_documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID UNIQUE REFERENCES llm_conversations(id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    content_markdown TEXT NOT NULL,
    summary TEXT,
    hash_sha256 VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. Semantic Chunks Table (HNSW Vector Search + Full-Text Search TSV)
CREATE TABLE IF NOT EXISTS llm_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES llm_conversations(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    header_path TEXT,
    text_content TEXT NOT NULL,
    embedding vector(1024),
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, text_content)) STORED,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_conv_chunk UNIQUE (conversation_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_llm_chunks_embedding ON llm_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_llm_chunks_tsv ON llm_chunks USING gin (tsv);
