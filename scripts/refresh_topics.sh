#!/bin/bash
# Periodic topics refresh - keeps auto-clusters, descriptions/keywords, safe
# LLM-judged merges, similarity links, and Obsidian hub docs in sync with
# whatever's changed in the DB (new conversations, retitled ones, manual
# edits). Run by brain-topics-refresh.timer on rog - see
# ~/.config/systemd/user/brain-topics-refresh.{service,timer}.
#
# Incremental only: ensure_embeddings only computes for conversations with
# embedding IS NULL, so a conversation whose title improves later (auto-
# titler) does NOT get re-embedded here. Run `topics recluster
# --force-embeddings` by hand periodically to pick that up - not on this
# timer, since it re-embeds everything (real cost) every time.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

BRAIN_LLM=".venv/bin/brain-llm"

echo "[$(date -Iseconds)] recluster (incremental)"
"$BRAIN_LLM" topics recluster

echo "[$(date -Iseconds)] describe (missing only)"
"$BRAIN_LLM" topics describe

echo "[$(date -Iseconds)] merge-similar"
"$BRAIN_LLM" topics merge-similar --low-threshold 0.6

echo "[$(date -Iseconds)] export-links"
"$BRAIN_LLM" topics export-links

echo "[$(date -Iseconds)] export-hub-docs"
"$BRAIN_LLM" topics export-hub-docs

echo "[$(date -Iseconds)] done"
