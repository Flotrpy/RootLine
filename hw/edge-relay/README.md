# edge-relay (Board A)

A TCP relay for the checkout → payment edge, running on the Linux side of
an Arduino UNO Q. Checkout connects to the board over Wi-Fi; the board
connects on to the payment service. Each connection becomes a
`relay.connection` span, plus `relay.connections`, `relay.errors`,
`relay.bytes` (by direction), `relay.connections.active` and
`relay.connection.duration`, exported to the snapshotter as service
`edge-relay`.

## Build and install

On the PC:

```bash
GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -trimpath -o edge-relay .
```

Copy `edge-relay`, `edge-relay.service` and `edge-relay.env.example` to the
board, then on the board:

```bash
sudo install -m 0755 edge-relay /usr/local/bin/edge-relay
sudo mkdir -p /etc/rootline
sudo cp edge-relay.env.example /etc/rootline/edge-relay.env   # then edit the IPs
sudo cp edge-relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now edge-relay
```

Check it with `systemctl status edge-relay` and `journalctl -u edge-relay -f`.
`Restart=always` keeps it running across reboots and crashes.

## Telemetry

The relay can export its own spans, but in the v0.1 campaign none reached the
snapshotter: no hardware snapshot contains an `edge-relay` service. That
keeps hardware and emulated snapshots alike (Toxiproxy is not instrumented
either). Decided for v0.1: leave it that way, so the comparison stays fair.
