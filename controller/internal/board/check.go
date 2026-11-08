package board

import (
	"context"
	"fmt"
	"strings"
	"time"
)

// Result is one line of `rootlinectl hw check`.
type Result struct {
	Name   string
	OK     bool
	Detail string
}

// Check verifies everything the unattended hardware campaign needs, using
// the same commands the faults use. With outage it also runs a 5 s Wi-Fi
// outage on Board A and waits for the board to come back.
func Check(ctx context.Context, b *Boards, outage bool) []Result {
	var res []Result
	add := func(name string, out []byte, err error) bool {
		detail := strings.TrimSpace(string(out))
		if i := strings.IndexByte(detail, '\n'); i >= 0 {
			detail = detail[:i]
		}
		if err != nil {
			detail = err.Error()
		}
		res = append(res, Result{name, err == nil, detail})
		return err == nil
	}

	out, err := b.Output(ctx, "A", "true", 1)
	if !add("Board A reachable by SSH key", out, err) {
		return res
	}
	out, err = b.Output(ctx, "A", "systemctl is-active edge-relay", 1)
	add("Board A relay running", out, err)
	out, err = b.Output(ctx, "A", "sudo -n /usr/local/bin/rootline-fault status", 1)
	add("Board A rootline-fault runs without a password", out, err)
	out, err = b.Output(ctx, "A", "sudo -n /usr/local/bin/rootline-fault weak-on {txpower_mbm} 60 && sudo -n /usr/local/bin/rootline-fault weak-off", 2)
	add("Board A transmit power can be lowered and restored", out, err)

	out, err = b.Output(ctx, "B", "true", 1)
	if add("Board B reachable by SSH key", out, err) {
		out, err = b.Output(ctx, "B", "command -v iperf3 && test -f ~/iperf_contention.sh", 1)
		add("Board B has iperf3 and the contention script", out, err)
		out, err = b.Output(ctx, "B", "IPERF_SERVER={iperf_server} BITRATE=1M DURATION=2 bash ~/iperf_contention.sh", 1)
		add("Board B reaches the laptop's iperf3 server", out, err)
	}

	if outage {
		out, err = b.Output(ctx, "A", "sudo -n /usr/local/bin/rootline-fault outage 5", 1)
		if add("Board A Wi-Fi outage starts", out, err) {
			back := false
			deadline := time.Now().Add(2 * time.Minute)
			_ = b.Sleep(ctx, 10*time.Second)
			for time.Now().Before(deadline) && ctx.Err() == nil {
				if _, err := b.Output(ctx, "A", "true", 1); err == nil {
					back = true
					break
				}
				_ = b.Sleep(ctx, 5*time.Second)
			}
			detail := "back within 2 minutes"
			var e error
			if !back {
				e = fmt.Errorf("board A did not come back within 2 minutes")
			}
			add("Board A reconnects after the outage", []byte(detail), e)
		}
	}
	return res
}
