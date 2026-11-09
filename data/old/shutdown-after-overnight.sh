#!/usr/bin/env bash
# Wait for the overnight run to exit, flush everything to disk, then shut
# Windows down with a 5-minute warning (cancel from Windows: shutdown /a).
PID=28467
LOG=/home/affan/RootLine/data/overnight.log
say() { echo "[$(date -u +%FT%TZ)] shutdown-watch: $*" >> "$LOG"; }

say "waiting for overnight.sh (pid $PID) to exit"
while kill -0 "$PID" 2>/dev/null; do sleep 30; done

# Give the last writes (progress file, iperf container removal) a moment.
sleep 60
if tail -n 5 "$LOG" | grep -q "^\[.*\] done:"; then
  say "overnight run finished normally"
else
  say "overnight run ended without its done line (see above); data so far is kept"
fi
say "data: $(ls /home/affan/RootLine/data/snapshots | wc -l) snapshot folders; flushing disks"
sync
say "shutting Windows down in 5 minutes (cancel with: shutdown /a)"
sync
/mnt/c/Windows/System32/shutdown.exe /s /t 300 /c "RootLine overnight run finished; data saved. Run 'shutdown /a' to cancel." \
  >> "$LOG" 2>&1 || say "shutdown.exe failed (exit $?)"
