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
#let D = r.at("discussion", default: (:))
#let drows(k) = D.at(k, default: ())
#let dfind(k, m) = drows(k).find(x => x.model_id == m)
#let dgroup(m, g) = drows("by_layer").find(x => x.model_id == m and x.group == g)
#let dcond(m, c) = drows("by_condition").find(x => x.model_id == m and x.condition == c)
#let dcondv(m, c, f) = { let x = dcond(m, c); if x == none { none } else { x.at(f) } }
#let G = "gemma3-4b-q4@ollama"
#let Q = "qwen3-8b-q4@ollama"

#set document(title: "Rootline: which evidence does an AI need to find the root cause, and can it fix it?", author: "Affan Shaik")
#set page(paper: "a4", margin: (x: 2.2cm, y: 2.4cm), numbering: "1")
#set text(size: 10.5pt)
#set heading(numbering: "1.")
#set par(justify: true)
#show link: underline

#align(center)[
  #text(size: 16pt, weight: "bold")[Rootline: which evidence does an AI need to find the root cause, and can it fix it?]
  #v(0.4em)
  Affan Shaik · #link("https://orcid.org/0009-0008-6203-3226")[ORCID 0009-0008-6203-3226] \
  #text(size: 9pt)[Technical report v0.1 · #r.label · results are from a pilot and carry wide confidence intervals]
]

#v(0.8em)
#block(inset: (x: 1.2em))[
  *Abstract.* Rootline is an open, reproducible benchmark and replay app for
  evidence-grounded AI diagnosis of microservice failures. It injects
  controlled faults into the OpenTelemetry Demo, freezes each incident's
  telemetry into Parquet snapshots, and replays them to free and open models
  under controlled evidence conditions. This first release asks two
  questions: which telemetry signals models need, and whether they can tell
  network faults from application faults.
  #if r.leaderboard.len() > 0 [
    On #r.n_snapshots snapshots, the best model (#raw(r.best_model)) reached
    #pct(r.leaderboard.at(0).top1) top-1 accuracy with combined evidence
    (95% CI #pct(r.leaderboard.at(0).top1_ci_low)–#pct(r.leaderboard.at(0).top1_ci_high)).
    #if drows("calibration").len() > 0 [
      Models were confident far beyond their accuracy (mean top confidence
      #pct(calc.min(..drows("calibration").map(x => x.mean_confidence)))–#pct(calc.max(..drows("calibration").map(x => x.mean_confidence)))),
      #let fa = drows("false_alarm_targets")
      #if fa.all(x => x.fault_claims == x.answers) [and every model claimed a fault on every healthy snapshot.] else [and models often claimed a fault on healthy snapshots.]
    ]
  ]
  #let tested = r.hypotheses.filter(h => h.status == "tested")
  This first release tests two of six pre-stated hypotheses (RQ1, RQ2); the
  other four are held for v0.2. #tested.len() could be tested;
  #tested.filter(h => h.threshold_met == true).len() met their threshold and
  #tested.filter(h => h.significant == true).len() remained significant after
  Holm correction. All results are reported, including failed hypotheses.
]

= Introduction

Large language models are increasingly proposed for incident diagnosis, but
most evaluations score free-text answers with another model and say little
about _which evidence_ the model used. Rootline grades by evidence and by
execution: every evidence line has a stable ID that answers must cite, and the
chosen fix can be applied to the live system (remediation is scored from
v0.2). We evaluate only freely available
open-weight models and free-tier APIs; results characterise what
budget-constrained teams can achieve today, not the frontier.

Prior work. AIOpsLab @aiopslab deploys microservice environments, injects
faults and evaluates agents that act on the live system. ITBench @itbench
collects real-world IT automation scenarios for agents across SRE,
compliance and FinOps tasks. RCAEval @rcaeval provides 735 failure cases from
three microservice systems with metrics, logs and traces, and fifteen
root-cause-analysis baselines. Rootline is smaller and narrower: it holds the
prompt budget fixed while varying which signals fill it, asks whether a
model can place a fault in the network or the application, checks that cited
evidence exists, and adds real Wi-Fi faults on hardware next to their
emulated counterparts.

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
the hypotheses tested in this release (RQ1 and RQ2). RQ3 (name reliance),
RQ4 (cascade), RQ5 (remediation) and RQ6 (classical baseline) are deferred
to v0.2 and not tested here.

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
  caption: [The six pre-stated hypotheses. v0.1 tests RQ1 and RQ2; the rest are deferred to v0.2. Effects and tests are defined in the method; details per row are in results.json.],
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

== Results by evidence condition

#if drows("by_condition").len() > 0 {
  let models = drows("by_condition").map(x => x.model_id).dedup()
  figure(
    table(
      columns: 9,
      align: (left, right, right, right, right, right, right, right, right),
      table.header(
        table.cell(rowspan: 2)[*Model*],
        table.cell(colspan: 4)[*Top-1*], table.cell(colspan: 4)[*Layer*],
        [Metrics], [Traces], [Logs], [Combined], [Metrics], [Traces], [Logs], [Combined],
      ),
      ..models.map(m => (
        raw(m),
        ..("metrics", "traces", "logs", "combined").map(c => pct(dcondv(m, c, "top1"))),
        ..("metrics", "traces", "logs", "combined").map(c => pct(dcondv(m, c, "layer_acc"))),
      )).flatten()
    ),
    caption: [Every model on every snapshot under each evidence condition, real service names. All conditions share the same 6,000-token budget.],
  )
}

== Exploratory: either end of a broken link <tab-either>

_Not pre-registered; it does not change any result above._ For a fault on a
link, the pre-registered scoring expects the downstream service (payment for
checkout → payment). Models often name the caller. Here the same answers are
re-scored with one change: for link faults, naming either end of the link
with the right category counts as correct.

#if r.exploratory_edge_scoring.len() > 0 {
  figure(
    table(
      columns: 6,
      align: (left, right, right, right, right, right),
      table.header[*Model*][*Top-1*][*Top-1, either end*][*Link faults*][*Link top-1*][*Link top-1, either end*],
      ..r.exploratory_edge_scoring.map(e => (
        raw(e.model_id), pct(e.top1_official), pct(e.top1_either_end),
        str(e.n_edge_faults), pct(e.edge_top1_official), pct(e.edge_top1_either_end),
      )).flatten()
    ),
    caption: [Combined evidence, unperturbed. Exploratory re-scoring of the same answers; the hypothesis tests use the pre-registered rule.],
  )
}

== Manipulation check <visibility>

Does each injected fault show in its own snapshot? For every snapshot, the
spans that should carry the fault (the caller's calls across a broken edge,
or the root-cause service's own spans) before and after fault onset.

#if r.fault_visibility.len() > 0 {
  figure(
    table(
      columns: 6,
      align: (left, left, right, right, right, right),
      table.header[*Snapshot*][*Measured*][*Errors before*][*Errors after*][*p95 before (ms)*][*p95 after (ms)*],
      ..r.fault_visibility.map(v => (
        raw(v.incident_id), v.measured, pct(v.error_rate_before), pct(v.error_rate_after),
        fmt(v.before_p95_ms, digits: 0), fmt(v.after_p95_ms, digits: 0),
      )).flatten()
    ),
    caption: [Fault visibility per snapshot, from the frozen telemetry only (no model).],
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

= Discussion

#let B = r.best_model
#let cb = dfind("calibration", B)
#let cg = dfind("calibration", G)
#let cq = dfind("calibration", Q)
#let la-g = dfind("layer_answers", G)
#let la-q = dfind("layer_answers", Q)
#let la-b = dfind("layer_answers", B)
#let fb = dfind("false_alarm_targets", B)
#let hw-b = dgroup(B, "hardware (network)")
#let net-b = dgroup(B, "network")
#let have(..xs) = xs.pos().all(x => x != none)

#if have(cb) [
  == Mostly wrong, and confidently so
  The headline is negative. With combined evidence the strongest model named
  the right service and category first in #pct(cb.top1) of snapshots, yet
  its top hypothesis carried a mean stated confidence of
  #pct(cb.mean_confidence).
  #if have(cg, cq) [The small models were more confident still
  (#pct(cg.mean_confidence) and #pct(cq.mean_confidence)) and less often
  right (#pct(cg.top1) and #pct(cq.top1)).]
  A team that acted on the confidence field would be misled: none of the
  models is calibrated well enough for its confidence to separate good
  answers from bad ones.
]

#if have(la-g, la-q, la-b, dgroup(G, "application"), dgroup(G, "network")) [
  == A layer answer can be a default, not a judgement
  Layer accuracy looks better than service accuracy, but the answers show
  why. Gemma 3 4B answered "application" on all #la-g.application of
  #(la-g.application + la-g.network + la-g.none + la-g.unparsed) snapshots,
  so its #pct(dgroup(G, "application").layer_acc) on application faults and
  #pct(dgroup(G, "network").layer_acc) on network faults measure a habit, not
  a skill. Qwen3 8B leaned the other way (#la-q.network network answers
  against #la-q.application application answers). Only the strongest model
  split its answers (#la-b.application application, #la-b.network network)
  in a way that tracked the faults. Layer accuracy should therefore be read
  next to the answer distribution, and v0.2 should report balanced accuracy.
]

#if r.at("exploratory_edge_scoring", default: ()).len() > 0 [
  == The caller gets the blame on broken links
  On faults that sit on a link, the strongest model got the layer right in
  more than half of them and the kind of fault in a few, and in most it named
  the caller (checkout) as the root cause rather than the service at the far
  end (payment), which the pre-registered rule scores. Under that rule no
  model got any link fault exactly right. The exploratory re-scoring in
  @tab-either shows how much this one rule decides. Both readings are
  defensible: from the caller's spans, the slow or failing dependency is
  visible but the fault itself is not. A benchmark that wants to separate
  "where it hurts" from "what broke" has to ask for both.
]

#if have(hw-b, net-b) [
  == Real radio faults read more like network faults
  For the strongest model, layer accuracy on the hardware faults was
  #pct(hw-b.layer_acc) (#hw-b.n snapshots), against #pct(net-b.layer_acc)
  on the emulated network faults (#net-b.n snapshots). This was not tested
  and the samples are small, but it fits the manipulation check: the Wi-Fi
  outage and contention produced clearly slow and failing calls, while
  several emulated faults (connection resets on a link that keeps one
  connection open, light packet loss) barely moved the evidence. An emulated
  fault that leaves no trace cannot be diagnosed, so emulation validity
  should be judged on faults that are visible in both settings.
]

#if have(fb) [
  == Nothing was ever "nothing"
  On the healthy snapshots, across all evidence conditions, the strongest
  model claimed a fault in #fb.fault_claims of #fb.answers answers#if fb.most_blamed != none [ and blamed #raw(fb.most_blamed) most often]#if drows("false_alarm_targets").all(x => x.fault_claims == x.answers) [; every other model also claimed a fault in every answer].
  Ordinary background noise in a live shop, such as the occasional failed
  request or a service that logs errors by design, was enough to produce a
  confident diagnosis. A useful assistant has to be able to say "no fault";
  v0.2 needs more healthy snapshots to measure this properly.
]

#if have(dcond(B, "combined"), dcond(B, "logs"), dcond(B, "metrics"), dcond(B, "traces")) [
  == More evidence did not help
  RQ1 expected combined evidence to beat the best single signal. For the
  strongest model, combined evidence scored #pct(dcond(B, "combined").top1)
  top-1 against #pct(dcond(B, "logs").top1) for logs and
  #pct(dcond(B, "metrics").top1) for metrics alone, while traces alone
  scored #pct(dcond(B, "traces").top1). Because every condition has the same
  budget, the combined pack carries only a third of each signal. With
  answers this rarely right, the difference is within noise, but the design
  question stands: at a fixed budget, breadth costs depth.
]

== What v0.2 should change
Report balanced layer accuracy and ask for both the symptom and the cause on
link faults; add healthy snapshots; strengthen or replace the faults that
left no trace; run each job more than once, since hosted models were not
fully deterministic at temperature 0; and test the four held-back questions
(name reliance, cascades, remediation and the classical baseline).

= Limitations

This is a pilot: two replicas per incident type give wide confidence
intervals, and this release tests two of six pre-stated hypotheses. One
testbed on one machine stands in for production systems that are larger and
noisier, and a few services were given more memory to keep the testbed
itself up; snapshots that overlapped a testbed crash were rerun. Models may
have seen the demo's public code, and service names reach the model (name
reliance, RQ3, is v0.2). Several injected faults left little trace in the
evidence (@visibility); they are scored as they are. On hardware, lowering
transmit power left no visible trace with the board near the router, and the
relay sent no telemetry of its own. Free-tier limits changed during 2026, so
provider choices are recorded per run.

= Reproducibility

Code (Apache-2.0) and data (CC BY 4.0) are public. `make reproduce`
regenerates every table and figure in this report from the published runs
without network access. Inputs: #r.inputs.runs runs
(sha256 #raw(if r.inputs.runs_sha256 == none { "–" } else { r.inputs.runs_sha256.slice(0, 12) })),
#r.inputs.remediation_trials remediation trials.

AI tools assisted with writing the code.

#bibliography("refs.yml", title: "References")
