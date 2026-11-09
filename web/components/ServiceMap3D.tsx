"use client";

import { useEffect, useRef, useState } from "react";

import { EDGES, FAULT_EDGE, NODES, position } from "@/lib/topology";

import { ServiceMapStatic } from "./ServiceMapStatic";

// The home page's service map in 3D. Requests move along every edge of the
// OpenTelemetry Demo. In "network" mode some requests on checkout -> payment
// are lost on the wire; in "application" mode payment itself answers with
// errors; "healthy" is the control. Drag to turn it, hover a service to see
// its calls. Static SVG first; WebGL takes over only when available, and
// motion stops under prefers-reduced-motion or while off screen.

export type MapMode = "network" | "application" | "healthy";

const isFaultEdge = (a: string, b: string) => a === FAULT_EDGE.from && b === FAULT_EDGE.to;

function cssColor(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

type Hover = { id: string; calls: number; calledBy: number } | null;

export function ServiceMap3D({ mode }: { mode: MapMode }) {
  const host = useRef<HTMLDivElement>(null);
  const labels = useRef<HTMLDivElement>(null);
  const modeRef = useRef<MapMode>(mode);
  const applyMode = useRef<() => void>(() => {});
  const [live, setLive] = useState(false);
  const [hover, setHover] = useState<Hover>(null);

  useEffect(() => {
    modeRef.current = mode;
    applyMode.current();
  }, [mode]);

  useEffect(() => {
    const el = host.current;
    const labelHost = labels.current;
    if (!el || !labelHost) return;
    const probe = document.createElement("canvas");
    if (!(probe.getContext("webgl2") || probe.getContext("webgl"))) return;

    let disposed = false;
    let cleanup = () => {};

    void import("three").then((THREE) => {
      if (disposed) return;
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      el.appendChild(renderer.domElement);
      renderer.domElement.setAttribute("aria-hidden", "true");

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100);
      camera.position.set(0, 0.25, 9.2);
      const world = new THREE.Group();
      scene.add(world);

      const pos = new Map(NODES.map((n) => [n.id, new THREE.Vector3(...position(n))]));

      const mat = {
        node: new THREE.MeshBasicMaterial(),
        hot: new THREE.MeshBasicMaterial(),
        edge: new THREE.LineBasicMaterial({ transparent: true, opacity: 0.85 }),
        flag: new THREE.LineDashedMaterial({ dashSize: 0.06, gapSize: 0.08, transparent: true, opacity: 0.6 }),
        fault: new THREE.LineBasicMaterial(),
        focus: new THREE.LineBasicMaterial(),
        packet: new THREE.PointsMaterial({ size: 0.055, sizeAttenuation: true, transparent: true, opacity: 0.9 }),
        bad: new THREE.PointsMaterial({ size: 0.075, sizeAttenuation: true, transparent: true }),
        ring: new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.5, side: THREE.DoubleSide }),
      };
      const paint = () => {
        // One fixed black-and-white theme: grey structure, the fault in white.
        const signal = new THREE.Color(cssColor("--signal"));
        mat.node.color = new THREE.Color(cssColor("--node"));
        mat.hot.color = signal;
        mat.edge.color = new THREE.Color(cssColor("--rule-strong"));
        mat.flag.color = new THREE.Color(cssColor("--rule-strong"));
        mat.fault.color = signal;
        mat.focus.color = new THREE.Color(cssColor("--ink-2"));
        mat.packet.color = new THREE.Color(cssColor("--muted"));
        mat.bad.color = signal;
        mat.ring.color = signal;
      };
      paint();

      const box = new THREE.BoxGeometry(0.11, 0.11, 0.11);
      const target = new THREE.Mesh(box, mat.node);
      for (const n of NODES) {
        const m = n.id === FAULT_EDGE.to ? target : new THREE.Mesh(box, mat.node);
        m.position.copy(pos.get(n.id)!);
        world.add(m);
      }
      const ring = new THREE.Mesh(new THREE.RingGeometry(0.15, 0.165, 48), mat.ring);
      world.add(ring);

      const lineGeo = (pick: (e: (typeof EDGES)[number]) => boolean) => {
        const pts: number[] = [];
        for (const e of EDGES) if (pick(e)) pts.push(...pos.get(e.from)!.toArray(), ...pos.get(e.to)!.toArray());
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
        return g;
      };
      world.add(new THREE.LineSegments(lineGeo((e) => e.kind !== "flag" && !isFaultEdge(e.from, e.to)), mat.edge));
      const flagLines = new THREE.LineSegments(lineGeo((e) => e.kind === "flag"), mat.flag);
      flagLines.computeLineDistances();
      world.add(flagLines);
      const faultLine = new THREE.LineSegments(lineGeo((e) => isFaultEdge(e.from, e.to)), mat.fault);
      world.add(faultLine);
      const focusLines = new THREE.LineSegments(new THREE.BufferGeometry(), mat.focus);
      world.add(focusLines);

      const mid = new THREE.Vector3().lerpVectors(pos.get(FAULT_EDGE.from)!, pos.get(FAULT_EDGE.to)!, 0.5);
      applyMode.current = () => {
        const m = modeRef.current;
        faultLine.material = m === "network" ? mat.fault : mat.edge;
        target.material = m === "application" ? mat.hot : mat.node;
        ring.visible = m !== "healthy";
        ring.position.copy(m === "network" ? mid : pos.get(FAULT_EDGE.to)!);
        spans.forEach(({ s, id }) => {
          const hot = (m === "network" && (id === FAULT_EDGE.from || id === FAULT_EDGE.to)) || (m === "application" && id === FAULT_EDGE.to);
          s.classList.toggle("hot", hot);
        });
        draw();
      };

      // Packets: a few per request edge, caller to callee.
      const flows = EDGES.filter((e) => e.kind !== "flag");
      const PER = 3;
      const packets = flows.flatMap((e, i) =>
        Array.from({ length: PER }, (_, k) => ({
          a: pos.get(e.from)!,
          b: pos.get(e.to)!,
          onFault: isFaultEdge(e.from, e.to),
          t: (k / PER + i * 0.137) % 1,
          speed: 0.16 + ((i * 7 + k * 3) % 5) * 0.025,
          bad: false,
        })),
      );
      const mkPoints = (m: InstanceType<typeof THREE.PointsMaterial>) => {
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(packets.length * 3), 3));
        world.add(new THREE.Points(g, m));
        return g;
      };
      const okGeo = mkPoints(mat.packet);
      const badGeo = mkPoints(mat.bad);
      const tmp = new THREE.Vector3();
      const OFF = [0, 0, -999];

      const spans = NODES.map((n) => {
        const s = document.createElement("span");
        s.className = "stage-label";
        s.textContent = n.id;
        labelHost.appendChild(s);
        return { s, id: n.id, p: pos.get(n.id)!, x: 0, y: 0 };
      });

      let w = 0;
      let h = 0;
      const resize = () => {
        w = el.clientWidth;
        h = el.clientHeight;
        if (!w || !h) return;
        renderer.setSize(w, h, false);
        camera.aspect = w / h;
        // Fit the map and its labels in frame.
        const fit = w / h < 1.1 ? 8.8 : 6.3; // labels need more room on narrow screens
        camera.position.z = Math.max(8.2, fit / (2 * Math.tan((16 * Math.PI) / 180) * (w / h)));
        camera.updateProjectionMatrix();
        draw();
      };

      // Pointer: parallax, drag to turn, hover to focus a service.
      let px = 0;
      let py = 0;
      let yaw = 0;
      let drag: { x: number; yaw: number } | null = null;
      let focused: string | null = null;
      const setFocus = (id: string | null) => {
        if (id === focused) return;
        focused = id;
        const pts: number[] = [];
        if (id) {
          for (const e of EDGES) {
            if (e.from === id || e.to === id) pts.push(...pos.get(e.from)!.toArray(), ...pos.get(e.to)!.toArray());
          }
        }
        focusLines.geometry.dispose();
        focusLines.geometry = new THREE.BufferGeometry();
        focusLines.geometry.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
        spans.forEach(({ s, id: sid }) => s.classList.toggle("focus", sid === id));
        setHover(
          id
            ? {
                id,
                calls: EDGES.filter((e) => e.from === id && e.kind !== "flag").length,
                calledBy: EDGES.filter((e) => e.to === id && e.kind !== "flag").length,
              }
            : null,
        );
        draw();
      };
      const onMove = (ev: PointerEvent) => {
        const r = el.getBoundingClientRect();
        const lx = ev.clientX - r.left;
        const ly = ev.clientY - r.top;
        const clamp = (v: number) => Math.max(-1, Math.min(1, v));
        px = clamp((lx / r.width - 0.5) * 2);
        py = clamp((ly / r.height - 0.5) * 2);
        if (drag) {
          yaw = Math.max(-0.9, Math.min(0.9, drag.yaw + ((ev.clientX - drag.x) / r.width) * 3));
          draw();
          return;
        }
        const inside = lx >= 0 && ly >= 0 && lx <= r.width && ly <= r.height;
        let best: string | null = null;
        let bestD = 26 * 26;
        if (inside) {
          for (const sp of spans) {
            const d = (sp.x - lx) ** 2 + (sp.y - 14 - ly) ** 2;
            if (d < bestD) {
              bestD = d;
              best = sp.id;
            }
          }
        }
        setFocus(best);
      };
      const onDown = (ev: PointerEvent) => {
        drag = { x: ev.clientX, yaw };
        el.setPointerCapture?.(ev.pointerId);
      };
      const onUp = () => {
        drag = null;
      };
      el.addEventListener("pointerdown", onDown);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointermove", onMove, { passive: true });
      el.addEventListener("pointerleave", () => !drag && setFocus(null));

      const step = (dt: number, time: number) => {
        const m = modeRef.current;
        const okArr = okGeo.attributes.position.array as Float32Array;
        const badArr = badGeo.attributes.position.array as Float32Array;
        packets.forEach((p, i) => {
          p.t += dt * p.speed;
          if (p.t >= 1) {
            p.t -= 1;
            p.bad = m !== "healthy" && p.onFault && (i * 31 + Math.floor(time)) % 3 !== 1;
          }
          if (m === "healthy" || !p.onFault) p.bad = false;
          tmp.lerpVectors(p.a, p.b, p.t);
          // Network: lost half-way along the wire. Application: arrives, then fails.
          const gone = p.bad && (m === "network" ? p.t > 0.55 : p.t > 0.97);
          const arr = p.bad ? badArr : okArr;
          const other = p.bad ? okArr : badArr;
          arr.set(gone ? OFF : tmp.toArray(), i * 3);
          other.set(OFF, i * 3);
        });
        okGeo.attributes.position.needsUpdate = true;
        badGeo.attributes.position.needsUpdate = true;
        const pulse = 1 + 0.35 * Math.sin(time * 2.4);
        ring.scale.setScalar(pulse);
        mat.ring.opacity = Math.max(0, 0.55 - 0.3 * (pulse - 0.65));
        // Small turns only, so labels never stack up edge-on.
        const auto = drag ? 0 : Math.sin(time * 0.12) * 0.26 + px * 0.1;
        world.rotation.y += (yaw + auto - world.rotation.y) * 0.05;
        world.rotation.x += (-0.12 + py * 0.08 - world.rotation.x) * 0.04;
      };

      function draw() {
        if (!w || !h) return;
        renderer.render(scene, camera);
        world.updateMatrixWorld();
        for (const sp of spans) {
          tmp.copy(sp.p).applyMatrix4(world.matrixWorld);
          const depth = tmp.z;
          tmp.project(camera);
          sp.x = (tmp.x * 0.5 + 0.5) * w;
          sp.y = (-tmp.y * 0.5 + 0.5) * h + 14;
          sp.s.style.transform = `translate(-50%, -50%) translate(${sp.x.toFixed(1)}px, ${sp.y.toFixed(1)}px)`;
          const dim = focused && focused !== sp.id ? 0.3 : 1;
          sp.s.style.opacity = String(dim * Math.max(0.4, Math.min(1, 0.75 + depth * 0.4)));
        }
      }

      const ro = new ResizeObserver(resize);
      ro.observe(el);
      resize();

      let raf = 0;
      let last = performance.now();
      let visible = true;
      const loop = (now: number) => {
        const dt = Math.min(0.05, (now - last) / 1000);
        last = now;
        step(dt, now / 1000);
        draw();
        raf = requestAnimationFrame(loop);
      };
      const start = () => {
        cancelAnimationFrame(raf);
        if (reduced.matches || !visible || document.hidden) {
          step(0, 0);
          draw();
          return;
        }
        last = performance.now();
        raf = requestAnimationFrame(loop);
      };
      const io = new IntersectionObserver(([e]) => {
        visible = e.isIntersecting;
        start();
      });
      io.observe(el);
      const onVis = () => start();
      document.addEventListener("visibilitychange", onVis);
      reduced.addEventListener("change", start);

      applyMode.current();
      step(0, 0);
      draw();
      setLive(true);
      start();

      cleanup = () => {
        cancelAnimationFrame(raf);
        io.disconnect();
        ro.disconnect();
        el.removeEventListener("pointerdown", onDown);
        window.removeEventListener("pointerup", onUp);
        window.removeEventListener("pointermove", onMove);
        document.removeEventListener("visibilitychange", onVis);
        reduced.removeEventListener("change", start);
        spans.forEach(({ s }) => s.remove());
        scene.traverse((o) => (o as { geometry?: { dispose: () => void } }).geometry?.dispose());
        Object.values(mat).forEach((m) => m.dispose());
        renderer.dispose();
        renderer.domElement.remove();
        applyMode.current = () => {};
      };
    });

    return () => {
      disposed = true;
      cleanup();
    };
  }, []);

  return (
    <div
      className="stage"
      role="img"
      aria-label="Service map of the OpenTelemetry Demo shop: 19 services and the requests between them. The highlighted link is checkout to payment, where the fault is shown."
    >
      {!live && (
        <div className="stage-fallback">
          <ServiceMapStatic />
        </div>
      )}
      <div ref={host} className="stage grab" />
      <div ref={labels} className="stage-labels" />
      {hover && (
        <div className="stage-tip" aria-live="polite">
          <b>{hover.id}</b> calls {hover.calls} · called by {hover.calledBy}
        </div>
      )}
    </div>
  );
}
