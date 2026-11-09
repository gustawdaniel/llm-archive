#!/bin/bash
# Forced command for the GitHub Actions deploy SSH key (see authorized_keys on
# brain-db: command="...deploy-dispatch.sh"). SSH puts whatever the client
# asked to run into $SSH_ORIGINAL_COMMAND - we ignore it except to match it
# against a fixed whitelist, so the key can only ever trigger one of these two
# pull-and-restart actions, never an arbitrary command.
#
# The client pipes the repo's current compose.yaml over stdin (see the `ssh
# ... deploy-api < compose.yaml` calls in the workflows) - we write it to a
# FIXED path (never one the client names) before pull/up, so what runs on
# this host can never drift from what's committed in git. Written to a temp
# file and renamed so a dropped connection mid-transfer can't leave a
# truncated compose.yaml behind.
set -euo pipefail
APP_DIR="${HOME}/apps/llm-archive"
cd "${APP_DIR}"

write_compose() {
    local dest="$1"
    local tmp
    tmp="$(mktemp "${dest}.XXXXXX")"
    cat > "$tmp"
    if [ ! -s "$tmp" ]; then
        rm -f "$tmp"
        echo "Refused: empty compose.yaml received over stdin" >&2
        exit 1
    fi
    mv "$tmp" "$dest"
}

case "${SSH_ORIGINAL_COMMAND:-}" in
    deploy-api)
        write_compose "${APP_DIR}/compose.yaml"
        sudo docker-compose pull llm-archive-api
        sudo docker-compose up -d llm-archive-api
        ;;
    deploy-web)
        write_compose "${APP_DIR}/web/compose.yaml"
        cd web
        sudo docker-compose pull llm-archive-web
        sudo docker-compose up -d llm-archive-web
        ;;
    *)
        echo "Refused: unrecognized command '${SSH_ORIGINAL_COMMAND:-<empty>}'" >&2
        exit 1
        ;;
esac
