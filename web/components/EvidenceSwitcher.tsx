"use client";

import { useState } from "react";

// What a model receives under each evidence condition (RQ1). Every pack is
// capped at the same 6,000 tokens, so conditions differ in signal, not size.

type Cond = "metrics" | "traces" | "logs" | "combined";

const CONDS: { id: Cond; label: string; prefix: string; what: string; detail: string }[] = [
  {
    id: "metrics",
    label: "Metrics",
    prefix: "M",
    what: "Numbers over time, per service",
    detail:
      "Request rate, error ratio and latency quantiles for each service, in 30-second buckets, written as change from the 5-minute baseline.",
  },
  {
    id: "traces",
    label: "Traces",
    prefix: "T",
    what: "The path of single requests",
    detail:
      "The 20 slowest and the 20 failed requests of the window, each drawn as its critical path from service to service.",
  },
  {
    id: "logs",
    label: "Logs",
    prefix: "L",
    what: "What services wrote down",
    detail:
      "Log lines grouped into templates (Drain3), ranked by how much their rate changed after fault onset.",
  },
  {
    id: "combined",
    label: "Combined",
    prefix: "M · T · L",
    what: "A third of each",
    detail: "Metrics, traces and logs at a third of the budget each. RQ1 asks whether this beats the best single signal.",
  },
];

const SHARE: Record<Cond, Record<"metrics" | "traces" | "logs", number>> = {
  metrics: { metrics: 1, traces: 0, logs: 0 },
  traces: { metrics: 0, traces: 1, logs: 0 },
  logs: { metrics: 0, traces: 0, logs: 1 },
  combined: { metrics: 1 / 3, traces: 1 / 3, logs: 1 / 3 },
};

export function EvidenceSwitcher() {
  const [cond, setCond] = useState<Cond>("combined");
  const c = CONDS.find((x) => x.id === cond)!;
  const share = SHARE[cond];
  return (
    <div className="ev">
      <div className="tabs" role="tablist" aria-label="Evidence condition">
        {CONDS.map((x) => (
          <button
            key={x.id}
            id={`ev-tab-${x.id}`}
            type="button"
            role="tab"
            aria-selected={cond === x.id}
            aria-controls="ev-panel"
            onClick={() => setCond(x.id)}
          >
            {x.label}
          </button>
        ))}
      </div>
      <div id="ev-panel" role="tabpanel" aria-labelledby={`ev-tab-${cond}`} className="ev-panel">
        <div className="ev-budget" aria-label="How the 6,000-token budget is split">
          {(["metrics", "traces", "logs"] as const).map((k) => (
            <div key={k} className={`ev-bar ev-${k}`} style={{ flexGrow: share[k] || 0.0001 }}>
              {share[k] > 0 && (
                <span>
                  {k} · {Math.round(6000 * share[k]).toLocaleString("en")}
                </span>
              )}
            </div>
          ))}
        </div>
        <div className="ev-scale">
          <span>0</span>
          <span>6,000 tokens (cl100k_base)</span>
        </div>
        <h3>{c.what}</h3>
        <p>{c.detail}</p>
        <p className="ev-ids">
          Every line carries a stable ID (<code>{c.prefix}-0042</code>), and answers must cite the IDs
          they rely on, so cited evidence can be checked.
        </p>
      </div>
    </div>
  );
}
