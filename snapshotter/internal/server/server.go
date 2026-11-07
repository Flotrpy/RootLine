// Package server receives OTLP over HTTP and freezes telemetry windows into
// snapshot directories on request.
package server

import (
	"bufio"
	"compress/gzip"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"runtime/debug"
	"strconv"
	"strings"
	"sync"
	"time"

	collogs "go.opentelemetry.io/proto/otlp/collector/logs/v1"
	colmetrics "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	coltrace "go.opentelemetry.io/proto/otlp/collector/trace/v1"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	"github.com/flotrpy/rootline/snapshotter/internal/buffer"
	"github.com/flotrpy/rootline/snapshotter/internal/parquetw"
	"github.com/flotrpy/rootline/snapshotter/internal/rows"
)

// MaxBody caps one OTLP request after decompression.
const MaxBody = 32 << 20

// Manifest is manifest.json, as in the data contract.
type Manifest struct {
	IncidentID        string            `json:"incident_id"`
	DemoGitTag        string            `json:"demo_git_tag"`
	ImageDigests      map[string]string `json:"image_digests"`
	T0UnixMs          int64             `json:"t0_unix_ms"`
	WindowMs          int64             `json:"window_ms"`
	CollectorVersion  string            `json:"collector_version"`
	SnapshotterGitSHA string            `json:"snapshotter_git_sha"`
	HostRAMGB         int               `json:"host_ram_gb"`
}

// Request matches the controller's incident.SnapshotRequest.
type Request struct {
	IncidentID string `json:"incident_id"`
	T0UnixMs   int64  `json:"t0_unix_ms"`
	StartMs    int64  `json:"start_unix_ms"`
	WindowMs   int64  `json:"window_ms"`
}

// Result is the /snapshot response.
type Result struct {
	Dir     string `json:"dir"`
	Spans   int    `json:"spans"`
	Metrics int    `json:"metrics"`
	Logs    int    `json:"logs"`
}

// Config holds static manifest fields and output settings.
type Config struct {
	OutDir           string
	DemoGitTag       string
	ImageDigests     map[string]string
	CollectorVersion string
	// Settle is how long /snapshot waits before reading the buffer, so
	// telemetry still in the collector's batch queue arrives first.
	Settle time.Duration
}

// Server owns the buffer and the metric flattener.
type Server struct {
	Cfg    Config
	Buf    *buffer.Buffer
	Flat   *rows.Flattener
	Log    *slog.Logger
	Sleep  func(time.Duration)
	snapMu sync.Mutex
}

// New returns a Server.
func New(cfg Config, buf *buffer.Buffer, log *slog.Logger) *Server {
	return &Server{Cfg: cfg, Buf: buf, Flat: rows.NewFlattener(), Log: log, Sleep: time.Sleep}
}

// OTLPHandler serves /v1/traces, /v1/metrics and /v1/logs.
func (s *Server) OTLPHandler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/traces", func(w http.ResponseWriter, r *http.Request) {
		req := &coltrace.ExportTraceServiceRequest{}
		if !s.decode(w, r, req) {
			return
		}
		s.Buf.AddSpans(rows.Traces(req))
		s.reply(w, r, &coltrace.ExportTraceServiceResponse{})
	})
	mux.HandleFunc("POST /v1/metrics", func(w http.ResponseWriter, r *http.Request) {
		req := &colmetrics.ExportMetricsServiceRequest{}
		if !s.decode(w, r, req) {
			return
		}
		s.Buf.AddMetrics(s.Flat.Metrics(req))
		s.reply(w, r, &colmetrics.ExportMetricsServiceResponse{})
	})
	mux.HandleFunc("POST /v1/logs", func(w http.ResponseWriter, r *http.Request) {
		req := &collogs.ExportLogsServiceRequest{}
		if !s.decode(w, r, req) {
			return
		}
		s.Buf.AddLogs(rows.Logs(req))
		s.reply(w, r, &collogs.ExportLogsServiceResponse{})
	})
	return mux
}

func isJSON(r *http.Request) bool {
	return strings.HasPrefix(r.Header.Get("Content-Type"), "application/json")
}

func (s *Server) decode(w http.ResponseWriter, r *http.Request, m proto.Message) bool {
	var body io.Reader = r.Body
	if strings.EqualFold(r.Header.Get("Content-Encoding"), "gzip") {
		gz, err := gzip.NewReader(r.Body)
		if err != nil {
			http.Error(w, "bad gzip body", http.StatusBadRequest)
			return false
		}
		defer func() { _ = gz.Close() }()
		body = gz
	}
	raw, err := io.ReadAll(io.LimitReader(body, MaxBody+1))
	if err != nil {
		http.Error(w, "read body: "+err.Error(), http.StatusBadRequest)
		return false
	}
	if len(raw) > MaxBody {
		http.Error(w, "body too large", http.StatusRequestEntityTooLarge)
		return false
	}
	if isJSON(r) {
		err = protojson.UnmarshalOptions{DiscardUnknown: true}.Unmarshal(raw, m)
	} else {
		err = proto.Unmarshal(raw, m)
	}
	if err != nil {
		http.Error(w, "decode: "+err.Error(), http.StatusBadRequest)
		return false
	}
	return true
}

func (s *Server) reply(w http.ResponseWriter, r *http.Request, m proto.Message) {
	var b []byte
	if isJSON(r) {
		w.Header().Set("Content-Type", "application/json")
		b, _ = protojson.Marshal(m)
	} else {
		w.Header().Set("Content-Type", "application/x-protobuf")
		b, _ = proto.Marshal(m)
	}
	_, _ = w.Write(b)
}

// ControlHandler serves POST /snapshot, GET /health and GET /stats.
func (s *Server) ControlHandler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("GET /stats", func(w http.ResponseWriter, _ *http.Request) {
		sp, m, l := s.Buf.Counts()
		writeJSON(w, http.StatusOK, map[string]int{"spans": sp, "metrics": m, "logs": l})
	})
	mux.HandleFunc("POST /snapshot", s.postSnapshot)
	return mux
}

var incidentRe = regexp.MustCompile(`^[A-Za-z]+-r[1-9][0-9]*$`)

// ErrExists is returned when a snapshot directory already exists.
// Snapshots are never overwritten.
var ErrExists = errors.New("snapshot already exists")

func (s *Server) postSnapshot(w http.ResponseWriter, r *http.Request) {
	var req Request
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4096)).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad json"})
		return
	}
	if !incidentRe.MatchString(req.IncidentID) || req.WindowMs <= 0 || req.T0UnixMs <= 0 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request"})
		return
	}
	res, err := s.Snapshot(req)
	switch {
	case errors.Is(err, ErrExists):
		writeJSON(w, http.StatusConflict, map[string]string{"error": err.Error()})
	case err != nil:
		s.Log.Error("snapshot failed", "incident", req.IncidentID, "err", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
	default:
		writeJSON(w, http.StatusOK, res)
	}
}

// Snapshot freezes [StartMs, StartMs+WindowMs) into OutDir/<incident_id>.
// Files are written into a temp directory that is renamed into place only
// when complete, so a crash never leaves a half-written snapshot.
func (s *Server) Snapshot(req Request) (Result, error) {
	s.snapMu.Lock()
	defer s.snapMu.Unlock()
	final := filepath.Join(s.Cfg.OutDir, req.IncidentID)
	if _, err := os.Stat(final); err == nil {
		return Result{}, fmt.Errorf("%w: %s", ErrExists, final)
	} else if !errors.Is(err, fs.ErrNotExist) {
		return Result{}, err
	}
	if s.Cfg.Settle > 0 {
		s.Sleep(s.Cfg.Settle)
	}
	start := req.StartMs
	if start == 0 {
		start = req.T0UnixMs - req.WindowMs/2
	}
	spans, metrics, logs := s.Buf.Window(start, start+req.WindowMs)

	if err := os.MkdirAll(s.Cfg.OutDir, 0o755); err != nil {
		return Result{}, err
	}
	tmp, err := os.MkdirTemp(s.Cfg.OutDir, "."+req.IncidentID+".tmp-")
	if err != nil {
		return Result{}, err
	}
	defer func() { _ = os.RemoveAll(tmp) }()

	if err := parquetw.WriteSpans(filepath.Join(tmp, "spans.parquet"), spans); err != nil {
		return Result{}, err
	}
	if err := parquetw.WriteMetrics(filepath.Join(tmp, "metrics.parquet"), metrics); err != nil {
		return Result{}, err
	}
	if err := parquetw.WriteLogs(filepath.Join(tmp, "logs.parquet"), logs); err != nil {
		return Result{}, err
	}
	digests := s.Cfg.ImageDigests
	if digests == nil {
		digests = map[string]string{}
	}
	m := Manifest{
		IncidentID:        req.IncidentID,
		DemoGitTag:        s.Cfg.DemoGitTag,
		ImageDigests:      digests,
		T0UnixMs:          req.T0UnixMs,
		WindowMs:          req.WindowMs,
		CollectorVersion:  s.Cfg.CollectorVersion,
		SnapshotterGitSHA: GitSHA(),
		HostRAMGB:         HostRAMGB(),
	}
	mb, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		return Result{}, err
	}
	if err := os.WriteFile(filepath.Join(tmp, "manifest.json"), append(mb, '\n'), 0o644); err != nil {
		return Result{}, err
	}
	if err := os.Rename(tmp, final); err != nil {
		return Result{}, err
	}
	s.Log.Info("snapshot written", "dir", final, "spans", len(spans), "metrics", len(metrics), "logs", len(logs))
	return Result{Dir: final, Spans: len(spans), Metrics: len(metrics), Logs: len(logs)}, nil
}

// GitSHA reads the VCS revision Go embeds at build time.
func GitSHA() string {
	info, ok := debug.ReadBuildInfo()
	if !ok {
		return "unknown"
	}
	sha, dirty := "unknown", false
	for _, s := range info.Settings {
		switch s.Key {
		case "vcs.revision":
			sha = s.Value
		case "vcs.modified":
			dirty = s.Value == "true"
		}
	}
	if dirty {
		sha += "-dirty"
	}
	return sha
}

// HostRAMGB reads MemTotal from /proc/meminfo, rounded to whole GB.
func HostRAMGB() int {
	f, err := os.Open("/proc/meminfo")
	if err != nil {
		return 0
	}
	defer func() { _ = f.Close() }()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		fields := strings.Fields(sc.Text())
		if len(fields) >= 2 && fields[0] == "MemTotal:" {
			kb, err := strconv.ParseInt(fields[1], 10, 64)
			if err != nil {
				return 0
			}
			return int((kb + 512*1024) / (1024 * 1024))
		}
	}
	return 0
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}
