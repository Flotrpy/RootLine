import Link from "next/link";

import { getHypotheses, getSite, getSummary } from "@/lib/data";
import { num, pct } from "@/lib/format";

export default function Home() {
  const site = getSite();
  const summary = getSummary();
  const hypotheses = getHypotheses();
  const leaderboard = summary
    .filter((r) => r.condition === "combined" && r.perturbation === "p0")
    .sort((a, b) => (b.top1 ?? 0) - (a.top1 ?? 0) || a.model_id.localeCompare(b.model_id));

  return (
    <>
      <h1>Which evidence does an AI need to find the root cause, and can it fix it?</h1>
      <p className="lede">
        Rootline breaks a microservice shop in controlled ways, freezes the telemetry, and asks
        free and open models what went wrong and how to fix it. <span className="pill">{site.label}</span>
      </p>

      <h2>Research questions</h2>
      {hypotheses.length === 0 ? (
        <div className="card empty">
          No results yet. Hypothesis tests appear here once the pilot runs are published.
        </div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>RQ</th>
                <th>Hypothesis</th>
                <th>Effect</th>
                <th>p (Holm)</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {hypotheses.map((h) => (
                <tr key={h.rq}>
                  <td>{h.rq}</td>
                  <td>
                    {h.statement}
                    {h.detail && <div className="mono" style={{ color: "var(--muted)" }}>{h.detail}</div>}
                  </td>
                  <td className="num">{num(h.effect)}</td>
                  <td className="num">{num(h.p_holm)}</td>
                  <td>
                    {h.status !== "tested" ? (
                      <span className="pill quiet">{h.status}</span>
                    ) : h.threshold_met ? (
                      <span className="pill">threshold met{h.significant ? ", significant" : ""}</span>
                    ) : (
                      <span className="pill bad">not supported</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>Leaderboard: combined evidence</h2>
      {leaderboard.length === 0 ? (
        <div className="card empty">No model runs yet.</div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th>Tier</th>
                <th>Top-1 (95% CI)</th>
                <th>Top-3</th>
                <th>Layer</th>
                <th>Evidence validity</th>
                <th>Invalid output</th>
                <th>Healthy false alarms</th>
                <th>ECE</th>
                <th>Tokens</th>
              </tr>
            </thead>
            <tbody>
              {leaderboard.map((r) => (
                <tr key={r.model_id}>
                  <td className="mono">{r.model_id}</td>
                  <td>{r.tier}</td>
                  <td className="num">
                    {pct(r.top1)} <span style={{ color: "var(--muted)" }}>({pct(r.top1_ci_low)}–{pct(r.top1_ci_high)})</span>
                  </td>
                  <td className="num">{pct(r.top3)}</td>
                  <td className="num">{pct(r.layer_acc)}</td>
                  <td className="num">{pct(r.evidence_validity)}</td>
                  <td className="num">{pct(r.invalid_output_rate)}</td>
                  <td className="num">{pct(r.healthy_false_alarm_rate)}</td>
                  <td className="num">{num(r.ece)}</td>
                  <td className="num">{(r.prompt_tokens + r.completion_tokens).toLocaleString("en")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>Explore</h2>
      <div className="grid">
        <Link href="/incidents/" className="card">
          <strong>Incidents</strong>
          <p>Replay any snapshot: the service graph, the evidence each model saw, and what it answered.</p>
        </Link>
        <Link href="/method/" className="card">
          <strong>Method</strong>
          <p>Faults, evidence conditions, metrics, statistics and limitations.</p>
        </Link>
      </div>
    </>
  );
}
