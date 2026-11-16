// Build-time data access. Pages read web/public/data with fs during the
// static export, so the HTML ships with its numbers and needs no fetch.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import type { Graph, HypothesisRow, Incident, PackFile, Site, SummaryRow } from "./types";

const DATA = join(process.cwd(), "public", "data");

function read<T>(rel: string): T | null {
  const p = join(DATA, rel);
  return existsSync(p) ? (JSON.parse(readFileSync(p, "utf8")) as T) : null;
}

export const EMPTY_SITE: Site = {
  labels_included: false,
  n_snapshots: 0,
  has_runs: false,
  best_model: null,
  label: "pilot (no data yet)",
};

export const getSite = (): Site => read<Site>("site.json") ?? EMPTY_SITE;
export const getSummary = (): SummaryRow[] => read<SummaryRow[]>("summary.json") ?? [];
export const getHypotheses = (): HypothesisRow[] =>
  read<HypothesisRow[]>("hypotheses.json") ?? [];
export const getIncidents = (): Incident[] => read<Incident[]>("incidents.json") ?? [];
export const getGraph = (id: string): Graph | null => read<Graph>(`incidents/${id}/graph.json`);
export const getPack = (id: string, condition: string, perturbation: string): PackFile | null =>
  read<PackFile>(`incidents/${id}/${condition}-${perturbation}.json`);

// Static export needs at least one path per dynamic route; "none" renders
// the empty state when there are no snapshots yet.
export const NO_INCIDENT = "none";

// A photo in web/public/photos/<name>.(jpg|jpeg|png|webp), if one was added.
export function photo(name: string): string | undefined {
  for (const ext of ["jpg", "jpeg", "png", "webp"]) {
    if (existsSync(join(process.cwd(), "public", "photos", `${name}.${ext}`))) {
      return `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/photos/${name}.${ext}`;
    }
  }
  return undefined;
}
