# edge-relay (Board A)

A TCP relay for the checkout → payment edge, running on the Linux side of
an Arduino UNO Q. Checkout connects to the board over Wi-Fi; the board
connects on to the payment service. Each connection becomes a
`relay.connection` span, plus `relay.connections`, `relay.errors`,
`relay.bytes` (by direction), `relay.connections.active` and
`relay.connection.duration`, exported to the snapshotter as service
`edge-relay`.

## Build and install

On the laptop:

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
`Restart=always` brings it back by itself after the hwPowerCut fault.

## Known asymmetry

Hardware snapshots contain an extra service (`edge-relay`) that the
emulated network faults do not, because Toxiproxy is not instrumented.
That is extra evidence for the models on hardware faults and is reported
as a limitation of the emulation-validity comparison.
TODO(flotrpy): decide whether to keep the relay's telemetry on.
