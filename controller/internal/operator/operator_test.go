package operator

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestConsoleConfirmsAndLogs(t *testing.T) {
	log := filepath.Join(t.TempDir(), "hw", "operator-log.jsonl")
	var out bytes.Buffer
	c := &Console{In: strings.NewReader("\n\n"), Out: &out, Log: log, Now: func() time.Time { return time.UnixMilli(42) }}
	ctx := context.Background()
	if err := c.Do(ctx, "hwPowerCut", "inject", "Cut power for 30 s."); err != nil {
		t.Fatal(err)
	}
	if err := c.Do(ctx, "hwPowerCut", "clear", "Check the relay."); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "Cut power for 30 s.") {
		t.Fatalf("instruction not shown: %q", out.String())
	}
	raw, err := os.ReadFile(log)
	if err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(string(raw)), "\n")
	if len(lines) != 2 {
		t.Fatalf("want 2 log lines, got %d", len(lines))
	}
	var s Step
	if err := json.Unmarshal([]byte(lines[1]), &s); err != nil {
		t.Fatal(err)
	}
	if s.Phase != "clear" || s.ConfirmedUnixMs != 42 {
		t.Fatalf("step = %+v", s)
	}
}

func TestConsoleCancelAndClosedInput(t *testing.T) {
	pr, pw := io.Pipe()
	defer func() { _ = pw.Close() }()
	c := &Console{In: pr, Out: io.Discard, Now: time.Now}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := c.Do(ctx, "f", "inject", "x"); err == nil {
		t.Fatal("want cancellation error")
	}
	closed := &Console{In: strings.NewReader(""), Out: io.Discard, Now: time.Now}
	if err := closed.Do(context.Background(), "f", "inject", "x"); err == nil {
		t.Fatal("want error when input closes")
	}
}
