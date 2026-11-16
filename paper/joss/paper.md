---
title: 'Rootline: a reproducible benchmark for evidence-grounded AI diagnosis of microservice failures'
tags:
  - root cause analysis
  - observability
  - OpenTelemetry
  - large language models
  - benchmark
authors:
  # TODO(flotrpy): JOSS needs your full name, ORCID and affiliation.
  - name: flotrpy
    affiliation: 1
affiliations:
  - name: Independent researcher
    index: 1
date: 16 November 2026
bibliography: paper.bib
---

# Summary

When a web application fails, the error usually surfaces far from its
cause: a checkout page times out because a payment service is slow because a
network link is dropping packets. Engineers trace back through metrics,
traces and logs to find the one component that broke. Language models are
increasingly proposed for this job, but it is hard to tell what such a model
actually used to reach its answer, or whether it can tell a broken network
link from a broken service.

Rootline is an open, reproducible benchmark and replay app for this
question. It injects controlled faults into the OpenTelemetry Demo
[@otel-demo], a microservice web shop under steady load; freezes the
telemetry around each fault into Parquet snapshots; and replays the same
snapshots to any model under controlled evidence conditions. Every line of
evidence carries a stable identifier, models answer in a strict JSON
contract that cites those identifiers, and scorers check the service,
category, network-or-application layer and cited evidence of every answer.
An optional hardware arm routes one link of the shop over real Wi-Fi through
two Arduino UNO Q boards, so real radio faults can be compared with their
emulated counterparts. Everything runs at no cost, with free and open models.

# Statement of need

Most evaluations of language models for incident diagnosis grade a
free-text answer with another model, or report a single accuracy figure on
a fixed dataset. That leaves three questions open for people who build or
choose such tools: which telemetry signals a model needs, whether it can
place a fault in the network or the application, and whether the evidence it
cites exists. Rootline is built to answer these with controlled experiments:

- **Fixed budget, varied signal.** Each prompt is capped at the same number
  of tokens, so metrics-only, traces-only, logs-only and combined conditions
  differ in what fills the budget, not in its size.
- **Layer attribution.** Network faults (latency, loss, connection resets,
  bandwidth limits) sit beside application faults, and answers are scored
  for the layer as well as the service.
- **Checkable evidence.** Answers must cite evidence identifiers; citations
  that do not exist, or point at the wrong service, are counted.
- **Frozen, shareable incidents.** Snapshots, labels and every model run are
  published, so a result can be re-scored or re-analysed without rerunning
  the testbed.

The intended users are researchers who evaluate models for operations work,
and practitioners who want to test a model on incidents before trusting it.

# State of the field

AIOpsLab [@aiopslab] deploys microservice environments, injects faults and
evaluates agents that act on the live system. ITBench [@itbench] collects
real-world IT automation scenarios across site reliability, compliance and
FinOps tasks. RCAEval [@rcaeval] provides 735 failure cases from three
microservice systems with metrics, logs and traces, and fifteen
root-cause-analysis baselines. These tools emphasise breadth, live agents or
large case collections. Rootline is narrower by design: it controls what the
model sees at a fixed budget, scores the layer of a fault separately from its
service, verifies cited evidence, and pairs emulated network faults with
real Wi-Fi faults. These controls require owning the full pipeline from
fault injection to scoring, which is why Rootline is a separate tool rather
than an extension of an existing benchmark; its snapshot format is plain
Parquet so the data can also be used with other tools.

# Software design

Rootline is split along the life of an incident, with a file format between
each stage so that every stage can be rerun or replaced on its own:

- A **Go controller** injects one of fifteen incident types through the
  demo's feature flags, Toxiproxy and `tc netem`, or over SSH on the boards,
  and runs a fixed protocol: baseline, fault, snapshot, clear, recovery
  check. Campaigns resume after interruption, and faults that end by
  themselves are handled without losing their snapshot.
- A **Go snapshotter** receives OpenTelemetry data and writes each incident
  window to Parquet with a manifest pinning the demo version and image
  digests. Ground-truth labels are stored apart from snapshots.
- A **Python harness** packs a snapshot into an evidence pack per condition,
  calls models through one client (hosted APIs and local Ollama models alike),
  waits out free-tier rate limits instead of hitting them, and stores every
  run in a resumable queue. Queues can live in a private dataset so scoring
  can continue across machines and days.
- An **analysis package** computes the pre-registered tests (McNemar and
  Fisher exact tests, bootstrap intervals, Holm correction), a
  fault-visibility manipulation check, and exploratory breakdowns, and writes
  one results file from which the README, the Typst report and the static
  results site are all generated. No number is typed by hand.
- A **Rust CLI** replays the exact evidence a model saw, and a **static
  site** (Next.js and DuckDB-WASM) lets anyone browse incidents in the
  browser.

The main trade-off is control over scale: a fixed testbed and a small number
of carefully protocolled incidents, rather than many uncontrolled ones.

# Research impact statement

The v0.1 pilot release [@rootline-v010] scored three free models on 42
snapshots (504 runs). Its main finding is negative: the models rarely named
the root cause, were confident far beyond their accuracy, and claimed a
fault on every healthy snapshot. It also showed that a single scoring rule,
which end of a broken link counts as the root cause, decides much of the
result, and that several emulated faults leave too little trace to be
diagnosable at all. These are findings about benchmark design that apply
beyond this testbed. The code, the 42 snapshots, the labels and all runs are
public, and `make data && make reproduce` regenerates every table and
figure.

# AI usage disclosure

<!-- TODO(flotrpy): JOSS requires the AI systems and versions used, where
they were used (code, documentation, this paper), and a statement that a
human reviewed and validated the output. Fill in and edit before
submitting. -->
Generative AI tools were used in writing the code, documentation and this
paper. The author reviewed and validated all generated content, and every
reported number is produced by the analysis code from the published runs.

# Acknowledgements

Thanks to the OpenTelemetry Demo maintainers, whose testbed makes this work
possible.

# References
