// Rootline v0.1 technical report.
//
// Every number comes from figures/results.json, written by `make reproduce`
// from the published runs. Nothing here is typed by hand: if a result is
// missing, the report says "not run".
//
//   make reproduce && make paper

#let r = json("figures/results.json")

#let fmt(x, digits: 3) = if x == none { "–" } else { str(calc.round(x, digits: digits)) }
#let pct(x) = if x == none { "–" } else { str(calc.round(x * 100, digits: 1)) + "%" }
#let hyp(id) = r.hypotheses.find(h => h.rq == id)

#set document(title: "Rootline: which evidence does an AI need to find the root cause, and can it fix it?", author: "flotrpy")
#set page(paper: "a4", margin: (x: 2.2cm, y: 2.4cm), numbering: "1")
#set text(size: 10.5pt)
#set heading(numbering: "1.")
#set par(justify: true)
#show link: underline

#align(center)[
  #text(size: 16pt, weight: "bold")[Rootline: which evidence does an AI need to find the root cause, and can it fix it?]
  #v(0.4em)
  flotrpy \
  #text(size: 9pt)[Technical report v0.1 · #r.label · results are from a pilot and carry wide confidence intervals]
]

#v(0.8em)
#block(inset: (x: 1.2em))[
  *Abstract.* Rootline is an open, reproducible benchmark and replay app for
  evidence-grounded AI diagnosis of microservice failures. It injects
  controlled faults into the OpenTelemetry Demo, freezes each incident's
  telemetry into Parquet snapshots, and replays them to free and open models
  under controlled evidence conditions. It measures which telemetry signals
  models need, whether they can tell network faults from application faults,
  how much they lean on service names, how much a cheap-first cascade saves,
  whether their chosen fixes restore service, and whether they beat a
  classical baseline.
  #if r.leaderboard.len() > 0 [
    On #r.n_snapshots snapshots, the best model (#raw(r.best_model)) reached
    #pct(r.leaderboard.at(0).top1) top-1 accuracy with combined evidence
    (95% CI #pct(r.leaderboard.at(0).top1_ci_low)–#pct(r.leaderboard.at(0).top1_ci_high)).
  ]
  #let tested = r.hypotheses.filter(h => h.status == "tested")
  Of six pre-stated hypotheses, #tested.len() could be tested;
  #tested.filter(h => h.threshold_met == true).len() met their threshold and
  #tested.filter(h => h.significant == true).len() remained significant after
  Holm correction. All results are reported, including failed hypotheses.
]

= Introduction

Large language models are increasingly proposed for incident diagnosis, but
most evaluations score free-text answers with another model and say little
about _which evidence_ the model used. Rootline grades by evidence and by
execution: every evidence line has a stable ID that answers must cite, and the
chosen fix is applied to the live system. We evaluate only freely available
open-weight models and free-tier APIs; results characterise what
budget-constrained teams can achieve today, not the frontier.

Prior work. TODO(flotrpy): cite AIOpsLab, ITBench, RCAEval and the ACL 2026
survey on agent evaluation once the references are confirmed, and centre the
novelty claims on layer attribution, remediation and robustness.

= Method

== Testbed and faults
The OpenTelemetry Demo runs on Docker Compose, pinned to a release tag and
image digests recorded in every snapshot manifest. Fifteen incident types:
ten application faults from the demo's feature flags, four network faults
(Toxiproxy latency, connection resets and bandwidth limits, and `tc netem`
packet loss) and one healthy control. Each incident runs a 5-minute
baseline, 5 minutes of fault, and a snapshot of the window from 5 minutes
before to 5 minutes after onset; the controller then clears the fault and
checks recovery. Ground-truth labels are stored apart from snapshots and
never reach a model.

== Evidence conditions and perturbations
Every prompt is at most 6,000 tokens (tiktoken `cl100k_base`), so conditions
differ in signal, not size: metrics only (per-service rates, error ratios and
latency quantiles in 30-second buckets, as change from baseline), traces only
(20 slowest and 20 errored traces as critical paths), logs only (Drain3
templates ranked by rate change) and combined (a third each). Perturbation P1
replaces every service name, including inside identifiers, with a consistent
anonymous one. All fault and flag names are redacted from every pack.

== Models, output and scoring
Models answer at temperature 0 with a strict JSON contract: layer, up to
three ranked hypotheses with confidence and cited evidence IDs, and one
action from a fixed menu (restart, disable a feature, clear a network fault,
no action). Invalid output gets one retry with the validation error; a second
failure counts as an abstention. We report top-1 and top-3 accuracy on the
(service, category) pair, layer attribution, evidence validity (cited IDs
that exist and belong to the root-cause service), healthy false alarms,
Brier score and 10-bin expected calibration error.

== Statistics
McNemar's exact test for paired comparisons on the same snapshots, Fisher's
exact test for unpaired ones, #r.seeds.bootstrap_resamples\-resample bootstrap
confidence intervals (seed #r.seeds.bootstrap), and Holm correction across
the six research questions. The cascade test uses θ = #r.rq4_theta.

= Results

#figure(
  table(
    columns: (auto, 1fr, auto, auto, auto),
    align: (left, left, right, right, left),
    table.header[*RQ*][*Hypothesis*][*Effect*][*p (Holm)*][*Result*],
    ..r.hypotheses.map(h => (
      h.rq,
      h.statement,
      fmt(h.effect),
      fmt(h.p_holm),
      if h.status != "tested" { h.status }
      else if h.threshold_met == true {
        if h.significant == true { "met, significant" } else { "met, not significant" }
      } else { "not supported" },
    )).flatten()
  ),
  caption: [The six pre-stated hypotheses. Effects and tests are defined in the method; details per row are in results.json.],
)

#if r.leaderboard.len() > 0 {
  figure(
    table(
      columns: 7,
      align: (left, center, right, right, right, right, right),
      table.header[*Model*][*Tier*][*Top-1*][*Top-3*][*Layer*][*Evidence validity*][*ECE*],
      ..r.leaderboard.map(m => (
        raw(m.model_id), m.tier, pct(m.top1), pct(m.top3), pct(m.layer_acc),
        pct(m.evidence_validity), fmt(m.ece),
      )).flatten()
    ),
    caption: [Combined evidence, real service names (#r.label).],
  )
} else [No model runs yet.]

#let captions = (
  "rq1_conditions.svg": [RQ1: top-1 accuracy by evidence condition, with 95% bootstrap confidence intervals.],
  "rq2_layers.svg": [RQ2: layer-attribution accuracy by the true layer of the fault.],
  "rq4_cascade.svg": [RQ4: cascade accuracy against total tokens over θ, with each tier alone for reference.],
)
#for f in r.figures {
  figure(image("figures/" + f, width: 90%), caption: captions.at(f, default: raw(f)))
}

#if r.baselines.len() > 0 {
  figure(
    table(
      columns: 5,
      table.header[*Baseline*][*Scheme*][*n*][*Top-1*][*Service accuracy*],
      ..r.baselines.map(b => (b.model, b.scheme, str(b.n), pct(b.top1), pct(b.service_acc))).flatten()
    ),
    caption: [Classical baselines. Isolation Forest predicts no category, so it has no top-1.],
  )
}

= Hardware arm: real Wi-Fi faults

Two Arduino UNO Q boards route the checkout → payment edge over a real Wi-Fi
link, with three faults triggered on the boards: reduced transmit power,
2.4 GHz channel contention and a 30-second Wi-Fi outage. Each is compared
with its emulated counterpart.

#if r.emulation_validity.len() > 0 {
  figure(
    table(
      columns: 6,
      table.header[*Model*][*Real fault*][*Emulated*][*Top-1 real*][*Top-1 emulated*][*p (Fisher)*],
      ..r.emulation_validity.map(e => (
        raw(e.model_id), e.hardware_fault, e.emulated_fault,
        pct(e.top1_hardware), pct(e.top1_emulated), fmt(e.top1_p_fisher),
      )).flatten()
    ),
    caption: [Emulation validity: a large gap means emulated faults are not a fair stand-in for real ones.],
  )
} else [Hardware snapshots not collected yet.]

= Limitations

This is a pilot: two replicas per incident type give wide confidence
intervals. One testbed stands in for production systems that are larger and
noisier. Models may have seen the demo's public code; P1 measures reliance on
names. Hardware snapshots contain the relay's own telemetry, which emulated
snapshots do not. Free-tier limits changed during 2026, so provider choices
are recorded per run.

= Reproducibility

Code (Apache-2.0) and data (CC BY 4.0) are public. `make reproduce`
regenerates every table and figure in this report from the published runs
without network access. Inputs: #r.inputs.runs runs
(sha256 #raw(if r.inputs.runs_sha256 == none { "–" } else { r.inputs.runs_sha256.slice(0, 12) })),
#r.inputs.remediation_trials remediation trials.

AI tools assisted with writing the code.
