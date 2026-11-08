"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { asset, pct } from "@/lib/format";
import {
  CONDITIONS,
  PERTURBATIONS,
  type Graph,
  type Label,
  type ModelAnswer,
  type PackFile,
  type RunRow,
} from "@/lib/types";

// React Flow is client-only and heavy; load it after the page paints.
const ServiceGraph = dynamic(() => import("./ServiceGraph"), { ssr: false });

function parse(raw: string): ModelAnswer | null {
  try {
    const text = raw.trim().replace(/^```(?:json)?\n([\s\S]*)\n```$/, "$1");
    return JSON.parse(text) as ModelAnswer;
  } catch {
    return null;
  }
}

type Props = {
  id: string;
  graph: Graph | null;
  initialPack: PackFile | null;
  label: Label | null;
  hasRuns: boolean;
};

export default function IncidentView({ id, graph, initialPack, label, hasRuns }: Props) {
  const [condition, setCondition] = useState<string>("combined");
  const [perturbation, setPerturbation] = useState<string>("p0");
  const [pack, setPack] = useState<PackFile | null>(initialPack);
  const [runs, setRuns] = useState<RunRow[] | null>(null);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    if (condition === "combined" && perturbation === "p0") {
      setPack(initialPack);
      return;
    }
    let live = true;
    fetch(asset(`/data/incidents/${id}/${condition}-${perturbation}.json`))
      .then((r) => (r.ok ? r.json() : null))
      .then((p: PackFile | null) => live && setPack(p))
      .catch(() => live && setPack(null));
    return () => {
      live = false;
    };
  }, [id, condition, perturbation, initialPack]);

  useEffect(() => {
    if (!hasRuns) return;
    let live = true;
    setRuns(null);
    import("@/lib/duckdb")
      .then(({ runsFor }) => runsFor(id, condition, perturbation))
      .then((r) => {
        if (!live) return;
        setRuns(r);
        setSelected(r[0]?.model_id ?? null);
      })
      .catch((e: unknown) => live && setRunsError(String(e)));
    return () => {
      live = false;
    };
  }, [id, condition, perturbation, hasRuns]);

  const answers = useMemo(
    () => (runs ?? []).map((r) => ({ run: r, answer: r.parsed_ok ? parse(r.raw_output) : null })),
    [runs],
  );
  const cited = useMemo(() => {
    const a = answers.find((x) => x.run.model_id === selected)?.answer;
    return new Set(a?.hypotheses.flatMap((h) => h.evidence) ?? []);
  }, [answers, selected]);

  return (
    <>
      {graph && graph.nodes.length > 0 && (
        <>
          <h2>Service graph during the window</h2>
          <ServiceGraph graph={graph} />
        </>
      )}

      <h2>Evidence and answers</h2>
      <div className="controls" role="group" aria-label="Evidence condition">
        {CONDITIONS.map((c) => (
          <button key={c} aria-pressed={condition === c} onClick={() => setCondition(c)}>
            {c}
          </button>
        ))}
        {PERTURBATIONS.map((p) => (
          <button key={p} aria-pressed={perturbation === p} onClick={() => setPerturbation(p)}>
            {p === "p0" ? "real names" : "anonymised (P1)"}
          </button>
        ))}
      </div>

      <div className="incident-cols">
        <div className="card pack">
          {!pack ? (
            <p>No evidence pack for this condition.</p>
          ) : (
            <>
              <div style={{ color: "var(--muted)" }}>{pack.prompt_tokens} prompt tokens</div>
              {pack.pack.sections.map((s) => (
                <section key={s.signal}>
                  <h3>
                    {s.signal}: {s.header}
                  </h3>
                  {s.lines.map((l) => (
                    <div key={l.id} className={`ln${cited.has(l.id) ? " cited" : ""}`}>
                      <span className="id">{l.id}</span>
                      {l.text}
                    </div>
                  ))}
                  {s.omitted > 0 && <div className="omitted">{s.omitted} lower-ranked lines omitted</div>}
                </section>
              ))}
            </>
          )}
        </div>

        <div className="answers">
          {!hasRuns && <div className="card empty">No model runs yet.</div>}
          {hasRuns && runs === null && !runsError && <div className="card">Loading runs in your browser…</div>}
          {runsError && <div className="card empty">Could not load runs: {runsError}</div>}
          {answers.map(({ run, answer }) => (
            <div
              key={run.model_id}
              className="card answer"
              onClick={() => setSelected(run.model_id)}
              style={{ cursor: "pointer", outline: selected === run.model_id ? "2px solid var(--accent)" : undefined }}
            >
              <h4>
                <span className="mono">{run.model_id}</span> <span className="pill quiet">tier {run.tier}</span>{" "}
                {revealed && <span className={`pill${run.top1 ? "" : " bad"}`}>{run.top1 ? "correct" : "wrong"}</span>}
              </h4>
              {!answer ? (
                <div>Invalid output (scored as an abstention).</div>
              ) : (
                <>
                  <div>
                    Layer: <strong>{answer.layer}</strong>
                    {answer.abstain && " (abstained)"} · Action:{" "}
                    <span className="mono">
                      {answer.action.type}
                      {answer.action.target ? `(${answer.action.target})` : ""}
                    </span>
                  </div>
                  <ol>
                    {answer.hypotheses
                      .slice()
                      .sort((a, b) => a.rank - b.rank)
                      .map((h) => (
                        <li key={h.rank}>
                          {h.service} / {h.category} · {pct(h.confidence)}
                          {h.evidence.length > 0 && <span className="mono"> [{h.evidence.join(", ")}]</span>}
                        </li>
                      ))}
                  </ol>
                </>
              )}
            </div>
          ))}
          {answers.length > 0 && <p style={{ color: "var(--muted)" }}>Select a model to highlight the evidence it cited.</p>}

          {label && (
            <div className="reveal">
              {revealed ? (
                <div className="card">
                  <strong>Root cause:</strong> {label.service} / {label.category} ({label.layer} layer)
                  {label.edge && <> on edge <span className="mono">{label.edge}</span></>}
                </div>
              ) : (
                <button onClick={() => setRevealed(true)}>Reveal the root cause</button>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
