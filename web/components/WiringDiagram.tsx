"use client";

import { useState } from "react";

// How the hardware arm is wired, and what each of its three faults does.
// From docs/HARDWARE.md and compose.hardware.yml.

type HwFault = "none" | "weak" | "contention" | "outage";

const FAULTS: { id: HwFault; label: string; text: string }[] = [
  { id: "none", label: "No fault", text: "checkout calls payment through Board A over the home Wi-Fi. Board B is idle." },
  { id: "weak", label: "Weak signal", text: "Board A's transmit power drops from about 20 dBm to 1 dBm. Its uplink gets lossy; the board puts power back by itself after 8 minutes at the latest." },
  { id: "contention", label: "Contention", text: "Board B sends 30 Mbit/s of UDP to the PC for 5 minutes on the same 2.4 GHz channel, so Board A's requests wait for airtime." },
  { id: "outage", label: "Wi-Fi outage", text: "Board A's radio switches off for 30 seconds. Every request through it fails until the link comes back." },
];

export function WiringDiagram() {
  const [f, setF] = useState<HwFault>("weak");
  const cur = FAULTS.find((x) => x.id === f)!;
  const linkA = f === "outage" ? "cut" : f === "weak" ? "weak" : "ok";
  return (
    <div className={`wire wire-${f}`}>
      <div className="seg" role="radiogroup" aria-label="Show a hardware fault">
        {FAULTS.map((x) => (
          <button key={x.id} type="button" role="radio" aria-checked={f === x.id} onClick={() => setF(x.id)}>
            {x.label}
          </button>
        ))}
      </div>
      <div className="plate">
        <svg viewBox="0 0 900 360" role="img" aria-label={`Wiring of the hardware arm. ${cur.text}`}>
          <defs>
            <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0 0 L10 5 L0 10 z" fill="var(--node)" />
            </marker>
            <marker id="arr-s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0 0 L10 5 L0 10 z" fill="var(--signal)" />
            </marker>
          </defs>

          {/* PC */}
          <rect x="20" y="40" width="300" height="280" fill="none" stroke="var(--node)" strokeWidth="1.5" />
          <text x="36" y="66" fontSize="13" fill="var(--ink)">PC · WSL · Docker</text>
          {[
            ["checkout", 92],
            ["payment", 162],
            ["snapshotter", 232],
          ].map(([n, y]) => (
            <g key={n as string}>
              <rect x="40" y={y as number} width="150" height="44" fill="var(--paper)" stroke="var(--node)" />
              <text x="56" y={(y as number) + 27} fontSize="13" fill="var(--ink)">{n}</text>
            </g>
          ))}
          <rect x="210" y="232" width="96" height="44" fill="var(--paper)" stroke={f === "contention" ? "var(--signal)" : "var(--node)"} strokeWidth={f === "contention" ? 2.5 : 1} />
          <text x="222" y="259" fontSize="12" fill={f === "contention" ? "var(--signal)" : "var(--ink)"}>iperf3 srv</text>

          {/* Router */}
          <rect x="400" y="150" width="120" height="60" fill="none" stroke="var(--node)" />
          <text x="414" y="176" fontSize="12" fill="var(--ink)">Wi-Fi router</text>
          <text x="414" y="196" fontSize="11" fill="var(--muted)">2.4 GHz · ch 6</text>
          <line x1="320" y1="180" x2="400" y2="180" stroke="var(--rule-strong)" strokeWidth="1" />

          {/* Board A */}
          <rect x="640" y="60" width="220" height="90" fill="none" stroke={f === "none" || f === "contention" ? "var(--node)" : "var(--signal)"} strokeWidth={f === "none" || f === "contention" ? 1.5 : 2.5} />
          <text x="656" y="88" fontSize="13" fill="var(--ink)">Board A · affan1</text>
          <text x="656" y="110" fontSize="11" fill="var(--muted)">edge-relay :50051</text>
          <text x="656" y="130" fontSize="11" fill={f === "weak" ? "var(--signal)" : "var(--muted)"}>
            tx power {f === "weak" ? "1 dBm" : "≈20 dBm"}
          </text>
          {/* Radio waves around Board A */}
          {f !== "outage" &&
            [16, 28, 40].map((r, i) => (
              <path
                key={r}
                className="wave"
                style={{ animationDelay: `${i * 0.3}s` }}
                d={`M${640 - 6} ${105 - r} a${r} ${r} 0 0 0 0 ${r * 2}`}
                fill="none"
                stroke={f === "weak" ? "var(--signal)" : "var(--rule-strong)"}
                strokeWidth="1"
                opacity={f === "weak" && i > 0 ? 0.15 : 1}
              />
            ))}

          {/* Board B */}
          <rect x="640" y="230" width="220" height="90" fill="none" stroke={f === "contention" ? "var(--signal)" : "var(--node)"} strokeWidth={f === "contention" ? 2.5 : 1.5} />
          <text x="656" y="258" fontSize="13" fill="var(--ink)">Board B · affan2</text>
          <text x="656" y="280" fontSize="11" fill={f === "contention" ? "var(--signal)" : "var(--muted)"}>
            iperf3 {f === "contention" ? "30 Mbit/s UDP, 5 min" : "idle"}
          </text>

          {/* checkout -> Board A -> payment */}
          <path
            className={`flow ${linkA}`}
            d="M190 114 C 300 114, 360 160, 400 168 M520 168 C 580 150, 600 110, 640 100"
            fill="none"
            stroke={linkA === "ok" ? "var(--node)" : "var(--signal)"}
            strokeWidth={linkA === "ok" ? 1.5 : 2.5}
            strokeDasharray={linkA === "weak" ? "4 6" : linkA === "cut" ? "2 10" : "6 6"}
            markerEnd={linkA === "ok" ? "url(#arr)" : "url(#arr-s)"}
          />
          <path
            className={`flow ${linkA}`}
            d="M640 130 C 600 170, 560 190, 520 192 M400 192 C 330 200, 260 186, 190 184"
            fill="none"
            stroke={linkA === "ok" ? "var(--node)" : "var(--signal)"}
            strokeWidth={linkA === "ok" ? 1.5 : 2.5}
            strokeDasharray={linkA === "weak" ? "4 6" : linkA === "cut" ? "2 10" : "6 6"}
            markerEnd={linkA === "ok" ? "url(#arr)" : "url(#arr-s)"}
          />
          {f === "outage" && (
            <g stroke="var(--signal)" strokeWidth="2.5">
              <line x1="578" y1="118" x2="598" y2="138" />
              <line x1="598" y1="118" x2="578" y2="138" />
            </g>
          )}
          <text x="200" y="104" fontSize="11" fill="var(--muted)">checkout → payment</text>

          {/* Contention flood */}
          {f === "contention" && (
            <path
              className="flow flood"
              d="M640 280 C 560 290, 520 230, 470 214 M400 210 C 360 240, 340 254, 306 254"
              fill="none"
              stroke="var(--signal)"
              strokeWidth="3"
              strokeDasharray="2 5"
              markerEnd="url(#arr-s)"
            />
          )}
        </svg>
      </div>
      <p className="wire-note" aria-live="polite">
        <span className="eyebrow">{cur.label}</span> {cur.text}
      </p>
    </div>
  );
}
