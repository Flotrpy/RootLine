# Architecture

Rootline runs the live system once to freeze snapshots, then replays the
snapshots to every model at no cost. The only path back to the live system
is the remediation trial.

```text
 live (once)                                         replay (every model, $0)
 ───────────                                         ────────────────────────
 rootlinectl ──flags/toxics/netem──▶ OTel Demo        snapshot dir
     │                                  │              ├─ spans.parquet
     │                         OTLP/HTTP│              ├─ metrics.parquet      packers ─▶ prompt ─▶ model
     │                                  ▼              ├─ logs.parquet           (6k tokens)        │
     └──POST /snapshot──────────▶ snapshotter ───────▶ └─ manifest.json                             ▼
                                                                                        scorers ◀─ JSON output
 data/labels/<id>.json  (written by rootlinectl, never read by packers) ──────────────▶   ▲
                                                                                          │
 rootlinectl remediate ◀──────────── the model's chosen action (15 live trials) ──────────┘
```

## Components

| Component | Path | What it does |
|-----------|------|--------------|
| Fault catalog | `controller/internal/catalog` | The 15 incident types and their labels. Source of truth; the Python mirror is checked against it. |
| Injectors | `controller/internal/{flagd,toxi,netem,inject}` | flagd file edits, Toxiproxy toxics (one server per edge, routed), netem via sidecars. |
| Incident protocol | `controller/internal/incident` | Baseline 5m, inject, hold 5m, snapshot [T0-5m, T0+5m], clear, cool down 3m, recover (max 10m). Resumable campaigns. |
| Remediation | `controller/internal/remediate` | Fixed action menu, live trial, harmful-action rule. |
| Panel API | `controller/internal/api` | `:8088` for the Arduino bridge app. |
| Snapshotter | `snapshotter/` | OTLP/HTTP on `:4318`, control on `:8089`, atomic Parquet writes. |
| Packers | `harness/rootline_harness/packers` | Metrics, traces, logs, combined. Stable IDs, label redaction, token budget. |
| Perturbations | `harness/rootline_harness/perturb` | P1 anonymised service names. |
| Prompt | `harness/rootline_harness/prompt.py` | Instructions + pack within 6,000 tokens. |
| Schema | `harness/rootline_harness/schema.py` | Strict output contract. |
| Scorers | `harness/rootline_harness/scorers` | Top-1/3, layer, evidence validity, false alarms, Brier, ECE. |

## Network wiring

Each Toxiproxy-routed edge has its own Toxiproxy container and a netem
sidecar sharing that container's network namespace:

```text
checkout ──▶ toxiproxy-payment:50051 ──▶ payment:50051      (netem-payment shares its netns)
frontend ──▶ toxiproxy-catalog:3550  ──▶ product-catalog:3550 (netem-catalog shares its netns)
```

The Toxiproxy image has no `tc`, hence the sidecars. Separate containers keep
a netem rule on one edge from touching the other.

## Ports

| Port | Service |
|------|---------|
| 8088 | rootlinectl panel API |
| 8089 | snapshotter control |
| 4318 | snapshotter OTLP/HTTP (inside the compose network) |
| 8474 | Toxiproxy API, checkout->payment |
| 8475 | Toxiproxy API, frontend->product-catalog |
| 9090 | Prometheus (demo), used for health checks |

## Decisions for v0.1

- Scored service for `paymentUnreachable` and network faults: the
  downstream service of the edge (`payment`, `product-catalog`).
- Flag variants (`50%`, `on`, `5sec`, `100x`): checked against the pinned
  `demo.flagd.json` of 3.1.0; `flagd` refuses unknown variants.
- Health queries use the demo's span metrics at `frontend-proxy`.
- Evidence validity scores only the top hypothesis's citations.
- The service list in prompts is the catalog's, unchanged for every v0.1 run
  (`frontend-web` and `telemetry-docs` also appear in evidence).
- Held for v0.2: P1 boundary rules (RQ3), the cascade's no-fault rule and
  theta (RQ4).
