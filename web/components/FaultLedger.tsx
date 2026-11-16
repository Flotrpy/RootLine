"use client";

import { Fragment, useState } from "react";

// The 15 pilot incident types, as defined in controller/internal/catalog.
type Layer = "application" | "network" | "none";
type Fault = { name: string; where: string; category: string; layer: Layer; how: string };

const FAULTS: Fault[] = [
  { name: "paymentFailure", where: "payment", category: "error", layer: "application", how: "flagd flag paymentFailure, variant 50%: half of all charges fail." },
  { name: "paymentUnreachable", where: "checkout → payment", category: "dependency unavailable", layer: "application", how: "flagd flag paymentUnreachable: checkout calls a payment address that does not answer." },
  { name: "productCatalogFailure", where: "product-catalog", category: "error", layer: "application", how: "flagd flag productCatalogFailure: lookups of one product return an error." },
  { name: "productCatalogLockContention", where: "product-catalog", category: "lock contention", layer: "application", how: "flagd flag productCatalogLockContention: queries wait on an exclusive table lock." },
  { name: "emailMemoryLeak", where: "email", category: "memory leak", layer: "application", how: "flagd flag emailMemoryLeak, variant 100x: the email service keeps memory it should free." },
  { name: "recommendationCacheFailure", where: "recommendation", category: "memory leak", layer: "application", how: "flagd flag recommendationCacheFailure: the cache grows without bound." },
  { name: "kafkaQueueProblems", where: "fraud-detection", category: "queue lag", layer: "application", how: "flagd flag kafkaQueueProblems: the queue floods and consumers fall behind." },
  { name: "intlShippingSlowdown", where: "shipping", category: "latency", layer: "application", how: "flagd flag intlShippingSlowdown, variant 5sec: non-US shipping quotes take 5 seconds." },
  { name: "imageSlowLoad", where: "frontend-proxy", category: "latency", layer: "application", how: "flagd flag imageSlowLoad, variant 5sec: product images are delayed at the proxy." },
  { name: "adHighCpu", where: "ad", category: "CPU saturation", layer: "application", how: "flagd flag adHighCpu: the ad service burns CPU on every request." },
  { name: "toxiLatency", where: "checkout → payment", category: "network latency", layer: "network", how: "Toxiproxy latency toxic: 300 ms ± 60 ms added to every packet on the link." },
  { name: "netemLoss", where: "frontend → product-catalog", category: "network loss", layer: "network", how: "tc netem on the link's proxy container: 5% of packets dropped." },
  { name: "toxiReset", where: "checkout → payment", category: "network reset", layer: "network", how: "Toxiproxy reset_peer toxic: 20% of connections are cut." },
  { name: "toxiBandwidth", where: "frontend → product-catalog", category: "network throughput", layer: "network", how: "Toxiproxy bandwidth toxic: the link is limited to 64 KB/s." },
  { name: "healthy", where: "–", category: "none", layer: "none", how: "Nothing is injected. A model that names a root cause here raises a false alarm." },
];

const FILTERS: { id: Layer | "all"; label: string }[] = [
  { id: "all", label: "All 15" },
  { id: "application", label: "Application · 10" },
  { id: "network", label: "Network · 4" },
  { id: "none", label: "Control · 1" },
];

export function FaultLedger() {
  const [filter, setFilter] = useState<Layer | "all">("all");
  const [open, setOpen] = useState<string | null>("toxiReset");
  const rows = FAULTS.map((f, i) => ({ ...f, n: i + 1 })).filter((f) => filter === "all" || f.layer === filter);
  return (
    <div>
      <div className="seg" role="radiogroup" aria-label="Filter incident types by layer">
        {FILTERS.map((f) => (
          <button key={f.id} type="button" role="radio" aria-checked={filter === f.id} onClick={() => setFilter(f.id)}>
            {f.label}
          </button>
        ))}
      </div>
      <table className="ledger">
        <caption className="sr-only">The 15 incident types of the pilot</caption>
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Incident</th>
            <th scope="col">Root cause</th>
            <th scope="col" className="hide-sm">Category</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((f) => {
            const isOpen = open === f.name;
            return (
              <Fragment key={f.name}>
                <tr className={`row${isOpen ? " open" : ""}`}>
                  <td>{String(f.n).padStart(2, "0")}</td>
                  <td>
                    <button
                      type="button"
                      className="row-btn"
                      aria-expanded={isOpen}
                      aria-controls={`how-${f.name}`}
                      onClick={() => setOpen(isOpen ? null : f.name)}
                    >
                      <span className="mono">{f.name}</span>
                      <span className="chev" aria-hidden="true">{isOpen ? "−" : "+"}</span>
                    </button>
                  </td>
                  <td className={f.layer === "network" ? "tag net" : "tag"}>{f.where}</td>
                  <td className="hide-sm">{f.category}</td>
                </tr>
                {isOpen && (
                  <tr className="how" id={`how-${f.name}`}>
                    <td />
                    <td colSpan={3}>
                      <span className="eyebrow">{f.layer === "none" ? "control" : `${f.layer} layer`} · how it is injected</span>
                      <p>{f.how}</p>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
