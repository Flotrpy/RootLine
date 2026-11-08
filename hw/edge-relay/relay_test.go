package main

import (
	"bytes"
	"context"
	"io"
	"log/slog"
	"net"
	"strings"
	"testing"
	"time"

	"go.opentelemetry.io/otel/codes"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/metric/metricdata"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
)

type harness struct {
	addr   string
	spans  *tracetest.SpanRecorder
	reader *sdkmetric.ManualReader
	cancel context.CancelFunc
	done   chan error
}

func startRelay(t *testing.T, upstream string) *harness {
	t.Helper()
	spans := tracetest.NewSpanRecorder()
	tp := sdktrace.NewTracerProvider(sdktrace.WithSpanProcessor(spans))
	reader := sdkmetric.NewManualReader()
	mp := sdkmetric.NewMeterProvider(sdkmetric.WithReader(reader))
	r, err := NewRelay(upstream, tp.Tracer("t"), mp.Meter("t"), slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err != nil {
		t.Fatal(err)
	}
	r.DialTimeout = time.Second
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	h := &harness{addr: ln.Addr().String(), spans: spans, reader: reader, cancel: cancel, done: make(chan error, 1)}
	go func() { h.done <- r.Serve(ctx, ln) }()
	t.Cleanup(func() {
		cancel()
		if err := <-h.done; err != nil {
			t.Errorf("Serve: %v", err)
		}
	})
	return h
}

// echoServer echoes everything back, upper-cased, then closes.
func echoServer(t *testing.T) string {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = ln.Close() })
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go func() {
				defer func() { _ = c.Close() }()
				b, _ := io.ReadAll(c)
				_, _ = c.Write(bytes.ToUpper(b))
			}()
		}
	}()
	return ln.Addr().String()
}

func sums(t *testing.T, r *sdkmetric.ManualReader) map[string]int64 {
	t.Helper()
	var rm metricdata.ResourceMetrics
	if err := r.Collect(context.Background(), &rm); err != nil {
		t.Fatal(err)
	}
	out := map[string]int64{}
	for _, sm := range rm.ScopeMetrics {
		for _, m := range sm.Metrics {
			if s, ok := m.Data.(metricdata.Sum[int64]); ok {
				for _, dp := range s.DataPoints {
					key := m.Name
					if v, ok := dp.Attributes.Value("direction"); ok {
						key += "." + v.AsString()
					}
					out[key] += dp.Value
				}
			}
		}
	}
	return out
}

func TestRelaysBothDirections(t *testing.T) {
	h := startRelay(t, echoServer(t))
	c, err := net.Dial("tcp", h.addr)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := c.Write([]byte("charge card")); err != nil {
		t.Fatal(err)
	}
	_ = c.(*net.TCPConn).CloseWrite()
	got, err := io.ReadAll(c)
	if err != nil {
		t.Fatal(err)
	}
	_ = c.Close()
	if string(got) != "CHARGE CARD" {
		t.Fatalf("got %q", got)
	}
	waitFor(t, func() bool { return len(h.spans.Ended()) == 1 })
	m := sums(t, h.reader)
	if m["relay.connections"] != 1 || m["relay.bytes.upstream"] != 11 || m["relay.bytes.downstream"] != 11 || m["relay.errors"] != 0 {
		t.Fatalf("metrics = %v", m)
	}
	if s := h.spans.Ended()[0]; s.Name() != "relay.connection" || s.Status().Code == codes.Error {
		t.Fatalf("span = %s %v", s.Name(), s.Status())
	}
}

func TestUpstreamDownIsAnErrorSpan(t *testing.T) {
	// Grab a free port and close it so nothing listens there.
	ln, _ := net.Listen("tcp", "127.0.0.1:0")
	dead := ln.Addr().String()
	_ = ln.Close()

	h := startRelay(t, dead)
	c, err := net.Dial("tcp", h.addr)
	if err != nil {
		t.Fatal(err)
	}
	_, _ = io.ReadAll(c) // relay closes the client after the failed dial
	_ = c.Close()
	waitFor(t, func() bool { return len(h.spans.Ended()) == 1 })
	s := h.spans.Ended()[0]
	if s.Status().Code != codes.Error || !strings.HasPrefix(s.Status().Description, "dial") {
		t.Fatalf("status = %v", s.Status())
	}
	if m := sums(t, h.reader); m["relay.errors"] != 1 {
		t.Fatalf("metrics = %v", m)
	}
}

func TestLoadConfig(t *testing.T) {
	env := func(m map[string]string) func(string) string { return func(k string) string { return m[k] } }
	tests := []struct {
		name    string
		env     map[string]string
		wantErr string
	}{
		{"defaults listen", map[string]string{"UPSTREAM_ADDR": "10.0.0.2:50051"}, ""},
		{"missing upstream", map[string]string{}, "UPSTREAM_ADDR is required"},
		{"bad upstream", map[string]string{"UPSTREAM_ADDR": "nohost"}, "UPSTREAM_ADDR"},
		{"bad otlp", map[string]string{"UPSTREAM_ADDR": "a:1", "OTLP_ENDPOINT": "snapshotter:4318"}, "OTLP_ENDPOINT"},
		{"good otlp", map[string]string{"UPSTREAM_ADDR": "a:1", "OTLP_ENDPOINT": "http://10.0.0.2:4318"}, ""},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c, err := loadConfig(env(tt.env))
			if tt.wantErr == "" {
				if err != nil {
					t.Fatal(err)
				}
				if c.Listen == "" {
					t.Fatal("listen default missing")
				}
				return
			}
			if err == nil || !strings.Contains(err.Error(), tt.wantErr) {
				t.Fatalf("err = %v, want %q", err, tt.wantErr)
			}
		})
	}
}

func waitFor(t *testing.T, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatal("condition not met in time")
}
