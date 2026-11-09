#!/usr/bin/env bash
# ==============================================================================
# Brain LLM Sync Extension Installer
# Usage: ./install.sh [--bump patch|minor|major]
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

python3 install.py "$@"
