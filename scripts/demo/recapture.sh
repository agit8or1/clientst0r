#!/usr/bin/env bash
# Recapture the documentation screenshots in one command.
#
#   DEMO_DIR=/var/tmp/clientst0r-demo DEMO_PORT=8099 \
#     bash scripts/demo/recapture.sh [--rebuild] [--walkthrough DIR] [NAME ...]
#
# * --rebuild         build the demo instance from scratch first (deletes
#                     $DEMO_DIR/demo.sqlite3 and media; nothing else).
#                     Without it the existing demo database is reused.
# * --walkthrough DIR also record the walkthrough into DIR, then copy the
#                     GIF and poster into docs/images/github and the
#                     transcript and captions into docs/media.
# * NAME ...          capture only these manifest entries (default: all).
#
# Starts the demo server on 127.0.0.1:$DEMO_PORT, captures into
# docs/images/github, rebuilds docs/screenshots.md and stops the server.
#
# Environment:
#   DEMO_DIR    (required) the demo instance directory, outside the repo
#   DEMO_PORT   port for the demo server (default 8099)
#   PYTHON      the project interpreter (default: venv/bin/python, else python3)
#   PLAYWRIGHT_PYTHONPATH  extra PYTHONPATH entry holding the playwright
#               package when it is not installed in that interpreter
#   HARDWARE_CATALOG_SOURCE  reuse a devicetype-library checkout on --rebuild
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
: "${DEMO_DIR:?set DEMO_DIR to the demo instance directory (outside the repository)}"
case "$DEMO_DIR" in "$ROOT"*) echo "DEMO_DIR must be outside the repository" >&2; exit 2;; esac
DEMO_PORT="${DEMO_PORT:-8099}"
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  if [ -x "$ROOT/venv/bin/python" ]; then PYTHON="$ROOT/venv/bin/python"; else PYTHON=python3; fi
fi
export DEMO_DIR DEMO_PORT DEMO_BASE="http://127.0.0.1:$DEMO_PORT"
export DJANGO_SETTINGS_MODULE=demo_settings PYTHONUNBUFFERED=1
export PYTHONPATH="scripts/demo:.${PLAYWRIGHT_PYTHONPATH:+:$PLAYWRIGHT_PYTHONPATH}"

REBUILD=0; WALK=""; ONLY=()
while [ $# -gt 0 ]; do
  case "$1" in
    --rebuild) REBUILD=1;;
    --walkthrough) WALK="$2"; shift;;
    *) ONLY+=("$1");;
  esac
  shift
done

if [ "$REBUILD" = 1 ]; then
  mkdir -p "$DEMO_DIR"
  rm -rf "$DEMO_DIR/demo.sqlite3" "$DEMO_DIR/demo.sqlite3-journal" "$DEMO_DIR/media"
  "$PYTHON" scripts/demo/setup_demo.py
fi
[ -f "$DEMO_DIR/demo.sqlite3" ] || { echo "no demo database in $DEMO_DIR; run with --rebuild" >&2; exit 2; }

LOG="$DEMO_DIR/runserver.log"
AXES_COOLOFF_TIME=1 AXES_FAILURE_LIMIT=5 AGIT8OR_CONNECT_ENABLED=True \
  AGIT8OR_CONNECT_PUBLIC_URL=https://desk.beaconmanaged.example setsid "$PYTHON" manage.py runserver "127.0.0.1:$DEMO_PORT" \
  --settings=demo_settings --noreload >"$LOG" 2>&1 &
SERVER=$!
trap 'kill -- -"$SERVER" 2>/dev/null || kill "$SERVER" 2>/dev/null || true' EXIT
for _ in $(seq 1 120); do
  curl -fsS -o /dev/null "$DEMO_BASE/health/" 2>/dev/null && break
  sleep 1
done
curl -fsS -o /dev/null "$DEMO_BASE/health/" || { echo "demo server did not start; see $LOG" >&2; exit 1; }

status=0
if [ ${#ONLY[@]} -gt 0 ]; then
  "$PYTHON" scripts/capture_screenshots.py --out docs/images/github --base "$DEMO_BASE" --only "${ONLY[@]}" || status=$?
else
  "$PYTHON" scripts/capture_screenshots.py --out docs/images/github --base "$DEMO_BASE" || status=$?
fi
"$PYTHON" scripts/build_gallery.py || status=$?

if [ -n "$WALK" ]; then
  "$PYTHON" scripts/capture_walkthrough.py --out "$WALK" || status=$?
  if [ -f "$WALK/walkthrough.gif" ]; then
    cp "$WALK/walkthrough.gif" "$WALK/walkthrough-poster.png" docs/images/github/
    cp "$WALK/walkthrough.txt" "$WALK/walkthrough.vtt" docs/media/
  fi
fi
exit $status
