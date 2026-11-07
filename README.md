# Rootline

**Which evidence does an AI need to find the root cause, and can it fix it?**

Rootline is an open, reproducible benchmark and replay app for evidence-grounded
AI diagnosis of microservice failures. It measures which telemetry signals free
and open models need, whether they can tell network faults from application
faults, how easily misleading evidence fools them, and whether their proposed
fixes actually restore service.

> Status: v0.1 pilot under construction. No results yet. Every number that
> appears here later is produced by `make reproduce`.

## How it works

1. **Break it.** The Go controller (`rootlinectl`) injects one of 15 incident
   types into the [OpenTelemetry Demo](https://opentelemetry.io/docs/demo/):
   10 application faults via flagd feature flags, 4 network faults via
   Toxiproxy and `tc netem`, and 1 healthy control.
2. **Freeze it.** The snapshotter receives OTLP and writes each incident window
   to Parquet (spans, metrics, logs) plus a manifest. Ground-truth labels are
   stored separately and never shown to a model.
3. **Replay it.** Python packers turn a snapshot into a 6k-token evidence pack
   (metrics only, traces only, logs only, or combined). Every line carries a
   stable ID (`M-0042`, `T-0013`, `L-0201`) so cited evidence can be checked.
4. **Score it.** Models answer with a strict JSON contract: layer, ranked
   hypotheses with confidence and cited evidence, and one remediation action
   from a fixed menu. Scorers compute top-1/top-3, layer attribution, evidence
   validity, calibration and more.

## Research questions

| # | Question |
|---|----------|
| RQ1 | Which telemetry signals does a model need for a correct diagnosis? |
| RQ2 | Can models tell network faults from application faults? |
| RQ3 | Do models reason from evidence or from service names? |
| RQ4 | How much accuracy does a cheap-first cascade keep? |
| RQ5 | Do correct diagnoses lead to working fixes? |
| RQ6 | Do LLMs beat a classical ML baseline? |

Scope: only freely available open-weight models and free-tier APIs. Results
characterise what budget-constrained teams can achieve today, not the frontier.

## Repository layout

| Path | Language | Purpose |
|------|----------|---------|
| `controller/` | Go | `rootlinectl`: flags, Toxiproxy, netem, incidents, remediation, HTTP API |
| `snapshotter/` | Go | OTLP receiver writing Parquet snapshots |
| `harness/` | Python | evidence packers, perturbations, scorers, scheduler, output schema |
| `cascade/`, `baselines/`, `analysis/` | Python | offline cascade, classical ML baselines, stats and figures |
| `replay/` | Rust | `rootline replay` CLI |
| `web/` | TypeScript | static results site (Next.js + DuckDB-WASM) |
| `hw/` | Go / Python / Arduino | Arduino UNO Q real Wi-Fi extension |
| `docs/` | | build prompt, architecture, data contracts |

## Quick start

```bash
make test        # run every module's unit tests
make lint        # run every linter
```

## Licence

Code: Apache-2.0. Dataset: CC BY 4.0.
