#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$SCRIPT_DIR/venv" ]; then
    exec "$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/social-archive.py" "$@"
else
    exec python3 "$SCRIPT_DIR/social-archive.py" "$@"
fi
