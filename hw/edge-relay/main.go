// Command edge-relay runs on Board A (Arduino UNO Q, Linux side). It relays
// the checkout -> payment TCP traffic over the board's Wi-Fi and exports
// OpenTelemetry spans and metrics to the Rootline snapshotter.
//
// Configuration (environment):
//
//	LISTEN_ADDR    address checkout connects to, e.g. 0.0.0.0:50051
//	UPSTREAM_ADDR  the payment service, e.g. 192.168.1.20:50051
//	OTLP_ENDPOINT  the snapshotter's OTLP/HTTP base, e.g. http://192.168.1.20:4318
//	               (empty disables telemetry)
//
// Build for the board: GOOS=linux GOARCH=arm64 go build -o edge-relay .
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/url"
	"os"
	"os/signal"
	"syscall"
	"time"

	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/metric"
	"go.opentelemetry.io/otel/metric/noop"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
	"go.opentelemetry.io/otel/trace"
	tracenoop "go.opentelemetry.io/otel/trace/noop"
)

// ServiceName is how the relay appears in snapshots.
const ServiceName = "edge-relay"

type config struct {
	Listen, Upstream, OTLP string
}

func loadConfig(getenv func(string) string) (config, error) {
	c := config{Listen: getenv("LISTEN_ADDR"), Upstream: getenv("UPSTREAM_ADDR"), OTLP: getenv("OTLP_ENDPOINT")}
	if c.Listen == "" {
		c.Listen = "0.0.0.0:50051"
	}
	if c.Upstream == "" {
		return c, errors.New("UPSTREAM_ADDR is required (the payment service, host:port)")
	}
	if _, _, err := net.SplitHostPort(c.Upstream); err != nil {
		return c, fmt.Errorf("UPSTREAM_ADDR: %w", err)
	}
	if c.OTLP != "" {
		u, err := url.Parse(c.OTLP)
		if err != nil || u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") {
			return c, fmt.Errorf("OTLP_ENDPOINT must be http(s)://host:port, got %q", c.OTLP)
		}
	}
	return c, nil
}

// telemetry sets up OTLP/HTTP exporters, or no-ops when endpoint is empty.
func telemetry(ctx context.Context, endpoint string) (trace.Tracer, metric.Meter, func(context.Context) error, error) {
	if endpoint == "" {
		return tracenoop.NewTracerProvider().Tracer(ServiceName), noop.NewMeterProvider().Meter(ServiceName),
			func(context.Context) error { return nil }, nil
	}
	res := resource.NewWithAttributes(semconv.SchemaURL, semconv.ServiceName(ServiceName))
	te, err := otlptracehttp.New(ctx, otlptracehttp.WithEndpointURL(endpoint+"/v1/traces"))
	if err != nil {
		return nil, nil, nil, err
	}
	me, err := otlpmetrichttp.New(ctx, otlpmetrichttp.WithEndpointURL(endpoint+"/v1/metrics"))
	if err != nil {
		return nil, nil, nil, err
	}
	tp := sdktrace.NewTracerProvider(sdktrace.WithBatcher(te), sdktrace.WithResource(res))
	mp := sdkmetric.NewMeterProvider(
		sdkmetric.WithReader(sdkmetric.NewPeriodicReader(me, sdkmetric.WithInterval(15*time.Second))),
		sdkmetric.WithResource(res),
	)
	shutdown := func(ctx context.Context) error {
		return errors.Join(tp.Shutdown(ctx), mp.Shutdown(ctx))
	}
	return tp.Tracer(ServiceName), mp.Meter(ServiceName), shutdown, nil
}

func main() {
	log := slog.New(slog.NewTextHandler(os.Stderr, nil))
	if err := run(log); err != nil {
		log.Error("edge-relay", "err", err)
		os.Exit(1)
	}
}

func run(log *slog.Logger) error {
	cfg, err := loadConfig(os.Getenv)
	if err != nil {
		return err
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	tracer, meter, shutdown, err := telemetry(ctx, cfg.OTLP)
	if err != nil {
		return err
	}
	defer func() {
		sctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = shutdown(sctx)
	}()

	relay, err := NewRelay(cfg.Upstream, tracer, meter, log)
	if err != nil {
		return err
	}
	ln, err := net.Listen("tcp", cfg.Listen)
	if err != nil {
		return err
	}
	log.Info("relaying", "listen", cfg.Listen, "upstream", cfg.Upstream, "otlp", cfg.OTLP)
	return relay.Serve(ctx, ln)
}
