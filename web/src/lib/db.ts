import * as duckdb from '@duckdb/duckdb-wasm';

const PARQUET_URL =
  (typeof import.meta !== 'undefined' && import.meta.env?.PUBLIC_PARQUET_URL) ||
  'https://archive.org/download/leizilla-dataset-ro-v0/versoes-ro-v0.parquet';

const WASM_VERSION = '1.32.0';
const CDN = `https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@${WASM_VERSION}/dist/`;

const BUNDLES: duckdb.DuckDBBundles = {
  mvp: {
    mainModule: `${CDN}duckdb-mvp.wasm`,
    mainWorker: `${CDN}duckdb-browser-mvp.worker.js`,
  },
  eh: {
    mainModule: `${CDN}duckdb-eh.wasm`,
    mainWorker: `${CDN}duckdb-browser-eh.worker.js`,
    pthreadWorker: `${CDN}duckdb-browser-eh-pthread.worker.js`,
  },
};

let _db: duckdb.AsyncDuckDB | null = null;
let _initPromise: Promise<duckdb.AsyncDuckDB> | null = null;

async function _init(): Promise<duckdb.AsyncDuckDB> {
  const bundle = await duckdb.selectBundle(BUNDLES);
  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${bundle.mainWorker}");`], { type: 'text/javascript' }),
  );
  const worker = new Worker(workerUrl);
  const logger = new duckdb.ConsoleLogger(duckdb.LogLevel.WARNING);
  const db = new duckdb.AsyncDuckDB(logger, worker);
  try {
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);

    const conn = await db.connect();
    try {
      await conn.query(
        `CREATE OR REPLACE VIEW versoes AS SELECT * FROM read_parquet('${PARQUET_URL}');`,
      );
    } finally {
      await conn.close();
    }
  } catch (e) {
    await db.terminate().catch(() => {}); // cleanup orphaned worker; ignore secondary errors
    throw e;
  } finally {
    URL.revokeObjectURL(workerUrl); // always revoke, even if instantiate fails
  }

  return db;
}

export function getDb(): Promise<duckdb.AsyncDuckDB> {
  if (_db) return Promise.resolve(_db);
  if (!_initPromise) {
    _initPromise = _init().then(
      (db) => {
        _db = db;
        return db;
      },
      (err) => {
        _initPromise = null; // allow retry on next call after transient failure
        throw err;
      },
    );
  }
  return _initPromise;
}

export interface LeiRow {
  lei_id: string;
  ente: string;
  dispositivo_path: string;
  dispositivo_tipo: string;
  texto_normalizado: string | null;
  em: string | null;
  ate: Date | null;
}

export async function searchLeis(query: string, limit = 20): Promise<LeiRow[]> {
  const safeLimit = Math.trunc(Math.max(1, Math.min(1000, Number.isFinite(limit) ? limit : 20)));
  const db = await getDb();
  const conn = await db.connect();
  try {
    const term = query.trim();
    if (!term) {
      const result = await conn.query(
        `SELECT * FROM versoes WHERE ate IS NULL LIMIT ${safeLimit}`,
      );
      return result.toArray().map((r: unknown) => (r as { toJSON(): LeiRow }).toJSON());
    }
    const stmt = await conn.prepare(
      `SELECT * FROM versoes WHERE ate IS NULL AND texto_normalizado ILIKE ? LIMIT ${safeLimit}`,
    );
    try {
      const result = await stmt.query(`%${term}%`);
      return result.toArray().map((r: unknown) => (r as { toJSON(): LeiRow }).toJSON());
    } finally {
      await stmt.close();
    }
  } finally {
    await conn.close();
  }
}
