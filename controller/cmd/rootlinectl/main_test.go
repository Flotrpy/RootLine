package main

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func testDeps(t *testing.T) deps {
	t.Helper()
	p := filepath.Join(t.TempDir(), "demo.flagd.json")
	doc := `{"flags":{"adHighCpu":{"state":"ENABLED","variants":{"on":true,"off":false},"defaultVariant":"off"}}}`
	if err := os.WriteFile(p, []byte(doc), 0o644); err != nil {
		t.Fatal(err)
	}
	return deps{cfg: config{FlagdFile: p, LabelsDir: t.TempDir()}}
}

func TestRunCommands(t *testing.T) {
	d := testDeps(t)
	ctx := context.Background()
	tests := []struct {
		args       []string
		wantOut    string
		wantErr    bool
		wantUsage  bool
		wantErrSub string
	}{
		{args: nil, wantOut: "Usage:"},
		{args: []string{"faults"}, wantOut: "toxiBandwidth"},
		{args: []string{"flag", "set", "adHighCpu", "on"}},
		{args: []string{"flag", "get", "adHighCpu"}, wantOut: "on"},
		{args: []string{"flag", "reset", "--all"}},
		{args: []string{"flag", "get", "adHighCpu"}, wantOut: "off"},
		{args: []string{"flag", "set", "adHighCpu", "maybe"}, wantErr: true, wantErrSub: "no variant"},
		{args: []string{"flag"}, wantErr: true, wantUsage: true},
		{args: []string{"toxi", "add", "ad->cart", "latency"}, wantErr: true, wantErrSub: "unknown edge"},
		{args: []string{"incident", "run", "--fault", "nope"}, wantErr: true, wantErrSub: "unknown fault"},
		{args: []string{"bogus"}, wantErr: true, wantUsage: true},
	}
	for _, tt := range tests {
		t.Run(strings.Join(tt.args, " "), func(t *testing.T) {
			var out bytes.Buffer
			err := run(ctx, tt.args, &out, d)
			if (err != nil) != tt.wantErr {
				t.Fatalf("err = %v, wantErr %v", err, tt.wantErr)
			}
			if tt.wantUsage && !errors.Is(err, errUsage) {
				t.Fatalf("want usage error, got %v", err)
			}
			if tt.wantErrSub != "" && !strings.Contains(err.Error(), tt.wantErrSub) {
				t.Fatalf("err %q missing %q", err, tt.wantErrSub)
			}
			if !strings.Contains(out.String(), tt.wantOut) {
				t.Fatalf("output %q missing %q", out.String(), tt.wantOut)
			}
		})
	}
}

func TestParseToxic(t *testing.T) {
	tx, err := parseToxic("reset_peer", []string{"toxicity=0.2", "timeout=0"})
	if err != nil {
		t.Fatal(err)
	}
	if tx.Toxicity != 0.2 || tx.Attributes["timeout"] != 0 || tx.Name != "manual-reset_peer" {
		t.Fatalf("toxic = %+v", tx)
	}
	for _, bad := range [][]string{{"latency"}, {"toxicity=2"}, {"rate=fast"}} {
		if _, err := parseToxic("latency", bad); err == nil {
			t.Errorf("%v: want error", bad)
		}
	}
}
