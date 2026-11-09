-- Migration: 004_topics_knowledge_graph.sql
-- Description: Emergent topics (auto-clustered, HDBSCAN) + similarity graph for
-- conversation-level browsing. See docs/topics_knowledge_graph.md for the design
-- rationale (why HDBSCAN, why no graph DB, why title+summary not chunk-average).

-- 1. Representative embedding per conversation (title + summary, computed once
--    llm_documents.summary is populated - see auto-classifier). NULL until a
--    conversation has been through at least one clustering pass.
ALTER TABLE llm_conversations ADD COLUMN IF NOT EXISTS embedding vector(1024);
ALTER TABLE llm_conversations ADD COLUMN IF NOT EXISTS last_clustered_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_llm_conversations_embedding
    ON llm_conversations USING hnsw (embedding vector_cosine_ops);

-- 2. Topics: emergent clusters, optionally human-named/described. `centroid` is
--    what lets a re-cluster run match a new cluster back to an existing topic
--    (cosine similarity) so names/descriptions survive across runs.
CREATE TABLE IF NOT EXISTS llm_topics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    description TEXT,
    centroid vector(1024) NOT NULL,
    is_manual BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Conversation <-> topic assignment. `source='manual'` rows are never
--    overwritten by the clustering job - a human correction sticks.
CREATE TABLE IF NOT EXISTS llm_conversation_topics (
    conversation_id UUID NOT NULL REFERENCES llm_conversations(id) ON DELETE CASCADE,
    topic_id UUID NOT NULL REFERENCES llm_topics(id) ON DELETE CASCADE,
    score DOUBLE PRECISION NOT NULL,
    source VARCHAR(20) NOT NULL DEFAULT 'auto',
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (conversation_id, topic_id)
);

CREATE INDEX IF NOT EXISTS idx_llm_conversation_topics_topic ON llm_conversation_topics (topic_id);

-- 4. Precomputed similarity edges (top-k nearest neighbours per conversation).
--    Computed once per clustering run, reused by both the Obsidian wikilink
--    export and (later) a custom graph view - never recomputed on read.
CREATE TABLE IF NOT EXISTS llm_similarity_edges (
    conversation_id_a UUID NOT NULL REFERENCES llm_conversations(id) ON DELETE CASCADE,
    conversation_id_b UUID NOT NULL REFERENCES llm_conversations(id) ON DELETE CASCADE,
    score DOUBLE PRECISION NOT NULL,
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (conversation_id_a, conversation_id_b),
    CONSTRAINT chk_edge_order CHECK (conversation_id_a < conversation_id_b)
);

CREATE INDEX IF NOT EXISTS idx_llm_similarity_edges_b ON llm_similarity_edges (conversation_id_b);
