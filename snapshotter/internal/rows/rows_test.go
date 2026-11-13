package rows

import (
	"math"
	"testing"

	colmetrics "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	coltrace "go.opentelemetry.io/proto/otlp/collector/trace/v1"
	commonpb "go.opentelemetry.io/proto/otlp/common/v1"
	metricspb "go.opentelemetry.io/proto/otlp/metrics/v1"
	resourcepb "go.opentelemetry.io/proto/otlp/resource/v1"
	tracepb "go.opentelemetry.io/proto/otlp/trace/v1"
)

func TestQuantile(t *testing.T) {
	bounds := []float64{10, 100, 1000}
	tests := []struct {
		name   string
		q      float64
		counts []uint64
		want   float64
	}{
		{"median in first bucket", 0.5, []uint64{10, 0, 0, 0}, 5},
		{"interpolate second bucket", 0.5, []uint64{0, 10, 0, 0}, 55},
		{"p99 spills into third", 0.99, []uint64{50, 49, 1, 0}, 100 + 900*0.0},
		{"overflow bucket returns top bound", 0.99, []uint64{0, 0, 0, 5}, 1000},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := Quantile(tt.q, bounds, tt.counts)
			if math.Abs(got-tt.want) > 1e-9 {
				t.Fatalf("got %v, want %v", got, tt.want)
			}
		})
	}
	if !math.IsNaN(Quantile(0.5, bounds, []uint64{0, 0, 0, 0})) {
		t.Fatal("empty histogram should be NaN")
	}
}

func res(svc string) *resourcepb.Resource {
	return &resourcepb.Resource{Attributes: []*commonpb.KeyValue{
		{Key: "service.name", Value: &commonpb.AnyValue{Value: &commonpb.AnyValue_StringValue{StringValue: svc}}},
	}}
}

func histReq(ts uint64, temporality metricspb.AggregationTemporality, counts []uint64) *colmetrics.ExportMetricsServiceRequest {
	var total uint64
	for _, c := range counts {
		total += c
	}
	return &colmetrics.ExportMetricsServiceRequest{ResourceMetrics: []*metricspb.ResourceMetrics{{
		Resource: res("payment"),
		ScopeMetrics: []*metricspb.ScopeMetrics{{Metrics: []*metricspb.Metric{{
			Name: "duration",
			Data: &metricspb.Metric_Histogram{Histogram: &metricspb.Histogram{
				AggregationTemporality: temporality,
				DataPoints: []*metricspb.HistogramDataPoint{{
					TimeUnixNano:   ts,
					Count:          total,
					ExplicitBounds: []float64{10, 100, 1000},
					BucketCounts:   counts,
				}},
			}},
		}}}},
	}}}
}

func byName(ms []Metric) map[string]float64 {
	out := map[string]float64{}
	for _, m := range ms {
		out[m.MetricName] = m.Value
	}
	return out
}

func TestCumulativeHistogramBecomesIntervalQuantiles(t *testing.T) {
	f := NewFlattener()
	cum := metricspb.AggregationTemporality_AGGREGATION_TEMPORALITY_CUMULATIVE

	first := byName(f.Metrics(histReq(1e15, cum, []uint64{1000, 0, 0, 0})))
	if _, ok := first["duration.p99"]; ok {
		t.Fatal("first cumulative point has no interval and must not emit quantiles")
	}
	if first["duration.count"] != 1000 {
		t.Fatalf("count = %v", first["duration.count"])
	}

	// 10 new observations, all slow. A cumulative p99 would still sit in
	// the first bucket; the interval p99 must see the slowdown.
	second := byName(f.Metrics(histReq(2e15, cum, []uint64{1000, 0, 10, 0})))
	if second["duration.p99"] <= 100 {
		t.Fatalf("interval p99 = %v, want > 100", second["duration.p99"])
	}
	if second["duration.count"] != 1010 {
		t.Fatalf("count = %v", second["duration.count"])
	}

	// Counter reset: the new point is the interval.
	third := byName(f.Metrics(histReq(3e15, cum, []uint64{4, 0, 0, 0})))
	if third["duration.p50"] != 5 {
		t.Fatalf("after reset p50 = %v", third["duration.p50"])
	}
}

func TestDeltaSumBecomesCumulative(t *testing.T) {
	f := NewFlattener()
	req := func(v int64) *colmetrics.ExportMetricsServiceRequest {
		return &colmetrics.ExportMetricsServiceRequest{ResourceMetrics: []*metricspb.ResourceMetrics{{
			Resource: res("checkout"),
			ScopeMetrics: []*metricspb.ScopeMetrics{{Metrics: []*metricspb.Metric{{
				Name: "calls",
				Data: &metricspb.Metric_Sum{Sum: &metricspb.Sum{
					IsMonotonic:            true,
					AggregationTemporality: metricspb.AggregationTemporality_AGGREGATION_TEMPORALITY_DELTA,
					DataPoints:             []*metricspb.NumberDataPoint{{Value: &metricspb.NumberDataPoint_AsInt{AsInt: v}}},
				}},
			}}}},
		}}}
	}
	f.Metrics(req(5))
	got := f.Metrics(req(3))
	if got[0].Value != 8 || got[0].Service != "checkout" {
		t.Fatalf("got %+v", got[0])
	}
}

func TestTraces(t *testing.T) {
	req := &coltrace.ExportTraceServiceRequest{ResourceSpans: []*tracepb.ResourceSpans{{
		Resource: res("payment"),
		ScopeSpans: []*tracepb.ScopeSpans{{Spans: []*tracepb.Span{
			{
				TraceId: []byte{1, 2}, SpanId: []byte{0xab}, Name: "Charge",
				StartTimeUnixNano: 100, EndTimeUnixNano: 350,
				Status: &tracepb.Status{Code: tracepb.Status_STATUS_CODE_ERROR},
				Attributes: []*commonpb.KeyValue{
					{Key: "z", Value: &commonpb.AnyValue{Value: &commonpb.AnyValue_IntValue{IntValue: 1}}},
					{Key: "a", Value: &commonpb.AnyValue{Value: &commonpb.AnyValue_StringValue{StringValue: "x"}}},
				},
			},
			{TraceId: []byte{1, 2}, SpanId: []byte{0xcd}, ParentSpanId: []byte{0xab}, StartTimeUnixNano: 200, EndTimeUnixNano: 100},
		}}},
	}}}
	got := Traces(req)
	if len(got) != 2 {
		t.Fatalf("got %d spans", len(got))
	}
	root, child := got[0], got[1]
	if root.TraceID != "0102" || root.SpanID != "ab" || root.ParentSpanID != nil {
		t.Errorf("root ids: %+v", root)
	}
	if root.StatusCode != "STATUS_CODE_ERROR" || root.DurationNs != 250 || root.Service != "payment" {
		t.Errorf("root fields: %+v", root)
	}
	if root.Attributes != `{"a":"x","z":1}` {
		t.Errorf("attributes = %s", root.Attributes)
	}
	if child.ParentSpanID == nil || *child.ParentSpanID != "ab" || child.DurationNs != 0 {
		t.Errorf("child: %+v", child)
	}
}
