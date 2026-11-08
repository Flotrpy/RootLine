"use client";

import { Background, Controls, Position, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";

import type { Graph } from "@/lib/types";

/** Columns by call depth: callers on the left, callees to the right. */
function layout(graph: Graph): Record<string, { x: number; y: number }> {
  const incoming = new Map<string, number>(graph.nodes.map((n) => [n.id, 0]));
  for (const e of graph.edges) incoming.set(e.target, (incoming.get(e.target) ?? 0) + 1);
  const depth = new Map<string, number>();
  const queue = graph.nodes.filter((n) => !incoming.get(n.id)).map((n) => n.id);
  queue.forEach((id) => depth.set(id, 0));
  // Breadth-first; a cap on visits keeps a cyclic graph from looping.
  for (let i = 0; i < queue.length && i < 10_000; i++) {
    const id = queue[i];
    for (const e of graph.edges.filter((x) => x.source === id)) {
      const d = (depth.get(id) ?? 0) + 1;
      if (d > (depth.get(e.target) ?? -1)) {
        depth.set(e.target, d);
        queue.push(e.target);
      }
    }
  }
  const rows = new Map<number, number>();
  const pos: Record<string, { x: number; y: number }> = {};
  for (const n of [...graph.nodes].sort((a, b) => a.id.localeCompare(b.id))) {
    const d = depth.get(n.id) ?? 0;
    const r = rows.get(d) ?? 0;
    rows.set(d, r + 1);
    pos[n.id] = { x: d * 260, y: r * 90 };
  }
  return pos;
}

export default function ServiceGraph({ graph }: { graph: Graph }) {
  const { nodes, edges } = useMemo(() => {
    const pos = layout(graph);
    const nodes: Node[] = graph.nodes.map((n) => ({
      id: n.id,
      position: pos[n.id],
      // Left-to-right layout: connect on the sides, not top and bottom.
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      data: { label: `${n.id}\n${n.spans} spans${n.errors ? `, ${n.errors} errors` : ""}` },
      style: {
        whiteSpace: "pre-line",
        fontSize: 12,
        width: 170,
        borderColor: n.errors ? "var(--bad)" : "var(--line)",
        borderWidth: n.errors ? 2 : 1,
      },
    }));
    const edges: Edge[] = graph.edges.map((e) => ({
      id: `${e.source}->${e.target}`,
      source: e.source,
      target: e.target,
      label: e.errors ? `${e.errors}/${e.calls} err` : `${e.calls}`,
      animated: e.errors > 0,
      labelBgPadding: [4, 2],
      labelBgStyle: { fill: "var(--card)" },
      labelStyle: { fontSize: 11 },
      style: { stroke: e.errors ? "var(--bad)" : undefined },
    }));
    return { nodes, edges };
  }, [graph]);

  return (
    <div className="graph" aria-label="Service call graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.1 }}
        minZoom={0.2}
        nodesDraggable={false}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
