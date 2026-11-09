# Rootline

**Which evidence does an AI need to find the root cause, and can it fix it?**

Rootline is an open, reproducible benchmark and replay app for evidence-grounded
AI diagnosis of microservice failures. It measures which telemetry signals free
and open models need, whether they can tell network faults from application
faults, how easily misleading evidence fools them, and whether their proposed
fixes actually restore service.

> Status: v0.1 pilot under construction. No results yet. Every number that
> appears here later is produced by `make reproduce`. v0.1 answers RQ1 and
> RQ2 only; see [Limitations](#limitations).

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

| # | Question | Release |
|---|----------|---------|
| RQ1 | Which telemetry signals does a model need for a correct diagnosis? | v0.1 |
| RQ2 | Can models tell network faults from application faults? | v0.1 |
| RQ3 | Do models reason from evidence or from service names? | v0.2 |
| RQ4 | How much accuracy does a cheap-first cascade keep? | v0.2 |
| RQ5 | Do correct diagnoses lead to working fixes? | v0.2 |
| RQ6 | Do LLMs beat a classical ML baseline? | v0.2 |

v0.1 tests only RQ1 and RQ2, with Holm correction across those two. The
code for RQ3 to RQ6 stays in the repository, but their hypotheses are
reported as "deferred to v0.2" and not tested.

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
   export ROOTLINE_DIR=/path/to/RootLine DEMO_GIT_TAG=3.1.0 DEMO_VERSION=3.1.0
   docker compose -f compose.yaml -f compose.full.yaml -f compose.observability.yaml -f "$ROOTLINE_DIR/compose.override.yml" pull --ignore-pull-failures
   docker compose -f compose.yaml -f compose.full.yaml -f compose.observability.yaml -f "$ROOTLINE_DIR/compose.override.yml" build snapshotter
   COMPOSE="docker compose -f compose.yaml -f compose.full.yaml -f compose.observability.yaml -f $ROOTLINE_DIR/compose.override.yml" "$ROOTLINE_DIR/controller/deploy/record-digests.sh"
   docker compose -f compose.yaml -f compose.full.yaml -f compose.observability.yaml -f "$ROOTLINE_DIR/compose.override.yml" up -d --no-build
   ```

   The fourth line records image digests for the snapshot manifests. It must
   run before `up`: the snapshotter exits at start without that file.

2. Check that every container is up and none is unhealthy:

   ```bash
   docker ps --filter health=unhealthy --filter status=exited
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

## Limitations

v0.1 is a pilot. Read every result with these limits in mind.

- **Small sample.** Two replicas of each of 15 incident types (30
  snapshots). Confidence intervals are wide, and a result that misses
  significance may only mean the sample is too small to show it. All
  results are reported, including negative ones.
- **Two questions only.** v0.1 tests RQ1 (which signals) and RQ2 (network
  vs application). It says nothing about name reliance, cascades, whether
  fixes work, or classical baselines; those are v0.2.
- **One testbed, one machine.** Every snapshot comes from the
  OpenTelemetry Demo 3.1.0 on Docker Compose, on one Windows desktop PC (WSL2),
  under a fixed load of 20 simulated users. Real production systems are
  larger, noisier and less tidy. Findings may not carry over.
- **Changed resource limits.** To keep the demo stable at this load,
  `compose.override.yml` raises the memory limits of a few services,
  including the database (see the comments in that file).
- **Faults the models may have seen.** The application faults are the
  demo's own public feature flags. Flag and fault names are removed from
  every prompt, but service names are not, and models may know the demo's
  source code from training.
- **Scoring choices.** For network faults the scored root cause is the
  downstream service of the broken edge (for example `payment` for
  checkout → payment). Other reasonable choices would change some scores.
  Prompts are capped at 6,000 tokens, so some evidence is dropped by design.
- **Free models only.** Only open-weight models and free-tier APIs, each
  scored once per snapshot and condition at temperature 0. Hosted models
  can change without notice; the model ID and date of every run are
  recorded.
- **Some faults left little trace.** A manipulation check
  (`python -m analysis fault-visibility`, written to
  `paper/figures/fault_visibility.csv`) compares each snapshot's affected
  spans before and after fault onset. Several injected faults barely move
  them, for example connection resets on a gRPC link that keeps one
  connection open. These snapshots are kept and scored as they are: a model
  cannot be expected to find a fault the evidence does not show, and the
  report says which ones these are.
- **Hardware arm.** 12 snapshots on one home Wi-Fi network with two
  Arduino UNO Q boards. Lowering transmit power affects only the board's
  uplink, and with the board near the router it left no visible trace; a
  30-second radio-off stands in for a power cut. The relay on the board
  sent no telemetry of its own, so hardware snapshots contain the same
  services as emulated ones. It is reported as exploratory, outside the
  hypothesis tests.
- **Reruns.** Snapshots that overlapped a crash of the testbed itself,
  including two whose baseline was already unhealthy, were moved to
  `data/old/` and run again with the same fault and replica number.

## Licence

Code: Apache-2.0. Dataset: CC BY 4.0.

## Running the models

From the repository root, after the overnight campaign has written
`data/snapshots/` and `data/labels/`. Models and provider caps live in
`harness/rootline_harness/scheduler/` (`providers.py`, `ratelimits.yaml`).

v0.1 scores three open-weight models, one per size:

| Model ID | Size | Runs on |
|----------|------|---------|
| `gpt-oss-120b@groq` | 120B (Tier C), low reasoning effort | Groq free tier, no card (`GROQ_API_KEY`) |
| `qwen3-8b-q4@ollama` | 8B, Q4_K_M (Tier B) | Ollama on the PC |
| `gemma3-4b-q4@ollama` | 4B, Q4_K_M (Tier A) | Ollama on the PC |

For the local models, install [Ollama](https://ollama.com) and pull the
exact tags (about 8.6 GB). Run them only when no campaign is running:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

```bash
ollama pull qwen3:8b && ollama pull gemma3:4b
```

1. Gate 2, the same snapshot scored twice must match:

   ```bash
   uv run --project harness python -m rootline_harness.run gate2 --incident paymentFailure-r1 --model gpt-oss-120b@groq
   ```

2. Queue and run (resumable; waits out rate limits instead of hitting them):

   ```bash
   uv run --project harness python -m rootline_harness.run enqueue --models gpt-oss-120b@groq qwen3-8b-q4@ollama gemma3-4b-q4@ollama
   uv run --project harness python -m rootline_harness.run work
   uv run --project harness python -m rootline_harness.run status
   uv run --project harness python -m rootline_harness.run export
   ```

   v0.1 needs only the default (P0) runs. `--perturb p1` adds the
   anonymised-names runs for RQ3 (v0.2).

   Rate-limited providers can run one day at a time from any machine:
   `scripts/score_daily.py --model gpt-oss-120b@groq` keeps its queue in a
   private Hugging Face dataset, stops at the daily cap and resumes the
   next day. Local models run with their own queue
   (`--db data/queue-ollama.sqlite`). Each location exports to
   `data/runs/runs-<name>.parquet`, and `run merge` combines them into
   `runs.parquet`.

3. (v0.2, RQ5) Live remediation trials with the best model's own actions:

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

Photos of the two boards go in `web/public/photos/board-a.jpg` and
`board-b.jpg` (`.png` or `.webp` also work); the site shows them next to
its drawings once they exist.

The site deploys to GitHub Pages only at release, by hand (`pages.yml`),
built with `--include-labels`: incident IDs name the faults, so an earlier
deploy would reveal the answers.

## Release

`docs/RELEASE.md` is the ordered path from the first snapshot to launch,
including when to set up the Arduino boards. `make release-check` reports
what is still missing; `make dataset` builds the Hugging Face dataset;
`make paper` compiles the technical report from `make reproduce` output.
