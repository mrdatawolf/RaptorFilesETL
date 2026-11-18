#!/usr/bin/env bash
set -euo pipefail

src="${1:?Usage: push_db.sh <path-to-snapshot>}"
dest="${RAPTOR_PUSH_DEST:?RAPTOR_PUSH_DEST is required}"
rsync -az -- "$src" "${dest%/}/trimmer.db"
