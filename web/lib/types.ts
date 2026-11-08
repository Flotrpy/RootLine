// Shapes of the files `python -m analysis site-data` writes.

export type Site = {
  labels_included: boolean;
  n_snapshots: number;
  has_runs: boolean;
  best_model: string | null;
  label: string;
  models?: string[];
};

export type Label = {
  fault: string;
  service: string;
  category: string;
  layer: string;
  edge: string | null;
};

export type Incident = { id: string; label?: Label };

export type SummaryRow = {
  model_id: string;
  tier: string;
  condition: string;
  perturbation: string;
  n: number;
  top1: number | null;
  top1_ci_low: number | null;
  top1_ci_high: number | null;
  top3: number | null;
  layer_acc: number | null;
  evidence_validity: number | null;
  invalid_output_rate: number | null;
  healthy_false_alarm_rate: number | null;
  brier: number | null;
  ece: number | null;
  prompt_tokens: number;
  completion_tokens: number;
};

export type HypothesisRow = {
  rq: string;
  statement: string;
  status: string;
  n: number;
  effect: number | null;
  threshold_met: boolean | null;
  test: string;
  p_value: number | null;
  p_holm: number | null;
  significant: boolean | null;
  detail: string;
};

export type GraphNode = { id: string; spans: number; errors: number };
export type GraphEdge = { source: string; target: string; calls: number; errors: number };
export type Graph = { nodes: GraphNode[]; edges: GraphEdge[] };

export type EvidenceLine = { id: string; services: string[]; text: string };
export type Section = { signal: string; header: string; lines: EvidenceLine[]; omitted: number };
export type PackFile = {
  prompt_tokens: number;
  pack: { incident_id: string; condition: string; perturbation: string; sections: Section[] };
};

export type RunRow = {
  model_id: string;
  tier: string;
  condition: string;
  perturbation: string;
  raw_output: string;
  parsed_ok: boolean;
  top1: boolean;
  layer_ok: boolean;
  confidence: number;
};

export type ModelAnswer = {
  abstain: boolean;
  layer: string;
  hypotheses: {
    rank: number;
    service: string;
    category: string;
    confidence: number;
    evidence: string[];
  }[];
  action: { type: string; target: string | null };
};

export const CONDITIONS = ["metrics", "traces", "logs", "combined"] as const;
export const PERTURBATIONS = ["p0", "p1"] as const;
