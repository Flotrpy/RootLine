// Package rows flattens OTLP payloads into the row shapes of the snapshot
// data contract (docs/DATA.md).
package rows

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strconv"
	"sync"

	collogs "go.opentelemetry.io/proto/otlp/collector/logs/v1"
	colmetrics "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	coltrace "go.opentelemetry.io/proto/otlp/collector/trace/v1"
	commonpb "go.opentelemetry.io/proto/otlp/common/v1"
	metricspb "go.opentelemetry.io/proto/otlp/metrics/v1"
	resourcepb "go.opentelemetry.io/proto/otlp/resource/v1"
)

// Span is one row of spans.parquet.
type Span struct {
	TraceID       string
	SpanID        string
	ParentSpanID  *string
	Service       string
	Operation     string
	StartUnixNano int64
	DurationNs    int64
	StatusCode    string
	Attributes    string // JSON object, sorted keys
}

// Metric is one row of metrics.parquet.
type Metric struct {
	Ts         int64 // unix ms
	Service    string
	MetricName string
	Value      float64
	Labels     string // JSON object, sorted keys
}

// Log is one row of logs.parquet.
type Log struct {
	Ts       int64 // unix ms
	Service  string
	Severity string
	Body     string
	TraceID  *string
}

// Quantiles derived from every histogram.
var Quantiles = []struct {
	Suffix string
	Q      float64
}{{".p50", 0.50}, {".p95", 0.95}, {".p99", 0.99}}

func anyValue(v *commonpb.AnyValue) any {
	if v == nil {
		return nil
	}
	switch x := v.Value.(type) {
	case *commonpb.AnyValue_StringValue:
		return x.StringValue
	case *commonpb.AnyValue_BoolValue:
		return x.BoolValue
	case *commonpb.AnyValue_IntValue:
		return x.IntValue
	case *commonpb.AnyValue_DoubleValue:
		return x.DoubleValue
	case *commonpb.AnyValue_BytesValue:
		return hex.EncodeToString(x.BytesValue)
	case *commonpb.AnyValue_ArrayValue:
		out := make([]any, 0, len(x.ArrayValue.GetValues()))
		for _, e := range x.ArrayValue.GetValues() {
			out = append(out, anyValue(e))
		}
		return out
	case *commonpb.AnyValue_KvlistValue:
		return attrMap(x.KvlistValue.GetValues())
	}
	return nil
}

func attrMap(kvs []*commonpb.KeyValue) map[string]any {
	m := make(map[string]any, len(kvs))
	for _, kv := range kvs {
		m[kv.GetKey()] = anyValue(kv.GetValue())
	}
	return m
}

// attrJSON encodes attributes as a JSON object; encoding/json sorts map
// keys, so equal attribute sets always produce equal strings.
func attrJSON(kvs []*commonpb.KeyValue) string {
	if len(kvs) == 0 {
		return "{}"
	}
	b, err := json.Marshal(attrMap(kvs))
	if err != nil {
		return "{}"
	}
	return string(b)
}

func serviceName(r *resourcepb.Resource) string {
	for _, kv := range r.GetAttributes() {
		if kv.GetKey() == "service.name" {
			if s, ok := anyValue(kv.GetValue()).(string); ok && s != "" {
				return s
			}
		}
	}
	return "unknown"
}

func anyString(v *commonpb.AnyValue) string {
	switch x := anyValue(v).(type) {
	case nil:
		return ""
	case string:
		return x
	default:
		b, _ := json.Marshal(x)
		return string(b)
	}
}

// Traces flattens a trace export request.
func Traces(req *coltrace.ExportTraceServiceRequest) []Span {
	var out []Span
	for _, rs := range req.GetResourceSpans() {
		svc := serviceName(rs.GetResource())
		for _, ss := range rs.GetScopeSpans() {
			for _, sp := range ss.GetSpans() {
				var parent *string
				if p := sp.GetParentSpanId(); len(p) > 0 {
					h := hex.EncodeToString(p)
					parent = &h
				}
				start := int64(sp.GetStartTimeUnixNano())
				dur := int64(sp.GetEndTimeUnixNano()) - start
				if dur < 0 {
					dur = 0
				}
				out = append(out, Span{
					TraceID:       hex.EncodeToString(sp.GetTraceId()),
					SpanID:        hex.EncodeToString(sp.GetSpanId()),
					ParentSpanID:  parent,
					Service:       svc,
					Operation:     sp.GetName(),
					StartUnixNano: start,
					DurationNs:    dur,
					StatusCode:    sp.GetStatus().GetCode().String(),
					Attributes:    attrJSON(sp.GetAttributes()),
				})
			}
		}
	}
	return out
}

// Logs flattens a log export request.
func Logs(req *collogs.ExportLogsServiceRequest) []Log {
	var out []Log
	for _, rl := range req.GetResourceLogs() {
		svc := serviceName(rl.GetResource())
		for _, sl := range rl.GetScopeLogs() {
			for _, lr := range sl.GetLogRecords() {
				ts := lr.GetTimeUnixNano()
				if ts == 0 {
					ts = lr.GetObservedTimeUnixNano()
				}
				sev := lr.GetSeverityText()
				if sev == "" && lr.GetSeverityNumber() != 0 {
					sev = lr.GetSeverityNumber().String()
				}
				var tid *string
				if t := lr.GetTraceId(); len(t) > 0 {
					h := hex.EncodeToString(t)
					tid = &h
				}
				out = append(out, Log{
					Ts:       int64(ts / 1_000_000),
					Service:  svc,
					Severity: sev,
					Body:     anyString(lr.GetBody()),
					TraceID:  tid,
				})
			}
		}
	}
	return out
}

// Flattener turns metric exports into rows. It keeps state per series so
// that it can (1) turn delta sums into cumulative counters, which the
// packers expect, and (2) turn cumulative histograms into per-interval
// quantiles: a quantile of an all-time cumulative histogram barely moves
// during a five-minute fault.
type Flattener struct {
	mu    sync.Mutex
	sums  map[string]float64
	hists map[string]histState
}

type histState struct {
	count   uint64
	buckets []uint64
}

// NewFlattener returns an empty Flattener.
func NewFlattener() *Flattener {
	return &Flattener{sums: map[string]float64{}, hists: map[string]histState{}}
}

func seriesKey(svc, name, labels string) string { return svc + "\x00" + name + "\x00" + labels }

// Metrics flattens a metrics export request.
func (f *Flattener) Metrics(req *colmetrics.ExportMetricsServiceRequest) []Metric {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []Metric
	for _, rm := range req.GetResourceMetrics() {
		svc := serviceName(rm.GetResource())
		for _, sm := range rm.GetScopeMetrics() {
			for _, m := range sm.GetMetrics() {
				out = append(out, f.metric(svc, m)...)
			}
		}
	}
	return out
}

func numberValue(dp *metricspb.NumberDataPoint) float64 {
	switch v := dp.Value.(type) {
	case *metricspb.NumberDataPoint_AsDouble:
		return v.AsDouble
	case *metricspb.NumberDataPoint_AsInt:
		return float64(v.AsInt)
	}
	return 0
}

func ms(ns uint64) int64 { return int64(ns / 1_000_000) }

func (f *Flattener) metric(svc string, m *metricspb.Metric) []Metric {
	name := m.GetName()
	var out []Metric
	switch d := m.Data.(type) {
	case *metricspb.Metric_Gauge:
		for _, dp := range d.Gauge.GetDataPoints() {
			out = append(out, Metric{ms(dp.GetTimeUnixNano()), svc, name, numberValue(dp), attrJSON(dp.GetAttributes())})
		}
	case *metricspb.Metric_Sum:
		delta := d.Sum.GetAggregationTemporality() == metricspb.AggregationTemporality_AGGREGATION_TEMPORALITY_DELTA
		for _, dp := range d.Sum.GetDataPoints() {
			labels := attrJSON(dp.GetAttributes())
			v := numberValue(dp)
			if delta && d.Sum.GetIsMonotonic() {
				k := seriesKey(svc, name, labels)
				f.sums[k] += v
				v = f.sums[k]
			}
			out = append(out, Metric{ms(dp.GetTimeUnixNano()), svc, name, v, labels})
		}
	case *metricspb.Metric_Histogram:
		delta := d.Histogram.GetAggregationTemporality() == metricspb.AggregationTemporality_AGGREGATION_TEMPORALITY_DELTA
		for _, dp := range d.Histogram.GetDataPoints() {
			out = append(out, f.histogram(svc, name, delta, dp)...)
		}
	case *metricspb.Metric_Summary:
		for _, dp := range d.Summary.GetDataPoints() {
			labels := attrJSON(dp.GetAttributes())
			for _, q := range dp.GetQuantileValues() {
				suffix := ".q" + strconv.FormatFloat(q.GetQuantile(), 'f', -1, 64)
				out = append(out, Metric{ms(dp.GetTimeUnixNano()), svc, name + suffix, q.GetValue(), labels})
			}
			out = append(out, Metric{ms(dp.GetTimeUnixNano()), svc, name + ".count", float64(dp.GetCount()), labels})
		}
		// Exponential histograms are not flattened: the demo's collector
		// config does not emit them (none in the v0.1 snapshots).
	}
	return out
}

func (f *Flattener) histogram(svc, name string, delta bool, dp *metricspb.HistogramDataPoint) []Metric {
	labels := attrJSON(dp.GetAttributes())
	k := seriesKey(svc, name, labels)
	ts := ms(dp.GetTimeUnixNano())
	cur := histState{count: dp.GetCount(), buckets: dp.GetBucketCounts()}

	var interval []uint64
	var cumulative uint64
	if delta {
		interval = cur.buckets
		prev := f.hists[k]
		cumulative = prev.count + cur.count
		f.hists[k] = histState{count: cumulative}
	} else {
		prev, seen := f.hists[k]
		f.hists[k] = cur
		cumulative = cur.count
		switch {
		case !seen:
			// First point: no interval yet, only the count.
			interval = nil
		case cur.count < prev.count || len(prev.buckets) != len(cur.buckets):
			interval = cur.buckets // counter reset
		default:
			interval = make([]uint64, len(cur.buckets))
			for i := range cur.buckets {
				interval[i] = cur.buckets[i] - prev.buckets[i]
			}
		}
	}

	out := []Metric{{ts, svc, name + ".count", float64(cumulative), labels}}
	var total uint64
	for _, c := range interval {
		total += c
	}
	if total > 0 {
		for _, q := range Quantiles {
			out = append(out, Metric{ts, svc, name + q.Suffix, Quantile(q.Q, dp.GetExplicitBounds(), interval), labels})
		}
	}
	return out
}

// Quantile estimates the q-quantile of an explicit-bucket histogram by
// linear interpolation inside the bucket, as Prometheus histogram_quantile
// does. Values in the overflow bucket return the highest finite bound.
func Quantile(q float64, bounds []float64, counts []uint64) float64 {
	var total uint64
	for _, c := range counts {
		total += c
	}
	if total == 0 || len(counts) == 0 {
		return math.NaN()
	}
	rank := q * float64(total)
	var cum uint64
	for i, c := range counts {
		prevCum := cum
		cum += c
		if float64(cum) < rank || c == 0 {
			continue
		}
		if i >= len(bounds) {
			if len(bounds) == 0 {
				return math.NaN()
			}
			return bounds[len(bounds)-1]
		}
		lower := 0.0
		if i > 0 {
			lower = bounds[i-1]
		}
		upper := bounds[i]
		return lower + (upper-lower)*(rank-float64(prevCum))/float64(c)
	}
	return bounds[len(bounds)-1]
}

// SortSpans, SortMetrics and SortLogs give snapshots a deterministic row
// order regardless of arrival order.
func SortSpans(s []Span) {
	sort.Slice(s, func(i, j int) bool {
		if s[i].StartUnixNano != s[j].StartUnixNano {
			return s[i].StartUnixNano < s[j].StartUnixNano
		}
		if s[i].TraceID != s[j].TraceID {
			return s[i].TraceID < s[j].TraceID
		}
		return s[i].SpanID < s[j].SpanID
	})
}

func SortMetrics(m []Metric) {
	sort.Slice(m, func(i, j int) bool {
		a, b := m[i], m[j]
		if a.Ts != b.Ts {
			return a.Ts < b.Ts
		}
		if a.Service != b.Service {
			return a.Service < b.Service
		}
		if a.MetricName != b.MetricName {
			return a.MetricName < b.MetricName
		}
		return a.Labels < b.Labels
	})
}

func SortLogs(l []Log) {
	sort.SliceStable(l, func(i, j int) bool {
		a, b := l[i], l[j]
		if a.Ts != b.Ts {
			return a.Ts < b.Ts
		}
		if a.Service != b.Service {
			return a.Service < b.Service
		}
		return a.Body < b.Body
	})
}

// String helps debugging.
func (s Span) String() string { return fmt.Sprintf("%s/%s %s %s", s.TraceID, s.SpanID, s.Service, s.Operation) }
