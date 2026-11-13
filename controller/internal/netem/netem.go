// Package netem adds and removes tc netem rules inside a container via
// `docker exec`. The target container needs the NET_ADMIN capability and the
// iproute2 tools.
package netem

import (
	"context"
	"fmt"
	"os/exec"
	"strings"
)

// Runner runs an external command. Tests swap in a fake.
type Runner interface {
	Run(ctx context.Context, name string, args ...string) ([]byte, error)
}

// ExecRunner runs commands with os/exec.
type ExecRunner struct{}

// Run implements Runner.
func (ExecRunner) Run(ctx context.Context, name string, args ...string) ([]byte, error) {
	out, err := exec.CommandContext(ctx, name, args...).CombinedOutput()
	if err != nil {
		return out, fmt.Errorf("%s %s: %w: %s", name, strings.Join(args, " "), err, strings.TrimSpace(string(out)))
	}
	return out, nil
}

// Shaper is what the controller needs from netem.
type Shaper interface {
	Loss(ctx context.Context, container string, pct int) error
	Clear(ctx context.Context, container string) error
}

// Netem applies rules to one network device inside containers.
type Netem struct {
	Runner Runner
	Device string // defaults to eth0
}

// New returns a Netem that uses os/exec and eth0.
func New() *Netem { return &Netem{Runner: ExecRunner{}, Device: "eth0"} }

func (n *Netem) dev() string {
	if n.Device == "" {
		return "eth0"
	}
	return n.Device
}

// Loss replaces the root qdisc with netem packet loss of pct percent.
func (n *Netem) Loss(ctx context.Context, container string, pct int) error {
	if pct <= 0 || pct > 100 {
		return fmt.Errorf("loss percent must be in 1..100, got %d", pct)
	}
	_, err := n.Runner.Run(ctx, "docker", "exec", container,
		"tc", "qdisc", "replace", "dev", n.dev(), "root", "netem", "loss", fmt.Sprintf("%d%%", pct))
	return err
}

// Clear removes the root qdisc. Removing a qdisc that is not there is not an
// error, so Clear is safe to call during resets.
func (n *Netem) Clear(ctx context.Context, container string) error {
	out, err := n.Runner.Run(ctx, "docker", "exec", container, "tc", "qdisc", "del", "dev", n.dev(), "root")
	if err != nil && isNoQdisc(string(out)+err.Error()) {
		return nil
	}
	return err
}

func isNoQdisc(msg string) bool {
	msg = strings.ToLower(msg)
	return strings.Contains(msg, "cannot delete qdisc with handle of zero") ||
		strings.Contains(msg, "no such file or directory") ||
		strings.Contains(msg, "invalid handle")
}
