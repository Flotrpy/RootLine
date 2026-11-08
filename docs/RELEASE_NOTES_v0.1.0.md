# Rootline v0.1.0: pilot release

Rootline is an open, reproducible benchmark and replay app for
evidence-grounded AI diagnosis of microservice failures, built at $0 with
free and open models.

**Results:** see the technical report (`paper/rootline-v0.1.pdf`) and
`paper/figures/results.json`. Every number there is produced by
`make reproduce` from the published runs. This is a pilot: two replicas per
incident type give wide confidence intervals.

## What is in this release

- **Testbed and faults:** 15 incident types on the OpenTelemetry Demo (10
  feature-flag application faults, 4 Toxiproxy/netem network faults, 1
  healthy control), plus 3 real Wi-Fi faults through Arduino UNO Q boards.
- **Snapshots:** frozen spans, metrics and logs per incident, as Parquet.
- **Evaluation:** four evidence conditions within 6,000 tokens, name
  anonymisation (P1), a strict output contract, evidence-grounded scoring,
  live remediation trials, an offline cheap-first cascade, and LightGBM and
  Isolation Forest baselines.
- **Analysis:** six pre-stated hypotheses with McNemar/Fisher tests,
  bootstrap confidence intervals and Holm correction; emulation validity for
  the hardware arm.
- **Tools:** `rootlinectl` (Go fault controller), the snapshotter (Go),
  `rootline` (Rust replay CLI), the results site (static, DuckDB-WASM), the
  Typst technical report.

## Reproduce

```bash
make data
```

```bash
make reproduce
```

```bash
make paper
```

## Data and licences

Code: Apache-2.0. Dataset (Hugging Face): CC BY 4.0, with `SHA256SUMS`.

## Known limitations

One testbed; emulated network faults (compared with real Wi-Fi faults in the
hardware arm); models may have seen the demo's public code (P1 measures
reliance on names); hardware snapshots include the relay's own telemetry;
free-tier limits changed during 2026, so the provider is recorded per run.

## Next (v0.2)

Red-herring (P2) and reordered-evidence (P3) perturbations, the private
holdout for contamination checks, and the DOI in `CITATION.cff`.
