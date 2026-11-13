import Link from "next/link";

import IncidentView from "@/components/IncidentView";
import { NO_INCIDENT, getGraph, getIncidents, getPack, getSite } from "@/lib/data";

export const dynamicParams = false;

export function generateStaticParams() {
  const ids = getIncidents().map((i) => ({ id: i.id }));
  return ids.length ? ids : [{ id: NO_INCIDENT }];
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return { title: `${id} · Rootline` };
}

export default async function IncidentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const site = getSite();
  const incident = getIncidents().find((i) => i.id === id);
  if (!incident) {
    return (
      <div className="wrap page">
        <h1>No incidents yet</h1>
        <div className="card empty">
          Snapshots appear here once they are published. <Link href="/">Back to results</Link>
        </div>
      </div>
    );
  }
  return (
    <div className="wrap page">
      <p>
        <Link href="/incidents/">← All incidents</Link>
      </p>
      <h1 className="mono">{id}</h1>
      <p className="lede">
        What each model saw and answered. The true root cause stays hidden until you reveal it.{" "}
        <span className="pill">{site.label}</span>
      </p>
      <IncidentView
        id={id}
        graph={getGraph(id)}
        initialPack={getPack(id, "combined", "p0")}
        label={site.labels_included ? (incident.label ?? null) : null}
        hasRuns={site.has_runs}
      />
    </div>
  );
}
