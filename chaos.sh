#!/usr/bin/env bash
# POSIX wrapper for chaos.py — call via `./chaos.sh <subcommand>`.
# Works in Git Bash on Windows as well as native Linux/macOS shells.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python "$HERE/chaos.py" "$@"
