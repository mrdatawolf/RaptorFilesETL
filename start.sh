#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

if [[ "${PUSH_PULL:-}" == push && -z "${RAPTOR_PUSH_DEST:-}" ]]; then
    echo "RAPTOR_PUSH_DEST is required when PUSH_PULL=push" >&2
    exit 2
fi

status=0
.venv/bin/raptor-etl run "$@" || status=$?
if [[ "${PUSH_PULL:-}" == push && "$status" -le 1 ]]; then
    snapshot_dir="$(mktemp -d)"
    trap 'rm -rf -- "$snapshot_dir"' EXIT
    .venv/bin/python - "${RAPTOR_DB_PATH:?}" "$snapshot_dir/trimmer.db" <<'PY'
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

source = Path(sys.argv[1]).resolve().as_uri() + "?mode=ro"
with closing(sqlite3.connect(source, uri=True)) as db:
    with closing(sqlite3.connect(sys.argv[2])) as snapshot:
        db.backup(snapshot)
PY
    ./push_db.sh "$snapshot_dir/trimmer.db"
fi
exit "$status"
