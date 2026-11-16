#!/usr/bin/env bash
# Board B: controlled Wi-Fi contention for the hwContention fault.
#
# Sends a fixed-rate UDP stream to an iperf3 server on YOUR OWN network.
# It refuses any server outside private address ranges, so it can never be
# pointed at someone else's network.
#
#   IPERF_SERVER=192.168.1.20 BITRATE=30M DURATION=300 ./iperf_contention.sh
set -euo pipefail

server="${IPERF_SERVER:?set IPERF_SERVER to your local iperf3 server (private IP)}"
bitrate="${BITRATE:-30M}"
duration="${DURATION:-300}"

is_private_ipv4() {
  local ip="$1" a b c d
  [[ "$ip" =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] || return 1
  a=${BASH_REMATCH[1]} b=${BASH_REMATCH[2]} c=${BASH_REMATCH[3]} d=${BASH_REMATCH[4]}
  for o in "$a" "$b" "$c" "$d"; do ((o <= 255)) || return 1; done
  ((a == 10)) && return 0
  ((a == 172 && b >= 16 && b <= 31)) && return 0
  ((a == 192 && b == 168)) && return 0
  return 1
}

if ! is_private_ipv4 "$server"; then
  echo "refusing: $server is not a private IPv4 address (10/8, 172.16/12, 192.168/16)" >&2
  exit 2
fi
[[ "$bitrate" =~ ^[0-9]+[KMG]?$ ]] || { echo "bad BITRATE: $bitrate" >&2; exit 2; }
[[ "$duration" =~ ^[0-9]+$ ]] && ((duration > 0 && duration <= 900)) || {
  echo "DURATION must be 1..900 seconds" >&2; exit 2; }

echo "contention: UDP ${bitrate}bit/s to ${server} for ${duration}s (started $(date -u +%FT%TZ))"
exec iperf3 --client "$server" --udp --bitrate "$bitrate" --time "$duration" --interval 10
