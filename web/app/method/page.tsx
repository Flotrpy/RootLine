export const metadata = { title: "Method · Rootline" };

const FAULTS: [string, string, string][] = [
  ["paymentFailure", "payment", "error"],
  ["paymentUnreachable", "checkout → payment", "dependency unavailable"],
  ["productCatalogFailure", "product-catalog", "error"],
  ["productCatalogLockContention", "product-catalog", "lock contention"],
  ["emailMemoryLeak", "email", "memory leak"],
  ["recommendationCacheFailure", "recommendation", "memory leak (cache growth)"],
  ["kafkaQueueProblems", "fraud-detection", "queue lag"],
  ["intlShippingSlowdown", "shipping", "latency (non-US only)"],
  ["imageSlowLoad", "frontend-proxy", "latency"],
  ["adHighCpu", "ad", "CPU saturation"],
  ["toxiLatency", "checkout → payment", "network latency (300 ± 60 ms)"],
  ["netemLoss", "frontend → product-catalog", "network loss (5%)"],
  ["toxiReset", "checkout → payment", "network reset (20% of connections)"],
  ["toxiBandwidth", "frontend → product-catalog", "network throughput (64 KB/s)"],
  ["healthy", "–", "none (control)"],
];

export default function Method() {
  return (
    <div className="wrap page">
      <h1>Method</h1>
      <p className="lede">
        Rootline runs the live system once to freeze snapshots, then replays the same snapshots to
        every model. Only free open-weight models and free-tier APIs are evaluated, so results
        describe what budget-constrained teams can do today, not the frontier.
      </p>

      <h2>Testbed and faults</h2>
      <p>
        The OpenTelemetry Demo runs on Docker Compose, pinned to a release tag and image digests.
        Ten application faults come from the demo&apos;s feature flags, four network faults from
        Toxiproxy and <code>tc netem</code>, and one healthy control means a model cannot assume
        every snapshot is broken.
      </p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr><th>Fault</th><th>Where</th><th>Category</th></tr>
          </thead>
          <tbody>
            {FAULTS.map(([f, w, c]) => (
              <tr key={f}><td className="mono">{f}</td><td>{w}</td><td>{c}</td></tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Incident protocol</h2>
      <p>
        20 simulated users; a 5-minute baseline; the fault for 5 minutes; a snapshot of the window
        from 5 minutes before to 5 minutes after onset; then the fault is cleared, the system cools
        down for 3 minutes, and recovery is checked (error ratio within 1.5× and p99 latency within
        1.2× of baseline, for up to 10 minutes). Ground-truth labels are stored apart from the
        snapshots and never shown to a model.
      </p>

      <h2>Evidence conditions</h2>
      <p>
        Every prompt is at most 6,000 tokens, so conditions differ in signal, not size:
        <strong> metrics</strong> (per-service rates, error ratios and latency quantiles in 30-second
        buckets as change from baseline), <strong>traces</strong> (the 20 slowest and 20 errored
        traces as critical paths), <strong>logs</strong> (Drain3 templates ranked by rate change,
        two examples each), and <strong>combined</strong> (a third of the budget each). Every line
        has a stable ID so cited evidence can be checked. Perturbation <strong>P1</strong> replaces
        service names with consistent anonymous ones.
      </p>

      <h2>Metrics</h2>
      <ul>
        <li>Top-1 and top-3 accuracy on the (service, category) pair</li>
        <li>Layer attribution: network vs application</li>
        <li>Evidence validity: cited IDs that exist and belong to the root-cause service</li>
        <li>Healthy false-alarm rate; calibration (Brier score, 10-bin ECE)</li>
        <li>Cascade accuracy per 1,000 tokens and escalation rate</li>
        <li>Remediation success within 120 s and harmful-action rate, from live trials</li>
      </ul>

      <h2>Statistics</h2>
      <p>
        McNemar&apos;s exact test for paired comparisons on the same snapshots, Fisher&apos;s exact
        test for unpaired ones, 10,000-resample bootstrap confidence intervals with a fixed seed,
        and Holm correction across the research questions. Every result is reported, including
        hypotheses that fail.
      </p>

      <h2>Limitations</h2>
      <ul>
        <li>This is a pilot: two replicas per incident type give wide confidence intervals.</li>
        <li>One testbed; real production systems are larger and noisier.</li>
        <li>Network faults are emulated; the hardware arm compares them with real Wi-Fi faults.</li>
        <li>Models may have seen the demo&apos;s public code; P1 measures reliance on names.</li>
      </ul>
    </div>
  );
}
