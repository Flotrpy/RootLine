// Package board runs commands on the Arduino UNO Q boards over SSH, for the
// unattended hardware campaign.
//
// SSH runs with BatchMode, so it fails at once instead of waiting for a
// password: key-based login must be set up first (docs/HARDWARE.md).
package board

import (
	"context"
	"fmt"
	"os"
	"regexp"
	"strings"
	"time"

	"github.com/flotrpy/rootline/controller/internal/netem"
)

// Boards knows how to reach each board and fills command placeholders.
type Boards struct {
	Runner    netem.Runner
	Hosts     map[string]string // board -> ssh destination, e.g. "A" -> "arduino@192.168.1.250"
	Vars      map[string]string // placeholder -> value
	Timeout   time.Duration     // per attempt
	RetryWait time.Duration
	Sleep     func(context.Context, time.Duration) error
}

// FromEnv reads ROOTLINE_BOARD_A, ROOTLINE_BOARD_B, ROOTLINE_IPERF_SERVER,
// ROOTLINE_HW_TXPOWER_MBM (default 100 = 1 dBm) and
// ROOTLINE_CONTENTION_BITRATE (default 30M).
func FromEnv(getenv func(string) string) *Boards {
	def := func(k, d string) string {
		if v := getenv(k); v != "" {
			return v
		}
		return d
	}
	hosts := map[string]string{}
	for _, b := range []string{"A", "B"} {
		if v := getenv("ROOTLINE_BOARD_" + b); v != "" {
			hosts[b] = v
		}
	}
	vars := map[string]string{
		"txpower_mbm":        def("ROOTLINE_HW_TXPOWER_MBM", "100"),
		"contention_bitrate": def("ROOTLINE_CONTENTION_BITRATE", "30M"),
	}
	if v := getenv("ROOTLINE_IPERF_SERVER"); v != "" {
		vars["iperf_server"] = v
	}
	return &Boards{
		Runner:    netem.ExecRunner{},
		Hosts:     hosts,
		Vars:      vars,
		Timeout:   45 * time.Second,
		RetryWait: 10 * time.Second,
		Sleep:     sleepCtx,
	}
}

// Default reads the process environment.
func Default() *Boards { return FromEnv(os.Getenv) }

func sleepCtx(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}

var placeholder = regexp.MustCompile(`\{([a-z_]+)\}`)

// safeValue keeps placeholder values to characters that cannot change the
// meaning of a shell command.
var safeValue = regexp.MustCompile(`^[A-Za-z0-9._:-]+$`)

// Expand fills {placeholders}; an unknown or unset one is an error.
func Expand(cmd string, vars map[string]string) (string, error) {
	var missing []string
	out := placeholder.ReplaceAllStringFunc(cmd, func(m string) string {
		key := m[1 : len(m)-1]
		v, ok := vars[key]
		if !ok || !safeValue.MatchString(v) {
			missing = append(missing, key)
			return m
		}
		return v
	})
	if len(missing) > 0 {
		return "", fmt.Errorf("unset or unsafe settings for %s (see ROOTLINE_* variables)", strings.Join(missing, ", "))
	}
	return out, nil
}

// Output runs cmd on a board, trying up to attempts times, and returns the
// last attempt's combined output.
func (b *Boards) Output(ctx context.Context, board, cmd string, attempts int) ([]byte, error) {
	host, ok := b.Hosts[board]
	if !ok {
		return nil, fmt.Errorf("board %s: set ROOTLINE_BOARD_%s (e.g. arduino@192.168.1.250)", board, board)
	}
	expanded, err := Expand(cmd, b.Vars)
	if err != nil {
		return nil, err
	}
	if attempts < 1 {
		attempts = 1
	}
	var out []byte
	for i := 1; i <= attempts; i++ {
		actx, cancel := context.WithTimeout(ctx, b.Timeout)
		out, err = b.Runner.Run(actx, "ssh",
			"-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
			"-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=3",
			host, expanded)
		cancel()
		if err == nil || i == attempts || ctx.Err() != nil {
			break
		}
		if serr := b.Sleep(ctx, b.RetryWait); serr != nil {
			return out, serr
		}
	}
	if err != nil {
		return out, fmt.Errorf("board %s: %w", board, err)
	}
	return out, nil
}

// Exec is Output without the output, for the injector.
func (b *Boards) Exec(ctx context.Context, board, cmd string, attempts int) error {
	_, err := b.Output(ctx, board, cmd, attempts)
	return err
}
