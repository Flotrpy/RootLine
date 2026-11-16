import Link from "next/link";

import { getIncidents, getSite } from "@/lib/data";

export const metadata = { title: "Incidents · Rootline" };

export default function Incidents() {
  const site = getSite();
  const incidents = getIncidents();
  return (
    <div className="wrap page">
      <h1>Incidents</h1>
      <p className="lede">
        Each snapshot is ten minutes of telemetry around one injected fault, or a healthy control.{" "}
        <span className="pill">{site.label}</span>
      </p>
      {incidents.length === 0 ? (
        <div className="card empty">No snapshots published yet.</div>
      ) : (
        <div className="grid">
          {incidents.map((i) => (
            <Link key={i.id} href={`/incidents/${i.id}/`} className="card mono">
              {i.id}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
