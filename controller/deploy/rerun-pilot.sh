#!/usr/bin/env bash
# Rerun the pilot incidents still pending in data/pilot-progress.json, with
# the demo back in its normal (emulated) wiring. No boards needed.
#
#   export DEMO_DIR=~/opentelemetry-demo
#   ./controller/deploy/rerun-pilot.sh
#
# Takes about 10 minutes of warm-up plus 13-23 minutes per incident.
# Logged to data/overnight.log like the night run.
set -uo pipefail

: "${DEMO_DIR:?set DEMO_DIR to the OpenTelemetry Demo checkout}"

ROOTLINE_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
export ROOTLINE_DIR
export ROOTLINE_UID="$(id -u)" ROOTLINE_GID="$(id -g)"
export ROOTLINE_FLAGD_FILE="${ROOTLINE_FLAGD_FILE:-$DEMO_DIR/src/flagd/demo.flagd.json}"
export DEMO_GIT_TAG="${DEMO_GIT_TAG:-$(git -C "$DEMO_DIR" describe --tags)}"
export DEMO_VERSION="$DEMO_GIT_TAG"
LOG="$ROOTLINE_DIR/data/overnight.log"
exec > >(tee -a "$LOG") 2>&1

say() { echo "[$(date -u +%FT%TZ)] $*"; }
DEMO_FILES=(-f compose.yaml -f compose.full.yaml -f compose.observability.yaml)
compose() { (cd "$DEMO_DIR" && docker compose "${DEMO_FILES[@]}" -f "$ROOTLINE_DIR/compose.override.yml" "$@"); }

cd "$ROOTLINE_DIR" || exit 1

pending="$(python3 -c 'import json; print(" ".join(json.load(open("data/pilot-progress.json"))["pending"]))')"
if [ -z "$pending" ]; then
  say "nothing pending in data/pilot-progress.json"
  exit 0
fi
say "rerun: $pending"

# Leaving out compose.hardware.yml puts checkout -> payment back through
# Toxiproxy, so nothing depends on the boards.
docker rm -f rootline-iperf >/dev/null 2>&1
compose up -d --no-build --remove-orphans || { say "compose failed; stopping"; exit 1; }
addr="$(compose exec -T checkout printenv PAYMENT_ADDR 2>/dev/null | tr -d '\r')"
case "$addr" in
  toxiproxy-payment*) say "checkout -> payment goes through Toxiproxy ($addr)" ;;
  *) say "checkout PAYMENT_ADDR is '$addr', not Toxiproxy; stopping"; exit 1 ;;
esac

"$ROOTLINE_DIR/bin/rootlinectl" campaign --plan plans/pilot.yaml || { say "rerun ended with an error (see above)"; exit 1; }
say "rerun done: see data/pilot-progress.json"
