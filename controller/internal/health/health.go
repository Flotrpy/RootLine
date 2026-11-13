// Package health samples shop-wide health (error ratio and p99 latency) and
// decides whether the system has recovered relative to a baseline.
package health

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"net/url"
	"strconv"
	"time"
)

// Sample is one health reading.
type Sample struct {
	ErrorRatio float64 `json:"error_ratio"`
	P99Ms      float64 `json:"p99_ms"`
}

// Recovery thresholds from the charter: error ratio within 1.5x baseline and
// p99 latency within 1.2x baseline.
const (
	ErrorRatioFactor = 1.5
	P99Factor        = 1.2
	// MinErrorRatio stops a near-zero baseline from making recovery
	// impossible: 1.5 x 0 is 0, and any single error would fail.
	MinErrorRatio = 0.005
)

// Recovered reports whether current is back within the thresholds of
// baseline.
func Recovered(baseline, current Sample) bool {
	errLimit := math.Max(baseline.ErrorRatio, MinErrorRatio) * ErrorRatioFactor
	return current.ErrorRatio <= errLimit && current.P99Ms <= baseline.P99Ms*P99Factor
}

// Probe reads current health.
type Probe interface {
	Sample(ctx context.Context) (Sample, error)
}

// Queries are the PromQL expressions the Prometheus probe runs. They default
// to the span metrics the demo's collector exports (names checked against
// demo 3.1.0).
type Queries struct {
	ErrorRatio string
	P99Ms      string
}

// DefaultQueries measure the frontend-proxy's server spans, which is what a
// shopper sees. Demo 3.1.0's Prometheus receives a sample only every 60 s, so
// a 1m window holds at most one point, rate() returns nothing, and every
// reading came out as 0. A 3m window always holds at least two.
var DefaultQueries = Queries{
	ErrorRatio: `sum(rate(traces_span_metrics_calls_total{service_name="frontend-proxy",span_kind="SPAN_KIND_SERVER",status_code="STATUS_CODE_ERROR"}[3m])) / sum(rate(traces_span_metrics_calls_total{service_name="frontend-proxy",span_kind="SPAN_KIND_SERVER"}[3m]))`,
	P99Ms:      `histogram_quantile(0.99, sum by (le) (rate(traces_span_metrics_duration_milliseconds_bucket{service_name="frontend-proxy",span_kind="SPAN_KIND_SERVER"}[3m])))`,
}

// Prometheus is a Probe backed by the Prometheus HTTP API.
type Prometheus struct {
	Base    string
	Queries Queries
	HTTP    *http.Client
}

// NewPrometheus returns a probe for a Prometheus server such as
// http://localhost:9090.
func NewPrometheus(base string) *Prometheus {
	return &Prometheus{Base: base, Queries: DefaultQueries, HTTP: &http.Client{Timeout: 10 * time.Second}}
}

type promResponse struct {
	Status string `json:"status"`
	Error  string `json:"error"`
	Data   struct {
		Result []struct {
			Value [2]any `json:"value"`
		} `json:"result"`
	} `json:"data"`
}

func (p *Prometheus) scalar(ctx context.Context, q string) (float64, error) {
	u := p.Base + "/api/v1/query?query=" + url.QueryEscape(q)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return 0, err
	}
	resp, err := p.HTTP.Do(req)
	if err != nil {
		return 0, fmt.Errorf("prometheus query: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	var pr promResponse
	if err := json.NewDecoder(resp.Body).Decode(&pr); err != nil {
		return 0, fmt.Errorf("prometheus response: %w", err)
	}
	if pr.Status != "success" {
		return 0, fmt.Errorf("prometheus: %s", pr.Error)
	}
	// No series means no traffic in the window; treat as zero.
	if len(pr.Data.Result) == 0 {
		return 0, nil
	}
	s, ok := pr.Data.Result[0].Value[1].(string)
	if !ok {
		return 0, fmt.Errorf("prometheus: unexpected value %v", pr.Data.Result[0].Value[1])
	}
	v, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return 0, err
	}
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return 0, nil
	}
	return v, nil
}

// Sample implements Probe.
func (p *Prometheus) Sample(ctx context.Context) (Sample, error) {
	er, err := p.scalar(ctx, p.Queries.ErrorRatio)
	if err != nil {
		return Sample{}, err
	}
	p99, err := p.scalar(ctx, p.Queries.P99Ms)
	if err != nil {
		return Sample{}, err
	}
	return Sample{ErrorRatio: er, P99Ms: p99}, nil
}
