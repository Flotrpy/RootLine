// Command snapshotter receives OTLP/HTTP from the demo's collector, keeps
// the last minutes in memory, and writes incident windows to Parquet when
// rootlinectl asks.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/flotrpy/rootline/snapshotter/internal/buffer"
	"github.com/flotrpy/rootline/snapshotter/internal/server"
)

func main() {
	otlpAddr := flag.String("otlp-addr", ":4318", "OTLP/HTTP listen address")
	ctlAddr := flag.String("control-addr", ":8089", "control API listen address")
	out := flag.String("out", "data/snapshots", "snapshot output directory")
	retention := flag.Duration("retention", 20*time.Minute, "how long rows stay in memory")
	settle := flag.Duration("settle", 15*time.Second, "wait before freezing a window")
	digests := flag.String("image-digests", os.Getenv("IMAGE_DIGESTS_FILE"), "JSON file mapping image -> digest")
	flag.Parse()

	log := slog.New(slog.NewTextHandler(os.Stderr, nil))
	cfg := server.Config{
		OutDir:           *out,
		DemoGitTag:       os.Getenv("DEMO_GIT_TAG"),
		CollectorVersion: os.Getenv("COLLECTOR_VERSION"),
		Settle:           *settle,
	}
	if *digests != "" {
		raw, err := os.ReadFile(*digests)
		if err != nil {
			log.Error("read image digests", "err", err)
			os.Exit(1)
		}
		if err := json.Unmarshal(raw, &cfg.ImageDigests); err != nil {
			log.Error("parse image digests", "err", err)
			os.Exit(1)
		}
	}
	if cfg.DemoGitTag == "" {
		log.Warn("DEMO_GIT_TAG is not set; manifests will not record the demo version")
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	buf := buffer.New(*retention)
	srv := server.New(cfg, buf, log)
	go func() {
		t := time.NewTicker(time.Minute)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				buf.Sweep()
			}
		}
	}()

	servers := []*http.Server{
		{Addr: *otlpAddr, Handler: srv.OTLPHandler(), ReadHeaderTimeout: 10 * time.Second},
		{Addr: *ctlAddr, Handler: srv.ControlHandler(), ReadHeaderTimeout: 10 * time.Second},
	}
	errc := make(chan error, len(servers))
	for _, s := range servers {
		go func(s *http.Server) {
			log.Info("listening", "addr", s.Addr)
			if err := s.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
				errc <- err
			}
		}(s)
	}
	select {
	case <-ctx.Done():
	case err := <-errc:
		log.Error("server failed", "err", err)
	}
	sctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	for _, s := range servers {
		_ = s.Shutdown(sctx)
	}
}
