# Board A: rootline-fault

The one command Rootline runs as root on Board A, through a single sudo rule
(`rootline.sudoers`), so the hardware campaign can run unattended over SSH.

| Command | Effect | Undo |
|---------|--------|------|
| `rootline-fault weak-on <mBm> [s]` | Wi-Fi transmit power fixed low | `weak-off`, or automatically after `s` seconds (default 480) |
| `rootline-fault outage [s]` | Wi-Fi radio off for `s` seconds (default 30), as a detached systemd job | comes back by itself |
| `rootline-fault status` | link and transmit power | |

Install (from WSL, see `docs/HARDWARE.md` stage 2):

```bash
scp hw/board/rootline-fault hw/board/rootline.sudoers arduino@192.168.1.250:~
```

```bash
ssh -t arduino@192.168.1.250 'sudo install -m 0755 ~/rootline-fault /usr/local/bin/rootline-fault && sudo install -m 0440 ~/rootline.sudoers /etc/sudoers.d/rootline && sudo visudo -c'
```

Tests: `harness/tests/test_board_fault.py` runs it against stub `iw`,
`systemd-run` and `systemctl`.
