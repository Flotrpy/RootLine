package board

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"
)

type call struct{ args []string }

type fakeRunner struct {
	calls []call
	// fail decides, per remote command, whether the attempt fails.
	fail func(cmd string, attempt int) bool
	seen map[string]int
}

func (f *fakeRunner) Run(_ context.Context, name string, args ...string) ([]byte, error) {
	f.calls = append(f.calls, call{append([]string{name}, args...)})
	cmd := args[len(args)-1]
	if f.seen == nil {
		f.seen = map[string]int{}
	}
	f.seen[cmd]++
	if f.fail != nil && f.fail(cmd, f.seen[cmd]) {
		return []byte("ssh: connect to host: No route to host"), errors.New("exit status 255")
	}
	return []byte("ok\nmore"), nil
}

func newBoards(r *fakeRunner) *Boards {
	return &Boards{
		Runner:    r,
		Hosts:     map[string]string{"A": "arduino@10.0.0.50", "B": "arduino@10.0.0.51"},
		Vars:      map[string]string{"txpower_mbm": "100", "iperf_server": "10.0.0.20", "contention_bitrate": "30M"},
		Timeout:   time.Second,
		RetryWait: time.Millisecond,
		Sleep:     func(context.Context, time.Duration) error { return nil },
	}
}

func TestExpand(t *testing.T) {
	got, err := Expand("weak-on {txpower_mbm} to {iperf_server}", map[string]string{"txpower_mbm": "100", "iperf_server": "10.0.0.20"})
	if err != nil || got != "weak-on 100 to 10.0.0.20" {
		t.Fatalf("got %q, %v", got, err)
	}
	if _, err := Expand("{iperf_server}", map[string]string{}); err == nil || !strings.Contains(err.Error(), "iperf_server") {
		t.Fatalf("want missing-setting error, got %v", err)
	}
	if _, err := Expand("{iperf_server}", map[string]string{"iperf_server": "1.2.3.4; rm -rf /"}); err == nil {
		t.Fatal("unsafe value must be refused")
	}
}

func TestExecUsesBatchModeSSH(t *testing.T) {
	r := &fakeRunner{}
	if err := newBoards(r).Exec(context.Background(), "A", "sudo -n /usr/local/bin/rootline-fault weak-on {txpower_mbm}", 1); err != nil {
		t.Fatal(err)
	}
	args := strings.Join(r.calls[0].args, " ")
	for _, want := range []string{"ssh ", "BatchMode=yes", "arduino@10.0.0.50", "weak-on 100"} {
		if !strings.Contains(args, want) {
			t.Fatalf("%q missing %q", args, want)
		}
	}
}

func TestRetriesThenGivesUp(t *testing.T) {
	r := &fakeRunner{fail: func(_ string, attempt int) bool { return attempt < 3 }}
	if err := newBoards(r).Exec(context.Background(), "A", "x", 4); err != nil {
		t.Fatalf("third attempt should succeed: %v", err)
	}
	if len(r.calls) != 3 {
		t.Fatalf("attempts = %d, want 3", len(r.calls))
	}
	always := &fakeRunner{fail: func(string, int) bool { return true }}
	if err := newBoards(always).Exec(context.Background(), "B", "y", 2); err == nil {
		t.Fatal("want error after all attempts fail")
	}
	if len(always.calls) != 2 {
		t.Fatalf("attempts = %d, want 2", len(always.calls))
	}
}

func TestUnknownBoard(t *testing.T) {
	b := newBoards(&fakeRunner{})
	delete(b.Hosts, "B")
	if err := b.Exec(context.Background(), "B", "true", 1); err == nil || !strings.Contains(err.Error(), "ROOTLINE_BOARD_B") {
		t.Fatalf("got %v", err)
	}
}

func TestFromEnv(t *testing.T) {
	env := map[string]string{"ROOTLINE_BOARD_A": "arduino@a", "ROOTLINE_IPERF_SERVER": "10.0.0.20"}
	b := FromEnv(func(k string) string { return env[k] })
	if b.Hosts["A"] != "arduino@a" || b.Hosts["B"] != "" || b.Vars["txpower_mbm"] != "100" ||
		b.Vars["contention_bitrate"] != "30M" || b.Vars["iperf_server"] != "10.0.0.20" {
		t.Fatalf("%+v", b)
	}
}

func TestCheck(t *testing.T) {
	r := &fakeRunner{fail: func(cmd string, _ int) bool { return strings.Contains(cmd, "is-active") }}
	res := Check(context.Background(), newBoards(r), false)
	byName := map[string]Result{}
	for _, x := range res {
		byName[x.Name] = x
	}
	if len(res) != 7 {
		t.Fatalf("want 7 checks, got %d: %+v", len(res), res)
	}
	if byName["Board A relay running"].OK {
		t.Fatal("relay check should fail")
	}
	if !byName["Board B reaches the laptop's iperf3 server"].OK {
		t.Fatal("iperf check should pass")
	}
	if byName["Board A reachable by SSH key"].Detail != "ok" {
		t.Fatalf("detail should be the first output line, got %q", byName["Board A reachable by SSH key"].Detail)
	}
}

func TestCheckStopsWhenBoardAUnreachable(t *testing.T) {
	r := &fakeRunner{fail: func(cmd string, _ int) bool { return cmd == "true" }}
	res := Check(context.Background(), newBoards(r), true)
	if len(res) != 1 || res[0].OK {
		t.Fatalf("want a single failed reachability check, got %+v", res)
	}
}
