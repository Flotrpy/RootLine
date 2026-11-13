// Package operator asks a person to perform the physical steps of a manual
// (hardware) fault, waits for confirmation and timestamps it.
package operator

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"
)

// Step is one confirmed operator action, appended to the operator log.
type Step struct {
	Fault           string `json:"fault"`
	Phase           string `json:"phase"` // "inject" or "clear"
	Instruction     string `json:"instruction"`
	ConfirmedUnixMs int64  `json:"confirmed_unix_ms"`
}

// Console prompts on a terminal and appends each confirmation to a JSONL log.
type Console struct {
	In  io.Reader
	Out io.Writer
	Log string // path of the JSONL log; empty disables logging
	Now func() time.Time

	lines chan string
}

// NewConsole prompts on stdin/stderr and logs to path.
func NewConsole(path string) *Console {
	return &Console{In: os.Stdin, Out: os.Stderr, Log: path, Now: time.Now}
}

func (c *Console) readLines() {
	c.lines = make(chan string)
	go func() {
		sc := bufio.NewScanner(c.In)
		for sc.Scan() {
			c.lines <- sc.Text()
		}
		close(c.lines)
	}()
}

// Do prints the instruction, waits for Enter, and records the time of
// confirmation. It returns early if ctx is cancelled.
func (c *Console) Do(ctx context.Context, fault, phase, instruction string) error {
	if c.lines == nil {
		c.readLines()
	}
	_, _ = fmt.Fprintf(c.Out, "\n>>> OPERATOR [%s %s]\n    %s\n    Press Enter when done (Ctrl-C aborts and clears the run).\n", fault, phase, instruction)
	select {
	case <-ctx.Done():
		return ctx.Err()
	case _, ok := <-c.lines:
		if !ok {
			return fmt.Errorf("operator input closed before %s %s was confirmed", fault, phase)
		}
	}
	step := Step{Fault: fault, Phase: phase, Instruction: instruction, ConfirmedUnixMs: c.Now().UnixMilli()}
	_, _ = fmt.Fprintf(c.Out, "    confirmed at %d\n", step.ConfirmedUnixMs)
	return c.append(step)
}

func (c *Console) append(s Step) error {
	if c.Log == "" {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(c.Log), 0o755); err != nil {
		return err
	}
	f, err := os.OpenFile(c.Log, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	b, err := json.Marshal(s)
	if err != nil {
		_ = f.Close()
		return err
	}
	if _, err := f.Write(append(b, '\n')); err != nil {
		_ = f.Close()
		return err
	}
	return f.Close()
}
