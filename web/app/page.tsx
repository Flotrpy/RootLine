import Link from "next/link";

import { BoardFigure } from "@/components/BoardFigure";
import { EvidenceSwitcher } from "@/components/EvidenceSwitcher";
import { FaultLedger } from "@/components/FaultLedger";
import { HeroMap } from "@/components/HeroMap";
import { ProtocolScrubber } from "@/components/ProtocolScrubber";
import { WiringDiagram } from "@/components/WiringDiagram";
import { getHypotheses, getSite, getSummary, photo } from "@/lib/data";
import { num, pct } from "@/lib/format";

const REPO = "https://github.com/Flotrpy/RootLine";

// The v0.1 run design. These are the plan's counts, not results.
const MODELS = [
  { id: "gpt-oss-120b@groq", size: "120B", where: "Groq free tier", tier: "C" },
  { id: "qwen3-8b-q4@ollama", size: "8B, 4-bit", where: "Ollama, on the laptop", tier: "B" },
  { id: "gemma3-4b-q4@ollama", size: "4B, 4-bit", where: "Ollama, on the laptop", tier: "A" },
];
const SNAPSHOTS = 42; // 30 pilot (15 types × 2) + 12 hardware (3 × 4)
const CONDITIONS = 4;

const RQ = {
  RQ1: {
    q: "Which signals does a model need to find the cause?",
    why: "Teams pay to keep metrics, traces and logs. If one signal carries most of the answer, budget-constrained teams can keep less.",
    measure: "Top-1 accuracy of the strongest model with combined evidence against its best single signal, on the same snapshots.",
    test: "McNemar exact test; threshold +10 points.",
  },
  RQ2: {
    q: "Can a model tell a broken link from a broken service?",
    why: "A slow network and a slow service look alike from the caller's side. Restarting a healthy service does nothing for a degraded link.",
    measure: "Layer accuracy (application, network or none) on network faults against application faults.",
    test: "Fisher exact test; threshold 15 points lower on network faults.",
  },
} as const;

const LIMITS = [
  ["A small pilot", "Two replicas of each incident type: 30 snapshots. Confidence intervals are wide, and a result that misses significance may only mean the sample is too small."],
  ["Two questions, not six", "Name reliance, cascades, whether fixes work and classical baselines are held for v0.2."],
  ["One testbed, one laptop", "The OpenTelemetry Demo 3.1.0 on Docker Compose under 20 simulated users. Production systems are larger and less tidy."],
  ["Changed resource limits", "A few services, the database among them, got more memory so the testbed itself stayed up. Snapshots hit by a testbed crash were moved aside and run again."],
  ["Faults a model may have seen", "The application faults are the demo's public feature flags. Fault names never reach a model, service names do."],
  ["Free models only", "Open-weight models and free tiers, one run per snapshot and condition at temperature 0. Hosted models can change without notice."],
];

export default function Home() {
  const site = getSite();
  const hyp = getHypotheses().filter((h) => h.rq === "RQ1" || h.rq === "RQ2");
  const board = getSummary()
    .filter((r) => r.condition === "combined" && r.perturbation === "p0")
    .sort((a, b) => (b.top1 ?? 0) - (a.top1 ?? 0) || a.model_id.localeCompare(b.model_id));
  const hasResults = board.length > 0;

  return (
    <>
      {/* 00 · Hero */}
      <section className="hero" aria-labelledby="hero-title">
        <div className="wrap hero-grid">
          <div className="hero-copy">
            <div>
              <p className="eyebrow">
                <b>●</b> Open benchmark · {site.label}
              </p>
              <h1 id="hero-title">
                When the shop breaks, can an AI find <em>why</em>?
              </h1>
              <p className="lede">
                Rootline breaks a real microservice shop on purpose, freezes what its engineers would
                see, and asks free, open AI models for the root cause. It measures which evidence they
                need, and whether they can tell a broken network from a broken service.
              </p>
              <div className="hero-actions">
                <a className="btn" href="#results">
                  See the results <span className="arr">→</span>
                </a>
                <a className="btn ghost" href={REPO}>
                  Code and data <span className="arr">↗</span>
                </a>
              </div>
            </div>
            <ul className="facts" aria-label="The study in numbers">
              <li>
                <span className="n">15</span>
                <span className="k">incident types</span>
              </li>
              <li>
                <span className="n">{SNAPSHOTS}</span>
                <span className="k">frozen snapshots</span>
              </li>
              <li>
                <span className="n">{MODELS.length}</span>
                <span className="k">open-weight models</span>
              </li>
              <li>
                <span className="n">2</span>
                <span className="k">Arduino UNO Q boards</span>
              </li>
            </ul>
          </div>
          <div className="hero-stage">
            <HeroMap />
          </div>
        </div>
      </section>

      {/* 01 · Problem */}
      <section className="sec" id="problem" aria-labelledby="problem-title">
        <div className="wrap">
          <div className="sec-head rv">
            <p className="sec-num">
              <b>01</b> / The problem
            </p>
            <h2 id="problem-title">
              Everyone wants AI on call. Nobody checks <em>what it looked at.</em>
            </h2>
          </div>
          <div className="cols split">
            <aside className="margin-note rv">
              <span className="eyebrow">Root cause</span>
              The one component whose failure explains every symptom. Fix it and the rest recovers;
              fix anything else and nothing changes.
            </aside>
            <div className="prose rv">
              <p>
                When a web shop fails, the error shows up far from where it started. A checkout page
                times out because payment is slow, because a link is dropping packets, because a radio
                is weak. Engineers trace back through metrics, traces and logs until they find the one
                thing that broke.
              </p>
              <p>
                Language models are now pitched for that job. But most evaluations grade a free-text
                answer with another model, and say little about which evidence the answer rests on, or
                whether the model can tell a network problem from an application one.
              </p>
              <p className="pull">
                Rootline grades by evidence: every line a model sees has an ID, and an answer only
                counts if it cites lines that exist.
              </p>
            </div>
            <div className="rv">
              <div className="artifact">
                <div className="artifact-bar">
                  <span>prompt.py · the exact instructions</span>
                  <span>every model, every run</span>
                </div>
                <pre>
                  <span className="c">{"# excerpt"}</span>
                  {"\n"}You are the on-call engineer for a microservice web shop. Below is telemetry from a
                  10-minute window; &quot;fault onset&quot; is the midpoint. The window may contain a fault,
                  or the system may be healthy.{"\n\n"}Find the root cause using only the evidence below.
                  {"\n\n"}
                  <span className="k">Layers:</span> application (the service itself is broken), network
                  (the link between services is degraded), none (healthy).{"\n\n"}
                  <span className="k">Rules:</span> give up to 3 hypotheses ranked best first; cite only
                  IDs that appear below; confidence is your probability that the hypothesis is right.
                </pre>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 02 · Method */}
      <section className="sec" id="method" aria-labelledby="method-title">
        <div className="wrap">
          <div className="sec-head rv">
            <p className="sec-num">
              <b>02</b> / The method
            </p>
            <h2 id="method-title">
              Break it, freeze it, <em>replay it,</em> score it.
            </h2>
          </div>
          <ol className="steps rv">
            <li>
              <span className="i">i.</span>
              <h3>Break</h3>
              <p>A Go controller injects one of 15 incident types into the OpenTelemetry Demo, a shop of about 20 services under steady load.</p>
              <span className="tech">flagd · Toxiproxy · tc netem · SSH to the boards</span>
            </li>
            <li>
              <span className="i">ii.</span>
              <h3>Freeze</h3>
              <p>Ten minutes of spans, metrics and logs around the fault are written to Parquet. The answer is stored apart.</p>
              <span className="tech">OTLP · Apache Arrow · Parquet</span>
            </li>
            <li>
              <span className="i">iii.</span>
              <h3>Replay</h3>
              <p>The same frozen snapshot goes to every model, packed into the same 6,000 tokens, under four evidence conditions.</p>
              <span className="tech">Polars · Drain3 · tiktoken</span>
            </li>
            <li>
              <span className="i">iv.</span>
              <h3>Score</h3>
              <p>Answers follow a strict JSON contract and are scored for service, category, layer and cited evidence.</p>
              <span className="tech">Pydantic · exact tests · bootstrap CIs</span>
            </li>
          </ol>

          <div className="cols method-detail">
            <div className="rv">
              <p className="eyebrow">One incident · drag the timeline</p>
            </div>
            <div className="rv">
              <ProtocolScrubber />
            </div>
          </div>

          <div className="cols method-detail">
            <div className="rv">
              <p className="eyebrow">15 incident types · filter, open a row</p>
              <p className="margin-note">
                Application faults use the demo&apos;s own feature flags. Network faults degrade one
                link between two services. The healthy control checks for false alarms.
              </p>
            </div>
            <div className="rv">
              <FaultLedger />
            </div>
          </div>
        </div>
      </section>

      {/* 03 · Questions */}
      <section className="sec" id="questions" aria-labelledby="q-title">
        <div className="wrap">
          <div className="sec-head rv">
            <p className="sec-num">
              <b>03</b> / Two questions
            </p>
            <h2 id="q-title">
              What evidence it needs, and <em>where</em> it thinks the fault is.
            </h2>
          </div>
          <div className="qs rv">
            {(Object.keys(RQ) as (keyof typeof RQ)[]).map((k) => (
              <article className="q" key={k}>
                <span className="id">{k}</span>
                <h3>{RQ[k].q}</h3>
                <dl>
                  <dt>Why</dt>
                  <dd>{RQ[k].why}</dd>
                  <dt>Measure</dt>
                  <dd>{RQ[k].measure}</dd>
                  <dt>Test</dt>
                  <dd>{RQ[k].test}</dd>
                </dl>
              </article>
            ))}
          </div>
          <div className="cols method-detail">
            <div className="rv">
              <p className="eyebrow">RQ1 · what a model receives</p>
              <p className="margin-note">Pick a condition. The token budget never changes, only what fills it.</p>
            </div>
            <div className="rv">
              <EvidenceSwitcher />
            </div>
          </div>
          <p className="q-deferred rv">
            Four more questions (name reliance, cheap-first cascades, whether fixes work, classical
            baselines) are written and pre-stated, and held for v0.2.
          </p>
        </div>
      </section>

      {/* 04 · Results */}
      <section className="sec" id="results" aria-labelledby="results-title">
        <div className="wrap">
          <div className="sec-head rv">
            <p className="sec-num">
              <b>04</b> / Results
            </p>
            <h2 id="results-title">
              {hasResults ? (
                <>
                  What the models <em>found.</em>
                </>
              ) : (
                <>
                  Runs in progress. <em>No numbers yet.</em>
                </>
              )}
            </h2>
          </div>

          {hasResults ? (
            <>
              <div className="table-scroll rv">
                <table>
                  <thead>
                    <tr>
                      <th>Model</th>
                      <th>Tier</th>
                      <th>Top-1 (95% CI)</th>
                      <th>Top-3</th>
                      <th>Layer</th>
                      <th>Evidence validity</th>
                      <th>Healthy false alarms</th>
                    </tr>
                  </thead>
                  <tbody>
                    {board.map((r) => (
                      <tr key={r.model_id}>
                        <td className="mono">{r.model_id}</td>
                        <td>{r.tier}</td>
                        <td className="num">
                          {pct(r.top1)}{" "}
                          <span style={{ color: "var(--muted)" }}>
                            ({pct(r.top1_ci_low)}–{pct(r.top1_ci_high)})
                          </span>
                        </td>
                        <td className="num">{pct(r.top3)}</td>
                        <td className="num">{pct(r.layer_acc)}</td>
                        <td className="num">{pct(r.evidence_validity)}</td>
                        <td className="num">{pct(r.healthy_false_alarm_rate)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {hyp.length > 0 && (
                <div className="qs results-q rv">
                  {hyp.map((h) => (
                    <article className="q" key={h.rq}>
                      <span className="id">{h.rq}</span>
                      <h3>{h.statement}</h3>
                      <dl>
                        <dt>Effect</dt>
                        <dd className="mono">{num(h.effect)}</dd>
                        <dt>p (Holm)</dt>
                        <dd className="mono">{num(h.p_holm)}</dd>
                        <dt>Result</dt>
                        <dd>
                          {h.status !== "tested" ? (
                            <span className="pill quiet">{h.status}</span>
                          ) : h.threshold_met ? (
                            <span className="pill">threshold met{h.significant ? ", significant" : ", not significant"}</span>
                          ) : (
                            <span className="pill bad">not supported</span>
                          )}
                        </dd>
                      </dl>
                    </article>
                  ))}
                </div>
              )}
              <p className="q-deferred rv">
                Every negative result is reported too. Replay any snapshot on the{" "}
                <Link href="/incidents/">incidents</Link> pages.
              </p>
            </>
          ) : (
            <div className="result-empty rv">
              <div>
                <p className="status">Collecting</p>
                <h3>The table fills itself from the runs.</h3>
                <p>
                  Nothing here is typed by hand. When the scoring runs finish, <code>make reproduce</code>{" "}
                  writes every table and chart from the run records, and this section shows them, including
                  results that go against the hypotheses.
                </p>
              </div>
              <div>
                <table className="matrix">
                  <caption className="sr-only">The v0.1 run plan</caption>
                  <thead>
                    <tr>
                      <th scope="col">Model</th>
                      <th scope="col">Size</th>
                      <th scope="col" className="hide-sm">Runs on</th>
                      <th scope="col" className="num">Runs</th>
                    </tr>
                  </thead>
                  <tbody>
                    {MODELS.map((m) => (
                      <tr key={m.id}>
                        <td className="mono">{m.id}</td>
                        <td>{m.size}</td>
                        <td className="hide-sm">{m.where}</td>
                        <td className="num">{SNAPSHOTS * CONDITIONS}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td colSpan={2}>
                        {SNAPSHOTS} snapshots × {CONDITIONS} conditions × {MODELS.length} models
                      </td>
                      <td className="hide-sm" />
                      <td className="num">{SNAPSHOTS * CONDITIONS * MODELS.length}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* 05 · Hardware */}
      <section className="sec" id="hardware" aria-labelledby="hw-title">
        <div className="wrap">
          <div className="sec-head rv">
            <p className="sec-num">
              <b>05</b> / Hardware
            </p>
            <h2 id="hw-title">
              Two small boards, one <em>real</em> radio link.
            </h2>
          </div>
          <div className="cols">
            <p className="margin-note rv">
              Emulated faults are tidy. Real Wi-Fi is not. The hardware arm checks whether models read
              a genuinely degraded link the way they read an emulated one.
            </p>
            <div>
              <div className="boards">
                <div className="board rv">
                  <BoardFigure board="A" photo={photo("board-a")} />
                  <h3>Board A, the relay</h3>
                  <ul className="spec">
                    <li><span>Name</span><span>affan1</span></li>
                    <li><span>Job</span><span>Carries checkout → payment over Wi-Fi</span></li>
                    <li><span>Faults</span><span>Weak signal, 30-second Wi-Fi outage</span></li>
                  </ul>
                </div>
                <div className="board rv">
                  <BoardFigure board="B" photo={photo("board-b")} />
                  <h3>Board B, the crowd</h3>
                  <ul className="spec">
                    <li><span>Name</span><span>affan2</span></li>
                    <li><span>Job</span><span>Crowds the 2.4 GHz channel on cue</span></li>
                    <li><span>Faults</span><span>Channel contention</span></li>
                  </ul>
                </div>
              </div>
              <div className="wiring rv">
                <p className="eyebrow">How it is wired · switch a fault on</p>
                <WiringDiagram />
              </div>
              <p className="q-deferred rv">
                All three hardware faults run unattended over SSH, and each board schedules its own undo,
                so a lost connection never leaves a fault in place. <Link href="/hardware/">Hardware details</Link>
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 06 · Limits */}
      <section className="sec" id="limits" aria-labelledby="limits-title">
        <div className="wrap">
          <div className="sec-head rv">
            <p className="sec-num">
              <b>06</b> / Limitations
            </p>
            <h2 id="limits-title">
              What this pilot <em>cannot</em> tell you.
            </h2>
          </div>
          <div className="cols">
            <p className="margin-note rv">
              Read every result with these in mind. The full list is in the repository&apos;s README.
            </p>
            <ol className="limits rv">
              {LIMITS.map(([t, d]) => (
                <li key={t}>
                  <div>
                    <strong>{t}</strong>
                    <p>{d}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>

      {/* 07 · Open */}
      <section className="sec" id="open" aria-labelledby="open-title">
        <div className="wrap">
          <div className="sec-head rv">
            <p className="sec-num">
              <b>07</b> / Open
            </p>
            <h2 id="open-title">
              Check our work. <em>Rerun it.</em>
            </h2>
          </div>
          <div className="open-grid rv">
            <a className="open-link" href={REPO}>
              <span className="eyebrow">Apache-2.0</span>
              <h3>
                Code <span className="arr">↗</span>
              </h3>
              <p>Controller, snapshotter, harness, analysis, this site and the board software.</p>
            </a>
            <Link className="open-link" href="/incidents/">
              <span className="eyebrow">In the browser</span>
              <h3>
                Replay <span className="arr">→</span>
              </h3>
              <p>Open any snapshot: the service graph, the evidence a model saw, and its answer.</p>
            </Link>
            <a className="open-link" href={`${REPO}#running-the-models`}>
              <span className="eyebrow">CC BY 4.0</span>
              <h3>
                Reproduce <span className="arr">↗</span>
              </h3>
              <p>
                <code>make data &amp;&amp; make reproduce</code> rebuilds every table and chart from the
                published runs.
              </p>
            </a>
          </div>
        </div>
      </section>
    </>
  );
}
