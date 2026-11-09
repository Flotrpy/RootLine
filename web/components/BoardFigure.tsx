"use client";

import { useState } from "react";

// A line drawing of the Arduino UNO Q (68.6 × 53.3 mm, the classic UNO
// footprint) with tappable parts. Positions are approximate: it explains
// the board's parts, it is not a replacement for a photo. When a photo of
// the actual board exists in public/photos, it can be shown instead.

type Part = { id: string; name: string; x: number; y: number; text: string };

const COMMON: Part[] = [
  { id: "mpu", name: "Linux processor", x: 300, y: 196, text: "Qualcomm Dragonwing QRB2210 running Debian Linux. Runs the board's side of Rootline." },
  { id: "mcu", name: "Microcontroller", x: 448, y: 126, text: "STM32U585 running Zephyr. Drives the buttons, LEDs and display of the optional demo panel." },
  { id: "radio", name: "Wi-Fi radio", x: 160, y: 104, text: "Wi-Fi 5 and Bluetooth module. Pinned to 2.4 GHz with power saving off, so faults land on one known band." },
  { id: "matrix", name: "LED matrix", x: 330, y: 300, text: "8 × 13 LED matrix on the board itself." },
  { id: "usb", name: "USB-C", x: 70, y: 200, text: "Power during the campaign comes from a phone charger; nothing is plugged into a computer." },
];

const ROLE: Record<"A" | "B", Part> = {
  A: { id: "role", name: "In Rootline", x: 470, y: 250, text: "edge-relay, a small Go program run by systemd, carries every checkout → payment request over the board's real Wi-Fi. Faults: transmit power dropped to 1 dBm, or the radio switched off for 30 s." },
  B: { id: "role", name: "In Rootline", x: 470, y: 250, text: "Sends 30 Mbit/s of UDP with iperf3 to the PC for 5 minutes, crowding the 2.4 GHz channel Board A depends on. Only ever to a private address on the home network." },
};

export function BoardFigure({ board, photo }: { board: "A" | "B"; photo?: string }) {
  const parts = [...COMMON, ROLE[board]];
  const [sel, setSel] = useState<string>("role");
  const [view, setView] = useState<"drawing" | "photo">(photo ? "photo" : "drawing");
  const part = parts.find((p) => p.id === sel)!;
  return (
    <figure>
      {photo && (
        <div className="seg small" role="radiogroup" aria-label={`Board ${board} view`}>
          {(["photo", "drawing"] as const).map((v) => (
            <button key={v} type="button" role="radio" aria-checked={view === v} onClick={() => setView(v)}>
              {v}
            </button>
          ))}
        </div>
      )}
      {view === "photo" && photo ? (
        <div className="plate photo">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={photo} alt={`Board ${board}, an Arduino UNO Q, as used in the campaign`} loading="lazy" />
        </div>
      ) : (
        <div className="plate">
          <svg viewBox="0 0 600 450" role="group" aria-label={`Drawing of Board ${board}, an Arduino UNO Q. Choose a part to read about it.`}>
            {/* Board outline with the UNO notch and mounting holes. */}
            <path
              d="M40 60 H520 L548 88 V380 L520 396 H40 Z"
              fill="none"
              stroke="var(--ink)"
              strokeWidth="1.5"
            />
            {[[66, 84], [512, 120], [512, 360], [100, 372]].map(([cx, cy]) => (
              <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r="9" fill="none" stroke="var(--ink)" strokeWidth="1" />
            ))}
            {/* Header rows, top and bottom. */}
            {Array.from({ length: 18 }, (_, i) => (
              <rect key={`t${i}`} x={168 + i * 18} y={70} width="10" height="10" fill="none" stroke="var(--rule-strong)" />
            ))}
            {Array.from({ length: 14 }, (_, i) => (
              <rect key={`b${i}`} x={204 + i * 18} y={374} width="10" height="10" fill="none" stroke="var(--rule-strong)" />
            ))}
            {/* USB-C */}
            <rect x="26" y="178" width="40" height="44" rx="8" fill="var(--paper)" stroke="var(--ink)" strokeWidth="1.5" />
            {/* Radio module with antenna trace. */}
            <rect x="100" y="96" width="120" height="70" fill="none" stroke="var(--ink)" strokeWidth="1" />
            <path d="M110 110 h20 v14 h20 v-14 h20 v14 h20 v-14 h20" fill="none" stroke="var(--rule-strong)" />
            {/* MPU, MCU, memory. */}
            <rect x="250" y="148" width="100" height="100" fill="none" stroke="var(--ink)" strokeWidth="1.5" />
            <rect x="264" y="162" width="72" height="72" fill="none" stroke="var(--rule-strong)" />
            <rect x="418" y="100" width="60" height="52" fill="none" stroke="var(--ink)" strokeWidth="1" />
            <rect x="370" y="160" width="40" height="70" fill="none" stroke="var(--rule-strong)" />
            {/* LED matrix 8 × 13 */}
            {Array.from({ length: 8 * 13 }, (_, i) => (
              <circle
                key={`m${i}`}
                cx={234 + (i % 13) * 15}
                cy={276 + Math.floor(i / 13) * 9}
                r="2.2"
                fill={board === "A" && (i % 13) * 2 + Math.floor(i / 13) * 3 < 7 ? "var(--signal)" : "var(--rule-strong)"}
              />
            ))}
            <text x="46" y="428" fontSize="13" fill="var(--muted)">
              Arduino UNO Q · 68.6 × 53.3 mm · drawing, positions approximate
            </text>
            {/* Hotspots */}
            {parts.map((p, i) => (
              <g
                key={p.id}
                className={`hot${sel === p.id ? " on" : ""}`}
                role="button"
                tabIndex={0}
                aria-pressed={sel === p.id}
                aria-label={p.name}
                onClick={() => setSel(p.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setSel(p.id);
                  }
                }}
              >
                <circle cx={p.x} cy={p.y} r="17" />
                <text x={p.x} y={p.y + 5} textAnchor="middle" fontSize="13">
                  {p.id === "role" ? board : i + 1}
                </text>
              </g>
            ))}
          </svg>
        </div>
      )}
      <figcaption>
        <span>{view === "photo" ? "Photo" : "Fig."} · Board {board}</span>
        <span>{view === "drawing" ? "Tap a numbered part" : ""}</span>
      </figcaption>
      {view === "drawing" && (
        <div className="part" aria-live="polite">
          <span className="eyebrow">{part.name}</span>
          <p>{part.text}</p>
        </div>
      )}
    </figure>
  );
}
