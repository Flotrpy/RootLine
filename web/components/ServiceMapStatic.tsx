import { EDGES, FAULT_EDGE, NODES, position } from "@/lib/topology";

// Flat fallback of the service map (no WebGL, before JS, or for print).
export function ServiceMapStatic() {
  const W = 640;
  const H = 520;
  const pt = (id: string) => {
    const n = NODES.find((x) => x.id === id)!;
    const [x, y] = position(n);
    return [W / 2 + x * 92, H / 2 - y * 92 + 10] as const;
  };
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="100%" aria-hidden="true" preserveAspectRatio="xMidYMid meet">
      {EDGES.map((e) => {
        const [x1, y1] = pt(e.from);
        const [x2, y2] = pt(e.to);
        const hot = e.from === FAULT_EDGE.from && e.to === FAULT_EDGE.to;
        return (
          <line
            key={`${e.from}-${e.to}`}
            x1={x1}
            y1={y1}
            x2={x2}
            y2={y2}
            stroke={hot ? "var(--signal)" : "var(--rule-strong)"}
            strokeWidth={hot ? 2 : 1}
            strokeDasharray={e.kind === "flag" ? "3 4" : undefined}
          />
        );
      })}
      {NODES.map((n) => {
        const [x, y] = pt(n.id);
        const hot = n.id === FAULT_EDGE.to;
        return (
          <g key={n.id}>
            <rect x={x - 4} y={y - 4} width={8} height={8} fill={hot ? "var(--signal)" : "var(--node)"} />
            <text x={x} y={y + 18} textAnchor="middle" fontSize="10.5" fontFamily="var(--mono)" fill="var(--ink-2)">
              {n.id}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
