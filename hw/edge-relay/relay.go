package main

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net"
	"sync"
	"sync/atomic"
	"time"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/trace"
)

// Relay forwards TCP connections from Listen to Upstream, one span and a
// set of metrics per connection. It is protocol-agnostic, so gRPC between
// checkout and payment passes through untouched.
type Relay struct {
	Upstream    string
	DialTimeout time.Duration
	Tracer      trace.Tracer
	Log         *slog.Logger

	conns    metric.Int64Counter
	errors   metric.Int64Counter
	bytes    metric.Int64Counter
	duration metric.Float64Histogram
	active   atomic.Int64
}

// NewRelay registers the relay's instruments on meter.
func NewRelay(upstream string, tracer trace.Tracer, meter metric.Meter, log *slog.Logger) (*Relay, error) {
	r := &Relay{Upstream: upstream, DialTimeout: 5 * time.Second, Tracer: tracer, Log: log}
	var err error
	if r.conns, err = meter.Int64Counter("relay.connections",
		metric.WithDescription("Connections accepted")); err != nil {
		return nil, err
	}
	if r.errors, err = meter.Int64Counter("relay.errors",
		metric.WithDescription("Connections that failed: upstream dial or copy errors")); err != nil {
		return nil, err
	}
	if r.bytes, err = meter.Int64Counter("relay.bytes", metric.WithUnit("By"),
		metric.WithDescription("Bytes relayed, by direction")); err != nil {
		return nil, err
	}
	if r.duration, err = meter.Float64Histogram("relay.connection.duration", metric.WithUnit("ms"),
		metric.WithDescription("Connection lifetime")); err != nil {
		return nil, err
	}
	if _, err = meter.Int64ObservableGauge("relay.connections.active",
		metric.WithInt64Callback(func(_ context.Context, o metric.Int64Observer) error {
			o.Observe(r.active.Load())
			return nil
		})); err != nil {
		return nil, err
	}
	return r, nil
}

// Serve accepts connections until ctx is cancelled, then waits for open
// connections to finish.
func (r *Relay) Serve(ctx context.Context, ln net.Listener) error {
	var wg sync.WaitGroup
	go func() {
		<-ctx.Done()
		_ = ln.Close()
	}()
	for {
		c, err := ln.Accept()
		if err != nil {
			if ctx.Err() != nil {
				wg.Wait()
				return nil
			}
			var ne net.Error
			if errors.As(err, &ne) && ne.Timeout() {
				continue
			}
			wg.Wait()
			return err
		}
		wg.Add(1)
		go func() {
			defer wg.Done()
			r.handle(ctx, c)
		}()
	}
}

func (r *Relay) handle(ctx context.Context, client net.Conn) {
	start := time.Now()
	ctx, span := r.Tracer.Start(ctx, "relay.connection",
		trace.WithSpanKind(trace.SpanKindServer),
		trace.WithAttributes(
			attribute.String("net.peer.addr", client.RemoteAddr().String()),
			attribute.String("relay.upstream", r.Upstream),
		))
	defer span.End()
	r.conns.Add(ctx, 1)
	r.active.Add(1)
	defer r.active.Add(-1)
	defer func() { _ = client.Close() }()

	fail := func(stage string, err error) {
		r.errors.Add(ctx, 1, metric.WithAttributes(attribute.String("stage", stage)))
		span.RecordError(err)
		span.SetStatus(codes.Error, stage+": "+err.Error())
		r.Log.Warn("relay error", "stage", stage, "err", err)
	}

	up, err := (&net.Dialer{Timeout: r.DialTimeout}).DialContext(ctx, "tcp", r.Upstream)
	if err != nil {
		fail("dial", err)
		return
	}
	defer func() { _ = up.Close() }()

	var wg sync.WaitGroup
	var upBytes, downBytes int64
	var copyErr error
	var once sync.Once
	pipe := func(dst, src net.Conn, n *int64) {
		defer wg.Done()
		written, err := io.Copy(dst, src)
		*n = written
		if err != nil && !isClosed(err) {
			once.Do(func() { copyErr = err })
		}
		// Half-close so the other direction sees EOF and finishes.
		if tc, ok := dst.(*net.TCPConn); ok {
			_ = tc.CloseWrite()
		} else {
			_ = dst.Close()
		}
	}
	wg.Add(2)
	go pipe(up, client, &upBytes)
	go pipe(client, up, &downBytes)
	wg.Wait()

	r.bytes.Add(ctx, upBytes, metric.WithAttributes(attribute.String("direction", "upstream")))
	r.bytes.Add(ctx, downBytes, metric.WithAttributes(attribute.String("direction", "downstream")))
	span.SetAttributes(attribute.Int64("relay.bytes.upstream", upBytes), attribute.Int64("relay.bytes.downstream", downBytes))
	if copyErr != nil {
		fail("copy", copyErr)
	}
	r.duration.Record(ctx, float64(time.Since(start).Microseconds())/1000)
}

func isClosed(err error) bool {
	return errors.Is(err, net.ErrClosed) || errors.Is(err, io.EOF)
}
