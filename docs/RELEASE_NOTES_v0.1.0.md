# Rootline v0.1.0: pilot release

Rootline is an open, reproducible benchmark and replay app for
evidence-grounded AI diagnosis of microservice failures, built at $0 with
free and open models.

v0.1 answers two questions: **which telemetry signals a model needs to find
the root cause (RQ1)**, and **whether it can tell a network fault from an
application fault (RQ2)**. Four more pre-stated questions are held for v0.2.

**Results:** see the technical report (`paper/rootline-v0.1.pdf`) and
`paper/figures/results.json`. Every number there is produced by
`make reproduce` from the published runs. This is a pilot: two replicas per
incident type give wide confidence intervals, and negative results are
reported as they are.

## What is in this release

- **Testbed and faults:** 15 incident types on the OpenTelemetry Demo 3.1.0
  (10 feature-flag application faults, 4 Toxiproxy/netem network faults,
  1 healthy control), plus 3 real Wi-Fi faults through two Arduino UNO Q
  boards, triggered unattended over SSH.
- **Snapshots:** 42 frozen incidents (30 pilot, 12 hardware): spans, metrics
  and logs as Parquet, with manifests pinning the demo tag and image digests.
- **Models:** gpt-oss-120b (Groq free tier), Qwen3 8B and Gemma 3 4B
  (Ollama, 4-bit), each scored on four evidence conditions within the same
  6,000-token budget, at temperature 0, with a strict output contract.
- **Scoring:** service and category (top-1, top-3), layer attribution,
  evidence validity (cited lines must exist and belong to the root cause),
  healthy false alarms and calibration.
- **Analysis:** RQ1 and RQ2 with McNemar and Fisher exact tests, bootstrap
  confidence intervals and Holm correction; emulation validity for the
  hardware arm; a fault-visibility check showing which faults left a trace
  in their own snapshot.
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

Code: Apache-2.0. Dataset on Hugging Face (`Flotrpy/rootline`): CC BY 4.0,
with `SHA256SUMS`.

## Known limitations

A small pilot on one testbed and one machine; two of six questions tested.
Several injected faults left little trace in the evidence (listed in the
report), including transmit-power reduction on the hardware arm. A few
services got more memory to keep the testbed up, and snapshots that
overlapped a testbed crash were rerun. Models may have seen the demo's public
code, and service names reach the model. Free-tier limits changed during
2026, so the provider is recorded per run. The full list is in the README.

## Next (v0.2)

Name reliance (RQ3), a cheap-first cascade (RQ4), live remediation trials
(RQ5) and a classical baseline (RQ6); stronger versions of the faults that
barely showed; a second testbed on Kubernetes; the DOI in `CITATION.cff`.
