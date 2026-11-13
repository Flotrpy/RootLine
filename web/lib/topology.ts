// The OpenTelemetry Demo's main request paths (simplified: databases other
// than the cart cache and the flagd sidecars are left out). Used for the
// home page's service map; the incident pages draw each snapshot's real
// graph instead.

export type Node = { id: string; layer: number; slot: number; of: number; up?: number };
export type Edge = { from: string; to: string; kind?: "flag" };

const layers: string[][] = [
  ["load-generator"],
  ["frontend-proxy"],
  ["frontend", "image-provider"],
  ["ad", "cart", "checkout", "currency", "product-catalog", "recommendation", "shipping"],
  ["valkey-cart", "payment", "email", "kafka", "quote"],
  ["accounting", "fraud-detection"],
];

export const NODES: Node[] = [
  ...layers.flatMap((ids, layer) => ids.map((id, slot) => ({ id, layer, slot, of: ids.length }))),
  { id: "flagd", layer: 3, slot: 3, of: 7, up: 1 },
];

export const EDGES: Edge[] = [
  { from: "load-generator", to: "frontend-proxy" },
  { from: "frontend-proxy", to: "frontend" },
  { from: "frontend-proxy", to: "image-provider" },
  ...["ad", "cart", "checkout", "currency", "product-catalog", "recommendation", "shipping"].map(
    (to) => ({ from: "frontend", to }),
  ),
  ...["cart", "currency", "email", "payment", "product-catalog", "shipping", "kafka"].map((to) => ({
    from: "checkout",
    to,
  })),
  { from: "cart", to: "valkey-cart" },
  { from: "shipping", to: "quote" },
  { from: "recommendation", to: "product-catalog" },
  { from: "kafka", to: "accounting" },
  { from: "kafka", to: "fraud-detection" },
  ...["payment", "product-catalog", "recommendation", "ad", "email", "shipping"].map((to) => ({
    from: "flagd",
    to,
    kind: "flag" as const,
  })),
];

// The edge the hardware arm routes over real Wi-Fi, and where the pilot's
// network faults land most often.
export const FAULT_EDGE = { from: "checkout", to: "payment" };

/** Deterministic 3D position: layers run left to right, each layer fans out in depth. */
export function position(n: Node): [number, number, number] {
  const x = (n.layer - 2.5) * 1.18;
  if (n.up) return [x, 1.55, -0.2];
  const t = n.of === 1 ? 0 : n.slot / (n.of - 1) - 0.5; // -0.5 .. 0.5
  const y = -t * Math.min(2.6, 0.55 * n.of);
  const z = Math.sin((n.slot + n.layer) * 1.7) * 0.55;
  return [x, y, z];
}
