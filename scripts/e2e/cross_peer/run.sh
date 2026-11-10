#!/usr/bin/env bash
# Local wrapper for the cross-peer run (scripts/e2e/cross_peer/run.py).
#
#   REM0TE_SRC=/path/to/built/rem0te \
#   DATABASE_URL=postgresql://user:pw@127.0.0.1:5432/rem0te_scratch \
#   [REDIS_URL=redis://127.0.0.1:6379] [PYTHON=venv/bin/python] \
#   bash scripts/e2e/cross_peer/run.sh [--keep] [--only s4,s5]
#
# Or point REM0TE_ENV_SH at a file that exports those (and PATH for node).
# Rem0te must be built (pnpm install && pnpm -r build) with its scratch
# database migrated and seeded (pnpm --filter api exec prisma migrate deploy;
# pnpm --filter api exec prisma db seed). Nothing here touches a ClientSt0r
# deployment: ClientSt0r runs on a throwaway SQLite file under the work dir.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
if [ -n "${REM0TE_ENV_SH:-}" ]; then
  # shellcheck disable=SC1090
  . "$REM0TE_ENV_SH"
fi
: "${REM0TE_SRC:?set REM0TE_SRC to a built Rem0te checkout}"
: "${DATABASE_URL:?set DATABASE_URL to the scratch Postgres database of Rem0te}"
PYTHON="${PYTHON:-$ROOT/venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"
cd "$ROOT"
exec "$PYTHON" "$HERE/run.py" "$@"
