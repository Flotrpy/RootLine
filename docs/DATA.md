# Data contracts

Change these only with flotrpy's sign-off. The Go snapshotter's golden test
and the Python contract test (`harness/tests/test_contract.py`) fail if the
two sides disagree.

## Incident IDs

`<fault>-r<replica>`, for example `paymentFailure-r1`, `toxiLatency-r2`,
`healthy-r1`, `hwWeakSignal-r3`.

## Snapshot directory

`data/snapshots/<incident_id>/`, written atomically (temp directory, then
rename). Existing snapshots are never overwritten.

### spans.parquet

| Column | Type | Notes |
|--------|------|-------|
| trace_id | string | hex |
| span_id | string | hex |
| parent_span_id | string, nullable | null for root spans |
| service | string | resource `service.name` |
| operation | string | span name |
| start_unix_nano | int64 | |
| duration_ns | int64 | clamped at 0 |
| status_code | string | `STATUS_CODE_UNSET`, `STATUS_CODE_OK`, `STATUS_CODE_ERROR` |
| attributes | string | JSON object, sorted keys |

### metrics.parquet

| Column | Type | Notes |
|--------|------|-------|
| ts | int64 | unix ms |
| service | string | |
| metric_name | string | see flattening rules |
| value | float64 | |
| labels | string | data point attributes, JSON object, sorted keys |

Flattening rules (snapshotter):

- Gauges: one row per data point.
- Sums: one row per data point. Delta monotonic sums are accumulated into
  cumulative values, so every counter is cumulative.
- Histograms: `<name>.count` (cumulative count) plus `<name>.p50`,
  `<name>.p95`, `<name>.p99` computed from the buckets observed **since the
  previous data point** of that series, not all-time. The first point of a
  series emits only `.count`.
- Summaries: `<name>.q<quantile>` and `<name>.count`.
- Exponential histograms: not flattened yet.

Packer conventions: names ending `_total`, `.count`, or equal to a span
metric call counter are treated as counters and turned into per-second
rates; everything else is a gauge (bucket maximum). Span metric call
counters also yield `request_rate` and `error_ratio` per service.

### logs.parquet

| Column | Type | Notes |
|--------|------|-------|
| ts | int64 | unix ms; observed time if the record has none |
| service | string | |
| severity | string | severity text, or the severity number's name |
| body | string | strings as-is, other values as JSON |
| trace_id | string, nullable | hex |

### manifest.json

```json
{
  "incident_id": "paymentFailure-r1",
  "demo_git_tag": "...",
  "image_digests": {"image": "repo@sha256:..."},
  "t0_unix_ms": 1800000000000,
  "window_ms": 600000,
  "collector_version": "...",
  "snapshotter_git_sha": "...",
  "host_ram_gb": 16
}
```

The window is `[t0 - window_ms/2, t0 + window_ms/2)`.

## Labels

`data/labels/<incident_id>.json`, written by `rootlinectl` before injection
and gitignored until release. Never read by packers.

```json
{"fault": "toxiReset", "service": "payment", "category": "network_reset",
 "layer": "network", "edge": "checkout->payment", "flag": null, "variant": null}
```

Categories: `cpu_saturation`, `dependency_unavailable`, `error`, `latency`,
`lock_contention`, `memory_leak`, `network_latency`, `network_loss`,
`network_reset`, `network_throughput`, `queue_lag`, `none`.

## Model output

See `harness/rootline_harness/schema.py`. Strict: no extra keys, unique
ranks, confidence in [0, 1], a target for every action except `no_action`.
One surrounding Markdown code fence is tolerated. Invalid output gets one
retry with the error appended; a second failure is scored as an abstention
and counted as `invalid_output`.

## Evidence packs

Each line: `<ID> <text>`, IDs `M-0001`, `T-0001`, `L-0001` assigned in rank
order before truncation, so the same evidence keeps its ID across
conditions. Every fault and flag name is replaced with `<redacted>` in every
pack. `Pack.to_json()` stores each line's services for evidence-validity
scoring.
