#!/usr/bin/env bash
# One unattended night: the 30-snapshot pilot campaign, then the hardware
# wiring, then the 12 hardware snapshots. Run from the RootLine checkout
# inside WSL (or any Linux shell) with the demo already pulled:
#
#   export DEMO_DIR=~/opentelemetry-demo DEMO_GIT_TAG=<tag>
#   export ROOTLINE_BOARD_A=arduino@192.168.1.250 ROOTLINE_BOARD_B=arduino@192.168.1.217
#   export ROOTLINE_IPERF_SERVER=192.168.1.178 HW_RELAY_ADDR=192.168.1.250:50051
#   ./controller/deploy/overnight.sh
#
# Safe to rerun: both campaigns resume where they stopped. Everything is
# logged to data/overnight.log.
set -uo pipefail

: "${DEMO_DIR:?set DEMO_DIR to the OpenTelemetry Demo checkout}"
: "${ROOTLINE_BOARD_A:?set ROOTLINE_BOARD_A}" "${ROOTLINE_BOARD_B:?set ROOTLINE_BOARD_B}"
: "${ROOTLINE_IPERF_SERVER:?set ROOTLINE_IPERF_SERVER to the laptop LAN IP}"
: "${HW_RELAY_ADDR:?set HW_RELAY_ADDR to Board A ip:port}"

ROOTLINE_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
export ROOTLINE_DIR
export ROOTLINE_FLAGD_FILE="${ROOTLINE_FLAGD_FILE:-$DEMO_DIR/src/flagd/demo.flagd.json}"
# The demo's .env says DEMO_VERSION=latest; pin the images to the checked-out tag.
export DEMO_GIT_TAG="${DEMO_GIT_TAG:-$(git -C "$DEMO_DIR" describe --tags)}"
export DEMO_VERSION="$DEMO_GIT_TAG"
LOG="$ROOTLINE_DIR/data/overnight.log"
mkdir -p "$ROOTLINE_DIR/data"
exec > >(tee -a "$LOG") 2>&1

say() { echo "[$(date -u +%FT%TZ)] $*"; }
# Demo 3.x: core + full (Kafka, fraud detection) + observability (Prometheus).
DEMO_FILES=(-f compose.yaml -f compose.full.yaml -f compose.observability.yaml)
compose() { (cd "$DEMO_DIR" && docker compose "${DEMO_FILES[@]}" -f "$ROOTLINE_DIR/compose.override.yml" "$@"); }
ctl() { "$ROOTLINE_DIR/bin/rootlinectl" "$@"; }

cd "$ROOTLINE_DIR" || exit 1

say "1/4 demo with the emulated wiring"
# Pull the released 3.1.0 images (every demo service also has build steps,
# and building them all from source takes hours); build only Rootline's own.
compose pull --ignore-pull-failures --quiet
compose build snapshotter || { say "snapshotter build failed; stopping"; exit 1; }
compose up -d --no-build || { say "compose failed; stopping"; exit 1; }

say "2/4 pilot campaign (30 snapshots, ~6.5 h)"
ctl campaign --plan plans/pilot.yaml || say "pilot campaign ended with an error (see above); continuing"

say "3/4 hardware wiring and iperf3 server"
compose -f "$ROOTLINE_DIR/compose.hardware.yml" up -d --no-build || { say "hardware compose failed; stopping"; exit 1; }
docker rm -f rootline-iperf >/dev/null 2>&1
docker run -d --rm --name rootline-iperf -p 5201:5201/tcp -p 5201:5201/udp alpine:3.22 \
  sh -c "apk add --no-cache iperf3 >/dev/null && exec iperf3 --server" || { say "iperf3 server failed; stopping"; exit 1; }
sleep 30

if ! ctl hw check; then
  say "hardware check failed: skipping the hardware campaign (pilot data is kept)"
  exit 1
fi

say "4/4 hardware campaign (12 snapshots, ~2.6 h)"
ctl campaign --plan plans/hardware.yaml || say "hardware campaign ended with an error (see above)"

docker rm -f rootline-iperf >/dev/null 2>&1
say "done: see data/pilot-progress.json and data/hardware-progress.json"
