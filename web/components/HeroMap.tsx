"use client";

import { useState } from "react";

import { type MapMode, ServiceMap3D } from "./ServiceMap3D";

const MODES: { id: MapMode; label: string; note: string }[] = [
  {
    id: "network",
    label: "Network fault",
    note: "Requests from checkout to payment are lost on the way. Payment itself is fine.",
  },
  {
    id: "application",
    label: "App fault",
    note: "Every request reaches payment, and payment answers with errors.",
  },
  { id: "healthy", label: "Healthy", note: "No fault. The control a model must not raise an alarm on." },
];

// Same symptom at checkout, different root cause: this is RQ2.
export function HeroMap() {
  const [mode, setMode] = useState<MapMode>("network");
  const current = MODES.find((m) => m.id === mode)!;
  return (
    <>
      <ServiceMap3D mode={mode} />
      <div className="stage-ui">
        <div className="seg" role="radiogroup" aria-label="Show a fault on the service map">
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              role="radio"
              aria-checked={mode === m.id}
              onClick={() => setMode(m.id)}
            >
              {m.label}
            </button>
          ))}
        </div>
        <p className="stage-note" aria-live="polite">
          {current.note} <span className="hint">Drag to turn. Hover a service.</span>
        </p>
      </div>
    </>
  );
}
