#!/bin/sh
# Write the digest of every image the stack uses to data/image-digests.json,
# which the snapshotter copies into each snapshot manifest.
# Run from the demo checkout with the same -f flags you use for `up`:
#   COMPOSE="docker compose -f compose.yaml -f compose.full.yaml -f compose.observability.yaml -f $ROOTLINE_DIR/compose.override.yml" \
#     "$ROOTLINE_DIR/controller/deploy/record-digests.sh"
set -eu
: "${ROOTLINE_DIR:?set ROOTLINE_DIR}"
COMPOSE=${COMPOSE:-docker compose}
out="$ROOTLINE_DIR/data/image-digests.json"
tmp="$out.tmp"
printf '{' > "$tmp"
sep=""
for img in $($COMPOSE config --images | sort -u); do
  digest=$(docker image inspect --format '{{index .RepoDigests 0}}' "$img" 2>/dev/null || echo "unknown")
  printf '%s\n  "%s": "%s"' "$sep" "$img" "$digest" >> "$tmp"
  sep=","
done
printf '\n}\n' >> "$tmp"
mv "$tmp" "$out"
echo "wrote $out"
