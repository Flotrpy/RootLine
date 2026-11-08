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
make test        # unit tests for both Go modules and the Python harness
make lint        # go vet, golangci-lint, ruff, pyright
make build       # bin/rootlinectl and bin/snapshotter
```

## Running the pilot

Needs Docker, about 16 GB of RAM, and a checkout of the OpenTelemetry Demo
at a pinned release tag. Docs: [architecture](docs/ARCHITECTURE.md),
[data contracts](docs/DATA.md).

1. Start the demo with Rootline's wiring, from the demo checkout:

   ```bash
   export ROOTLINE_DIR=/path/to/RootLine DEMO_GIT_TAG=<tag>
   docker compose -f docker-compose.yml -f "$ROOTLINE_DIR/compose.override.yml" up -d --build
   ```

2. Record image digests for the manifests:

   ```bash
   COMPOSE="docker compose -f docker-compose.yml -f $ROOTLINE_DIR/compose.override.yml" "$ROOTLINE_DIR/controller/deploy/record-digests.sh"
   ```

3. From the RootLine checkout, check a flag round trip:

   ```bash
   export ROOTLINE_FLAGD_FILE=/path/to/opentelemetry-demo/src/flagd/demo.flagd.json
   ./bin/rootlinectl flag set adHighCpu on && ./bin/rootlinectl flag reset --all
   ```

4. Gate 1, one full dry run (about 25 minutes with warm-up):

   ```bash
   ./bin/rootlinectl incident run --fault paymentFailure --replica 1 --warmup
   cd harness && uv run python -m rootline_harness.packers ../data/snapshots/paymentFailure-r1 --condition combined
   ```

   Pass when `data/snapshots/paymentFailure-r1/` holds three Parquet files and
   a manifest, `data/labels/paymentFailure-r1.json` exists, and the pack
   shows payment errors near the top. Then move or delete that dry-run
   snapshot so the campaign can write `paymentFailure-r1` again.

5. Overnight collection (30 incidents, about 6.5 hours, safe to Ctrl-C and
   rerun):

   ```bash
   ./bin/rootlinectl campaign --plan plans/pilot.yaml
   ```

## Licence

Code: Apache-2.0. Dataset: CC BY 4.0.

## Running the models

From the repository root, after the overnight campaign has written
`data/snapshots/` and `data/labels/`. Models and provider caps live in
`harness/rootline_harness/scheduler/` (`providers.py`, `ratelimits.yaml`).

1. Gate 2, the same snapshot scored twice must match:

   ```bash
   uv run --project harness python -m rootline_harness.run gate2 --incident paymentFailure-r1 --model gpt-oss-120b@cerebras
   ```

2. Queue and run (resumable; waits out rate limits instead of hitting them):

   ```bash
   uv run --project harness python -m rootline_harness.run enqueue --models gpt-oss-120b@cerebras
   uv run --project harness python -m rootline_harness.run work
   uv run --project harness python -m rootline_harness.run status
   uv run --project harness python -m rootline_harness.run export
   ```

   Add `--perturb p1` to `enqueue` for the anonymised-names runs.

3. Live remediation trials with the best model's own actions:

   ```bash
   uv run --project harness python -m analysis plan-remediation
   ```

   Run the printed `rootlinectl remediate ... --jsonl data/runs/remediation.jsonl` commands.

4. Regenerate every table and figure into `paper/figures/`, offline:

   ```bash
   make reproduce
   ```

## Replay without Python

The Rust CLI renders the exact evidence a model saw and can ask a local
model. Export the packs once, then:

```bash
uv run --project harness python -m rootline_harness.export_packs
```

```bash
./bin/rootline info data/snapshots/paymentFailure-r1
```

```bash
./bin/rootline replay data/snapshots/paymentFailure-r1 --condition combined --perturb p1
```

```bash
./bin/rootline replay data/snapshots/paymentFailure-r1 --model ollama/<name>
```

## Results site

A static site in `web/` (Next.js export, DuckDB-WASM in the browser).
Build its data, then preview at the root path:

```bash
uv run --project harness python -m analysis site-data
```

```bash
cd web && pnpm install && NEXT_PUBLIC_BASE_PATH="" pnpm build
```

The site deploys to GitHub Pages only at release, by hand (`pages.yml`),
built with `--include-labels`: incident IDs name the faults, so an earlier
deploy would reveal the answers.
