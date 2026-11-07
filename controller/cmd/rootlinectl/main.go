// Command rootlinectl injects faults into the OpenTelemetry Demo, runs the
// incident protocol and campaigns, executes remediation trials and serves
// the panel API.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"text/tabwriter"
	"time"

	"github.com/flotrpy/rootline/controller/internal/api"
	"github.com/flotrpy/rootline/controller/internal/catalog"
	"github.com/flotrpy/rootline/controller/internal/flagd"
	"github.com/flotrpy/rootline/controller/internal/health"
	"github.com/flotrpy/rootline/controller/internal/incident"
	"github.com/flotrpy/rootline/controller/internal/inject"
	"github.com/flotrpy/rootline/controller/internal/netem"
	"github.com/flotrpy/rootline/controller/internal/remediate"
	"github.com/flotrpy/rootline/controller/internal/toxi"
)

const usage = `rootlinectl - Rootline fault controller

Usage:
  rootlinectl faults
  rootlinectl flag set <name> <variant> | flag get <name> | flag reset --all
  rootlinectl toxi add <edge> <toxic-type> [toxicity=0.2] [key=int ...]
  rootlinectl toxi clear <edge>
  rootlinectl netem loss <container> <pct> | netem clear <container>
  rootlinectl incident run --fault <f> --replica <n> [--warmup]
  rootlinectl campaign --plan plans/pilot.yaml [--progress <file>]
  rootlinectl remediate --action <type> --target <t> --incident <id> [--jsonl <file>]
  rootlinectl serve [--addr :8088]

Environment (defaults in brackets):
  ROOTLINE_FLAGD_FILE  [opentelemetry-demo/src/flagd/demo.flagd.json]
  TOXIPROXY_URLS       [payment=http://localhost:8474,product-catalog=http://localhost:8475]
  PROMETHEUS_URL       [http://localhost:9090]
  SNAPSHOTTER_URL      [http://localhost:8089]
  ROOTLINE_LABELS_DIR  [data/labels]
`

// config is read from the environment.
type config struct {
	FlagdFile, ToxiURLs, PromURL, SnapURL, LabelsDir string
}

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func loadConfig() config {
	return config{
		FlagdFile: env("ROOTLINE_FLAGD_FILE", "opentelemetry-demo/src/flagd/demo.flagd.json"),
		ToxiURLs:  env("TOXIPROXY_URLS", "payment=http://localhost:8474,product-catalog=http://localhost:8475"),
		PromURL:   env("PROMETHEUS_URL", "http://localhost:9090"),
		SnapURL:   env("SNAPSHOTTER_URL", "http://localhost:8089"),
		LabelsDir: env("ROOTLINE_LABELS_DIR", "data/labels"),
	}
}

// deps are built lazily so commands that need nothing (faults, help) work
// without any service running.
type deps struct {
	cfg config
	log *slog.Logger
}

func (d deps) injector() *inject.Injector {
	router, err := toxi.ParseRouter(d.cfg.ToxiURLs)
	if err != nil {
		// Commands that touch Toxiproxy report the problem on first use.
		router = toxi.Router{}
		d.log.Warn("TOXIPROXY_URLS", "err", err)
	}
	return &inject.Injector{
		Flags: flagd.NewStore(d.cfg.FlagdFile),
		Toxi:  router,
		Netem: netem.New(),
		Edges: inject.DefaultEdges,
	}
}

func (d deps) runner() *incident.Runner {
	return &incident.Runner{
		Injector:    d.injector(),
		Probe:       health.NewPrometheus(d.cfg.PromURL),
		Snapshotter: &incident.HTTPSnapshotter{Base: d.cfg.SnapURL},
		Clock:       incident.RealClock{},
		Protocol:    incident.Pilot,
		LabelsDir:   d.cfg.LabelsDir,
		Log:         d.log,
	}
}

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	d := deps{cfg: loadConfig(), log: slog.New(slog.NewTextHandler(os.Stderr, nil))}
	if err := run(ctx, os.Args[1:], os.Stdout, d); err != nil {
		fmt.Fprintln(os.Stderr, "rootlinectl:", err)
		os.Exit(1)
	}
}

var errUsage = errors.New("see 'rootlinectl help'")

func run(ctx context.Context, args []string, out io.Writer, d deps) error {
	if len(args) == 0 || args[0] == "help" || args[0] == "-h" || args[0] == "--help" {
		_, err := fmt.Fprint(out, usage)
		return err
	}
	cmd, rest := args[0], args[1:]
	switch cmd {
	case "faults":
		return listFaults(out)
	case "flag":
		return flagCmd(rest, out, d.injector().Flags)
	case "toxi":
		return toxiCmd(ctx, rest, d.injector().Toxi)
	case "netem":
		return netemCmd(ctx, rest, d.injector().Netem)
	case "incident":
		return incidentCmd(ctx, rest, out, d)
	case "campaign":
		return campaignCmd(ctx, rest, out, d)
	case "remediate":
		return remediateCmd(ctx, rest, out, d)
	case "serve":
		return serveCmd(ctx, rest, d)
	}
	return fmt.Errorf("unknown command %q: %w", cmd, errUsage)
}

func listFaults(out io.Writer) error {
	tw := tabwriter.NewWriter(out, 0, 4, 2, ' ', 0)
	_, _ = fmt.Fprintln(tw, "FAULT\tKIND\tLAYER\tSERVICE\tCATEGORY\tEDGE")
	for _, f := range catalog.All() {
		_, _ = fmt.Fprintf(tw, "%s\t%s\t%s\t%s\t%s\t%s\n", f.Name, f.Kind, f.Layer, f.Service, f.Category, f.Edge)
	}
	return tw.Flush()
}

func flagCmd(args []string, out io.Writer, f flagd.Flags) error {
	switch {
	case len(args) == 3 && args[0] == "set":
		return f.Set(args[1], args[2])
	case len(args) == 2 && args[0] == "get":
		v, err := f.Get(args[1])
		if err != nil {
			return err
		}
		_, err = fmt.Fprintln(out, v)
		return err
	case len(args) == 2 && args[0] == "reset" && args[1] == "--all":
		return f.ResetAll()
	}
	return fmt.Errorf("flag: bad arguments: %w", errUsage)
}

func edgeProxy(edge string) (inject.Edge, error) {
	e, ok := inject.DefaultEdges[edge]
	if !ok {
		return inject.Edge{}, fmt.Errorf("unknown edge %q (have %s, %s)", edge, catalog.EdgeCheckoutPayment, catalog.EdgeFrontendCatalog)
	}
	return e, nil
}

// parseToxic turns "latency latency=300 jitter=60 toxicity=0.5" into a toxic.
func parseToxic(typ string, params []string) (toxi.Toxic, error) {
	t := toxi.Toxic{Name: "manual-" + typ, Type: typ, Toxicity: 1, Attributes: map[string]int{}}
	for _, p := range params {
		k, v, ok := strings.Cut(p, "=")
		if !ok {
			return t, fmt.Errorf("param %q is not key=value", p)
		}
		if k == "toxicity" {
			f, err := strconv.ParseFloat(v, 64)
			if err != nil || f < 0 || f > 1 {
				return t, fmt.Errorf("toxicity must be in 0..1, got %q", v)
			}
			t.Toxicity = f
			continue
		}
		n, err := strconv.Atoi(v)
		if err != nil {
			return t, fmt.Errorf("param %s: %w", k, err)
		}
		t.Attributes[k] = n
	}
	return t, nil
}

func toxiCmd(ctx context.Context, args []string, p toxi.Proxies) error {
	if len(args) >= 3 && args[0] == "add" {
		e, err := edgeProxy(args[1])
		if err != nil {
			return err
		}
		t, err := parseToxic(args[2], args[3:])
		if err != nil {
			return err
		}
		return p.AddToxic(ctx, e.Proxy, t)
	}
	if len(args) == 2 && args[0] == "clear" {
		e, err := edgeProxy(args[1])
		if err != nil {
			return err
		}
		return toxi.ClearAll(ctx, p, e.Proxy)
	}
	return fmt.Errorf("toxi: bad arguments: %w", errUsage)
}

func netemCmd(ctx context.Context, args []string, n netem.Shaper) error {
	if len(args) == 3 && args[0] == "loss" {
		pct, err := strconv.Atoi(strings.TrimSuffix(args[2], "%"))
		if err != nil {
			return fmt.Errorf("netem loss: %w", err)
		}
		return n.Loss(ctx, args[1], pct)
	}
	if len(args) == 2 && args[0] == "clear" {
		return n.Clear(ctx, args[1])
	}
	return fmt.Errorf("netem: bad arguments: %w", errUsage)
}

func printJSON(out io.Writer, v any) error {
	enc := json.NewEncoder(out)
	enc.SetIndent("", "  ")
	enc.SetEscapeHTML(false)
	return enc.Encode(v)
}

func incidentCmd(ctx context.Context, args []string, out io.Writer, d deps) error {
	if len(args) == 0 || args[0] != "run" {
		return fmt.Errorf("incident: bad arguments: %w", errUsage)
	}
	fs := flag.NewFlagSet("incident run", flag.ContinueOnError)
	fault := fs.String("fault", "", "fault name")
	replica := fs.Int("replica", 1, "replica number")
	warmup := fs.Bool("warmup", false, "add the 10-minute warm-up")
	if err := fs.Parse(args[1:]); err != nil {
		return err
	}
	f, ok := catalog.Lookup(*fault)
	if !ok {
		return fmt.Errorf("unknown fault %q (see 'rootlinectl faults')", *fault)
	}
	if *replica < 1 {
		return errors.New("replica must be >= 1")
	}
	res, err := d.runner().Run(ctx, f, *replica, *warmup)
	if err != nil {
		return err
	}
	return printJSON(out, res)
}

func campaignCmd(ctx context.Context, args []string, out io.Writer, d deps) error {
	fs := flag.NewFlagSet("campaign", flag.ContinueOnError)
	planPath := fs.String("plan", "plans/pilot.yaml", "plan file")
	progress := fs.String("progress", "", "progress file (default data/<plan name>-progress.json)")
	if err := fs.Parse(args); err != nil {
		return err
	}
	plan, err := incident.LoadPlan(*planPath)
	if err != nil {
		return err
	}
	if *progress == "" {
		*progress = "data/" + plan.Name + "-progress.json"
	}
	prog, err := d.runner().Campaign(ctx, plan, *progress)
	if prog != nil {
		_, _ = fmt.Fprintf(out, "campaign %s: %d done, %d failed, %d pending (progress in %s)\n",
			plan.Name, len(prog.Done), len(prog.Failed), len(prog.Pending), *progress)
	}
	return err
}

func remediateCmd(ctx context.Context, args []string, out io.Writer, d deps) error {
	fs := flag.NewFlagSet("remediate", flag.ContinueOnError)
	action := fs.String("action", "", "restart | disable_feature | clear_network_fault | no_action")
	target := fs.String("target", "", "service or edge")
	id := fs.String("incident", "", "incident id, e.g. paymentFailure-r1")
	jsonl := fs.String("jsonl", "", "also append the result as one JSON line to this file")
	if err := fs.Parse(args); err != nil {
		return err
	}
	tr := &remediate.Trial{
		Executor: &remediate.Executor{Injector: d.injector(), Runner: netem.ExecRunner{}},
		Probe:    health.NewPrometheus(d.cfg.PromURL),
		Clock:    incident.RealClock{},
		Protocol: incident.Pilot,
	}
	res, err := tr.Run(ctx, *id, remediate.Action{Type: *action, Target: *target})
	if err != nil {
		return err
	}
	if *jsonl != "" {
		if err := appendJSONL(*jsonl, res); err != nil {
			return err
		}
	}
	return printJSON(out, res)
}

// appendJSONL appends v as one compact JSON line, the format the analysis
// reads remediation trials from.
func appendJSONL(path string, v any) error {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return err
	}
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	if _, err := f.Write(buf.Bytes()); err != nil {
		_ = f.Close()
		return err
	}
	return f.Close()
}

func serveCmd(ctx context.Context, args []string, d deps) error {
	fs := flag.NewFlagSet("serve", flag.ContinueOnError)
	addr := fs.String("addr", ":8088", "listen address")
	if err := fs.Parse(args); err != nil {
		return err
	}
	srv := &http.Server{Addr: *addr, Handler: api.New(d.injector()).Handler(), ReadHeaderTimeout: 5 * time.Second}
	go func() {
		<-ctx.Done()
		sctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = srv.Shutdown(sctx)
	}()
	d.log.Info("serving", "addr", *addr)
	if err := srv.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
		return err
	}
	return nil
}
