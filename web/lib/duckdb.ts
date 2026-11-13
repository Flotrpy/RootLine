// DuckDB-WASM, loaded only when a page asks for it, from bundles the site
// hosts itself (scripts/copy-duckdb.mjs).
import type { AsyncDuckDB } from "@duckdb/duckdb-wasm";

import { asset } from "./format";
import type { RunRow } from "./types";

let db: Promise<AsyncDuckDB> | null = null;

async function open(): Promise<AsyncDuckDB> {
  const duckdb = await import("@duckdb/duckdb-wasm");
  const bundle = await duckdb.selectBundle({
    mvp: {
      mainModule: asset("/duckdb/duckdb-mvp.wasm"),
      mainWorker: asset("/duckdb/duckdb-browser-mvp.worker.js"),
    },
    eh: {
      mainModule: asset("/duckdb/duckdb-eh.wasm"),
      mainWorker: asset("/duckdb/duckdb-browser-eh.worker.js"),
    },
  });
  const worker = new Worker(bundle.mainWorker!);
  const instance = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), worker);
  await instance.instantiate(bundle.mainModule, bundle.pthreadWorker);
  const url = new URL(asset("/data/runs.parquet"), window.location.href).toString();
  await instance.registerFileURL("runs.parquet", url, duckdb.DuckDBDataProtocol.HTTP, false);
  return instance;
}

export function getDB(): Promise<AsyncDuckDB> {
  db ??= open();
  return db;
}

/** Every model's run on one incident, condition and perturbation. */
export async function runsFor(
  incident: string,
  condition: string,
  perturbation: string,
): Promise<RunRow[]> {
  const conn = await (await getDB()).connect();
  try {
    const stmt = await conn.prepare(
      `SELECT model_id, tier, condition, perturbation, raw_output, parsed_ok, top1,
              layer_ok, confidence
         FROM read_parquet('runs.parquet')
        WHERE incident_id = ? AND condition = ? AND perturbation = ?
        ORDER BY tier DESC, model_id`,
    );
    const table = await stmt.query(incident, condition, perturbation);
    await stmt.close();
    return table.toArray().map((r) => r.toJSON() as RunRow);
  } finally {
    await conn.close();
  }
}
