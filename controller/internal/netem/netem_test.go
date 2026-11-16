package netem

import (
	"context"
	"errors"
	"slices"
	"strings"
	"testing"
)

type call struct {
	name string
	args []string
}

type fakeRunner struct {
	calls []call
	out   string
	err   error
}

func (f *fakeRunner) Run(_ context.Context, name string, args ...string) ([]byte, error) {
	f.calls = append(f.calls, call{name, args})
	return []byte(f.out), f.err
}

func TestLoss(t *testing.T) {
	tests := []struct {
		name    string
		pct     int
		want    []string
		wantErr bool
	}{
		{"five percent", 5, []string{"exec", "netem-catalog", "tc", "qdisc", "replace", "dev", "eth0", "root", "netem", "loss", "5%"}, false},
		{"zero rejected", 0, nil, true},
		{"over 100 rejected", 101, nil, true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := &fakeRunner{}
			n := &Netem{Runner: r}
			err := n.Loss(context.Background(), "netem-catalog", tt.pct)
			if (err != nil) != tt.wantErr {
				t.Fatalf("err = %v", err)
			}
			if tt.wantErr {
				if len(r.calls) != 0 {
					t.Fatal("no command should run on invalid input")
				}
				return
			}
			if len(r.calls) != 1 || r.calls[0].name != "docker" || !slices.Equal(r.calls[0].args, tt.want) {
				t.Fatalf("calls = %+v", r.calls)
			}
		})
	}
}

func TestClear(t *testing.T) {
	tests := []struct {
		name    string
		out     string
		err     error
		wantErr bool
	}{
		{"removed", "", nil, false},
		{"nothing to remove", "Error: Cannot delete qdisc with handle of zero.", errors.New("exit status 2"), false},
		{"docker down", "", errors.New("cannot connect to the Docker daemon"), true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r := &fakeRunner{out: tt.out, err: tt.err}
			n := &Netem{Runner: r, Device: "eth1"}
			err := n.Clear(context.Background(), "c")
			if (err != nil) != tt.wantErr {
				t.Fatalf("err = %v, wantErr %v", err, tt.wantErr)
			}
			if got := strings.Join(r.calls[0].args, " "); got != "exec c tc qdisc del dev eth1 root" {
				t.Fatalf("args = %q", got)
			}
		})
	}
}
