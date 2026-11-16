// Self-host DuckDB-WASM's bundles so the site needs no CDN at runtime.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const dist = dirname(require.resolve("@duckdb/duckdb-wasm/dist/duckdb-mvp.wasm"));
const out = join(import.meta.dirname, "..", "public", "duckdb");
mkdirSync(out, { recursive: true });
for (const f of [
  "duckdb-mvp.wasm",
  "duckdb-eh.wasm",
  "duckdb-browser-mvp.worker.js",
  "duckdb-browser-eh.worker.js",
]) {
  copyFileSync(join(dist, f), join(out, f));
}
console.log(`copied DuckDB-WASM bundles to ${out}`);
