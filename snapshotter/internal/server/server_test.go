package server

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"flag"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/apache/arrow-go/v18/arrow/memory"
	"github.com/apache/arrow-go/v18/parquet/file"
	"github.com/apache/arrow-go/v18/parquet/pqarrow"
	collogs "go.opentelemetry.io/proto/otlp/collector/logs/v1"
	colmetrics "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	coltrace "go.opentelemetry.io/proto/otlp/collector/trace/v1"
	commonpb "go.opentelemetry.io/proto/otlp/common/v1"
	logspb "go.opentelemetry.io/proto/otlp/logs/v1"
	metricspb "go.opentelemetry.io/proto/otlp/metrics/v1"
	resourcepb "go.opentelemetry.io/proto/otlp/resource/v1"
	tracepb "go.opentelemetry.io/proto/otlp/trace/v1"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	"github.com/flotrpy/rootline/snapshotter/internal/buffer"
)

var update = flag.Bool("update", false, "rewrite testdata/golden.json and the fixture snapshot")

// Fixed fixture times: T0 and a 10-minute window around it.
const (
	t0Ms     = int64(1_800_000_000_000)
	windowMs = int64(600_000)
)

func ns(ms int64) uint64 { return uint64(ms) * 1_000_000 }

func resource(svc string) *resourcepb.Resource {
	return &resourcepb.Resource{Attributes: []*commonpb.KeyValue{
		{Key: "service.name", Value: &commonpb.AnyValue{Value: &commonpb.AnyValue_StringValue{StringValue: svc}}},
	}}
}

func str(s string) *commonpb.AnyValue {
	return &commonpb.AnyValue{Value: &commonpb.AnyValue_StringValue{StringValue: s}}
}

func fixtureTraces() *coltrace.ExportTraceServiceRequest {
	tid := []byte{0xde, 0xad, 0xbe, 0xef, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1}
	return &coltrace.ExportTraceServiceRequest{ResourceSpans: []*tracepb.ResourceSpans{
		{Resource: resource("checkout"), ScopeSpans: []*tracepb.ScopeSpans{{Spans: []*tracepb.Span{
			{TraceId: tid, SpanId: []byte{1, 0, 0, 0, 0, 0, 0, 1}, Name: "oteldemo.CheckoutService/PlaceOrder",
				StartTimeUnixNano: ns(t0Ms + 1000), EndTimeUnixNano: ns(t0Ms + 1900),
				Status: &tracepb.Status{Code: tracepb.Status_STATUS_CODE_ERROR}},
		}}}},
		{Resource: resource("payment"), ScopeSpans: []*tracepb.ScopeSpans{{Spans: []*tracepb.Span{
			{TraceId: tid, SpanId: []byte{2, 0, 0, 0, 0, 0, 0, 2}, ParentSpanId: []byte{1, 0, 0, 0, 0, 0, 0, 1},
				Name: "oteldemo.PaymentService/Charge", StartTimeUnixNano: ns(t0Ms + 1010), EndTimeUnixNano: ns(t0Ms + 1880),
				Status:     &tracepb.Status{Code: tracepb.Status_STATUS_CODE_ERROR},
				Attributes: []*commonpb.KeyValue{{Key: "app.payment.amount", Value: str("42.00")}}},
			// Outside the window: must not be written.
			{TraceId: tid, SpanId: []byte{3, 0, 0, 0, 0, 0, 0, 3}, Name: "late",
				StartTimeUnixNano: ns(t0Ms + windowMs), EndTimeUnixNano: ns(t0Ms + windowMs + 5)},
		}}}},
	}}
}

func fixtureMetrics() *colmetrics.ExportMetricsServiceRequest {
	sum := func(ts int64, v float64, status string) *metricspb.NumberDataPoint {
		return &metricspb.NumberDataPoint{TimeUnixNano: ns(ts), Value: &metricspb.NumberDataPoint_AsDouble{AsDouble: v},
			Attributes: []*commonpb.KeyValue{{Key: "status.code", Value: str(status)}}}
	}
	hist := func(ts int64, counts []uint64) *metricspb.HistogramDataPoint {
		var c uint64
		for _, x := range counts {
			c += x
		}
		return &metricspb.HistogramDataPoint{TimeUnixNano: ns(ts), Count: c, ExplicitBounds: []float64{10, 100, 1000}, BucketCounts: counts}
	}
	cum := metricspb.AggregationTemporality_AGGREGATION_TEMPORALITY_CUMULATIVE
	return &colmetrics.ExportMetricsServiceRequest{ResourceMetrics: []*metricspb.ResourceMetrics{{
		Resource: resource("payment"),
		ScopeMetrics: []*metricspb.ScopeMetrics{{Metrics: []*metricspb.Metric{
			{Name: "traces.span.metrics.calls", Data: &metricspb.Metric_Sum{Sum: &metricspb.Sum{
				IsMonotonic: true, AggregationTemporality: cum,
				DataPoints: []*metricspb.NumberDataPoint{
					sum(t0Ms-60_000, 100, "STATUS_CODE_UNSET"), sum(t0Ms+60_000, 160, "STATUS_CODE_UNSET"),
					sum(t0Ms-60_000, 0, "STATUS_CODE_ERROR"), sum(t0Ms+60_000, 30, "STATUS_CODE_ERROR"),
				},
			}}},
			{Name: "traces.span.metrics.duration", Data: &metricspb.Metric_Histogram{Histogram: &metricspb.Histogram{
				AggregationTemporality: cum,
				DataPoints:             []*metricspb.HistogramDataPoint{hist(t0Ms-60_000, []uint64{90, 10, 0, 0}), hist(t0Ms+60_000, []uint64{120, 10, 30, 0})},
			}}},
			{Name: "process.memory.usage", Data: &metricspb.Metric_Gauge{Gauge: &metricspb.Gauge{
				DataPoints: []*metricspb.NumberDataPoint{{TimeUnixNano: ns(t0Ms), Value: &metricspb.NumberDataPoint_AsInt{AsInt: 104857600}}},
			}}},
		}}},
	}}}
}

func fixtureLogs() *collogs.ExportLogsServiceRequest {
	return &collogs.ExportLogsServiceRequest{ResourceLogs: []*logspb.ResourceLogs{{
		Resource: resource("payment"),
		ScopeLogs: []*logspb.ScopeLogs{{LogRecords: []*logspb.LogRecord{
			{TimeUnixNano: ns(t0Ms + 1500), SeverityText: "ERROR", Body: str("Payment request failed. Invalid token."),
				TraceId: []byte{0xde, 0xad, 0xbe, 0xef, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1}},
			{ObservedTimeUnixNano: ns(t0Ms - 30_000), SeverityNumber: logspb.SeverityNumber_SEVERITY_NUMBER_INFO, Body: str("charged card")},
		}}},
	}}}
}

func post(t *testing.T, url string, m proto.Message, asJSON bool) {
	t.Helper()
	var body []byte
	var err error
	ct := "application/x-protobuf"
	if asJSON {
		body, err = protojson.Marshal(m)
		ct = "application/json"
	} else {
		body, err = proto.Marshal(m)
	}
	if err != nil {
		t.Fatal(err)
	}
	var gz bytes.Buffer
	w := gzip.NewWriter(&gz)
	_, _ = w.Write(body)
	_ = w.Close()
	req, _ := http.NewRequest(http.MethodPost, url, &gz)
	req.Header.Set("Content-Type", ct)
	req.Header.Set("Content-Encoding", "gzip")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode != 200 {
		msg, _ := io.ReadAll(resp.Body)
		t.Fatalf("POST %s: %d %s", url, resp.StatusCode, msg)
	}
}

type parquetSummary struct {
	Schema string `json:"schema"`
	Rows   int64  `json:"rows"`
}

func summarise(t *testing.T, path string) parquetSummary {
	t.Helper()
	rdr, err := file.OpenParquetFile(path, false)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = rdr.Close() }()
	fr, err := pqarrow.NewFileReader(rdr, pqarrow.ArrowReadProperties{}, memory.DefaultAllocator)
	if err != nil {
		t.Fatal(err)
	}
	tbl, err := fr.ReadTable(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defer tbl.Release()
	var fields []string
	for _, f := range tbl.Schema().Fields() {
		s := f.Name + ":" + f.Type.String()
		if f.Nullable {
			s += "?"
		}
		fields = append(fields, s)
	}
	return parquetSummary{Schema: strings.Join(fields, "; "), Rows: tbl.NumRows()}
}

func newTestServer(t *testing.T, out string) (*Server, *httptest.Server, *httptest.Server) {
	t.Helper()
	buf := buffer.New(time.Hour)
	buf.Now = func() time.Time { return time.UnixMilli(t0Ms) }
	s := New(Config{OutDir: out, DemoGitTag: "fixture", CollectorVersion: "fixture"}, buf, slog.New(slog.NewTextHandler(io.Discard, nil)))
	otlp := httptest.NewServer(s.OTLPHandler())
	ctl := httptest.NewServer(s.ControlHandler())
	t.Cleanup(otlp.Close)
	t.Cleanup(ctl.Close)
	return s, otlp, ctl
}

func snapshot(t *testing.T, ctlURL string) (int, Result) {
	t.Helper()
	body, _ := json.Marshal(Request{IncidentID: "paymentFailure-r1", T0UnixMs: t0Ms, StartMs: t0Ms - windowMs/2, WindowMs: windowMs})
	resp, err := http.Post(ctlURL+"/snapshot", "application/json", bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	var r Result
	_ = json.NewDecoder(resp.Body).Decode(&r)
	return resp.StatusCode, r
}

func TestGoldenSnapshot(t *testing.T) {
	out := t.TempDir()
	_, otlp, ctl := newTestServer(t, out)
	post(t, otlp.URL+"/v1/traces", fixtureTraces(), false)
	post(t, otlp.URL+"/v1/metrics", fixtureMetrics(), true)
	post(t, otlp.URL+"/v1/logs", fixtureLogs(), false)

	code, res := snapshot(t, ctl.URL)
	if code != 200 {
		t.Fatalf("snapshot: %d", code)
	}
	dir := filepath.Join(out, "paymentFailure-r1")
	got := map[string]parquetSummary{}
	for _, name := range []string{"spans", "metrics", "logs"} {
		got[name] = summarise(t, filepath.Join(dir, name+".parquet"))
	}
	if res.Spans != int(got["spans"].Rows) || res.Logs != int(got["logs"].Rows) {
		t.Fatalf("response counts %+v disagree with files %+v", res, got)
	}

	var m Manifest
	raw, _ := os.ReadFile(filepath.Join(dir, "manifest.json"))
	if err := json.Unmarshal(raw, &m); err != nil {
		t.Fatal(err)
	}
	if m.IncidentID != "paymentFailure-r1" || m.T0UnixMs != t0Ms || m.WindowMs != windowMs || m.DemoGitTag != "fixture" {
		t.Fatalf("manifest = %+v", m)
	}

	golden := filepath.Join("testdata", "golden.json")
	if *update {
		b, _ := json.MarshalIndent(got, "", "  ")
		if err := os.WriteFile(golden, append(b, '\n'), 0o644); err != nil {
			t.Fatal(err)
		}
		// Refresh the fixture snapshot the Python harness reads.
		fixture := filepath.Join("..", "..", "testdata", "fixture-snapshot")
		_ = os.RemoveAll(fixture)
		if err := os.MkdirAll(filepath.Dir(fixture), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.Rename(dir, fixture); err != nil {
			t.Fatal(err)
		}
		return
	}
	raw, err := os.ReadFile(golden)
	if err != nil {
		t.Fatalf("read golden (run go test ./internal/server -update): %v", err)
	}
	var want map[string]parquetSummary
	if err := json.Unmarshal(raw, &want); err != nil {
		t.Fatal(err)
	}
	for name, w := range want {
		if got[name] != w {
			t.Errorf("%s:\n got  %+v\n want %+v", name, got[name], w)
		}
	}
}

func TestSnapshotNeverOverwritesAndLeavesNoTemp(t *testing.T) {
	out := t.TempDir()
	_, otlp, ctl := newTestServer(t, out)
	post(t, otlp.URL+"/v1/logs", fixtureLogs(), false)
	if code, _ := snapshot(t, ctl.URL); code != 200 {
		t.Fatalf("first snapshot: %d", code)
	}
	if code, _ := snapshot(t, ctl.URL); code != http.StatusConflict {
		t.Fatalf("second snapshot: %d, want 409", code)
	}
	entries, _ := os.ReadDir(out)
	if len(entries) != 1 || entries[0].Name() != "paymentFailure-r1" {
		t.Fatalf("output dir holds %v", entries)
	}
}

func TestBadRequests(t *testing.T) {
	_, otlp, ctl := newTestServer(t, t.TempDir())
	resp, err := http.Post(otlp.URL+"/v1/traces", "application/x-protobuf", strings.NewReader("\xff\xff"))
	if err != nil {
		t.Fatal(err)
	}
	_ = resp.Body.Close()
	if resp.StatusCode != 400 {
		t.Fatalf("garbage protobuf: %d", resp.StatusCode)
	}
	for _, body := range []string{`{"incident_id":"../../etc","t0_unix_ms":1,"window_ms":1}`, `{"incident_id":"x-r1"}`, `nope`} {
		resp, err := http.Post(ctl.URL+"/snapshot", "application/json", strings.NewReader(body))
		if err != nil {
			t.Fatal(err)
		}
		_ = resp.Body.Close()
		if resp.StatusCode != 400 {
			t.Errorf("%s: %d, want 400", body, resp.StatusCode)
		}
	}
}
