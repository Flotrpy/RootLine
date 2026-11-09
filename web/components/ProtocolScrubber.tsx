"use client";

import { useId, useState } from "react";

// One incident, minute by minute, from controller/internal/incident (Pilot
// protocol). Minutes count from the start of the baseline; T0 is fault onset.

const PHASES = [
  { from: 0, to: 5, name: "Baseline", text: "The shop runs normally under 20 simulated users. The controller samples health to compare against later." },
  { from: 5, to: 10, name: "Fault", text: "At T0 the fault is injected: a feature flag, a Toxiproxy toxic, a tc netem rule, or a command on an Arduino board." },
  { from: 10, to: 10.5, name: "Snapshot", text: "The snapshotter freezes ten minutes of spans, metrics and logs, from 5 minutes before T0 to 5 minutes after, into Parquet." },
  { from: 10.5, to: 13, name: "Clear and cool down", text: "The fault is removed and the system gets 3 minutes to settle." },
  { from: 13, to: 23, name: "Recovery check", text: "Health is sampled every 15 seconds until it matches the baseline again, for at most 10 minutes. Runs that never recover are flagged." },
];
const END = 23;

export function ProtocolScrubber() {
  const [t, setT] = useState(7);
  const id = useId();
  const phase = PHASES.find((p) => t >= p.from && t < p.to) ?? PHASES[PHASES.length - 1];
  const x = (m: number) => (m / END) * 100;
  const inWindow = t >= 0 && t <= 10;
  return (
    <div className="scrub">
      <div className="scrub-track" aria-hidden="true">
        <div className="scrub-window" style={{ left: `${x(0)}%`, width: `${x(10)}%` }}>
          <span>snapshot window, T0 ± 5 min</span>
        </div>
        {PHASES.map((p) => (
          <div
            key={p.name}
            className={`scrub-phase${p === phase ? " on" : ""}${p.name === "Fault" ? " fault" : ""}`}
            style={{ left: `${x(p.from)}%`, width: `${x(p.to - p.from)}%` }}
          />
        ))}
        <div className="scrub-t0" style={{ left: `${x(5)}%` }}>
          <span>T0</span>
        </div>
        <div className="scrub-head" style={{ left: `${x(t)}%` }} />
      </div>
      <label htmlFor={id} className="sr-only">
        Minute of the incident
      </label>
      <input
        id={id}
        type="range"
        min={0}
        max={END}
        step={0.25}
        value={t}
        onChange={(e) => setT(Number(e.target.value))}
        aria-valuetext={`minute ${t.toFixed(1)}, ${phase.name}`}
      />
      <div className="scrub-ticks" aria-hidden="true">
        {[0, 5, 10, 13, 23].map((m) => (
          <span key={m} style={{ left: `${x(m)}%` }}>
            {m === 5 ? "T0" : `${m}′`}
          </span>
        ))}
      </div>
      <div className="scrub-read" aria-live="polite">
        <div className="scrub-clock">
          <span className="mono">
            {t < 5 ? `T0 − ${(5 - t).toFixed(1)}` : `T0 + ${(t - 5).toFixed(1)}`} min
          </span>
          <span className={`pill${phase.name === "Fault" ? " bad" : " quiet"}`}>{phase.name}</span>
          {inWindow && <span className="pill">in snapshot</span>}
        </div>
        <p>{phase.text}</p>
      </div>
      <p className="scrub-foot">
        The first incident of a night adds a 10-minute warm-up. One incident takes 13 to 23 minutes, depending on how fast health recovers;
        the 30 pilot snapshots run unattended in one night.
      </p>
    </div>
  );
}
