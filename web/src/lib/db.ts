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

export const PAGE_SIZE = 20;

export interface SearchOptions {
  ente?: string;
  year?: number;
  page?: number;
  pageSize?: number;
}

type RowMapper<T> = (r: unknown) => T;
const toJson: RowMapper<LeiRow> = (r) => (r as { toJSON(): LeiRow }).toJSON();

function buildWhere(query: string, ente?: string, year?: number) {
  const clauses = ['ate IS NULL'];
  const params: Array<string | number> = [];
  if (query.trim()) {
    clauses.push('texto_normalizado ILIKE ?');
    params.push(`%${query.trim()}%`);
  }
  if (ente) {
    clauses.push('ente = ?');
    params.push(ente);
  }
  if (year != null && year > 0) {
    // em is a DATE column inferred by read_json_auto; YEAR(NULL) = NULL → safe
    clauses.push('YEAR(em) = ?');
    params.push(year);
  }
  return { where: clauses.join(' AND '), params };
}

async function runSql<T>(
  sql: string,
  params: Array<string | number>,
  mapper: RowMapper<T>,
): Promise<T[]> {
  const db = await getDb();
  const conn = await db.connect();
  try {
    if (params.length === 0) {
      const result = await conn.query(sql);
      return result.toArray().map(mapper);
    }
    const stmt = await conn.prepare(sql);
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const result = await (stmt as any).query(...params);
      return result.toArray().map(mapper);
    } finally {
      await stmt.close();
    }
  } finally {
    await conn.close();
  }
}

export async function searchLeisFiltered(query: string, opts: SearchOptions = {}): Promise<LeiRow[]> {
  const { ente, year, page = 0, pageSize = PAGE_SIZE } = opts;
  // Math.trunc + bounds enforce integer values — LIMIT/OFFSET cannot be injected.
  // DuckDB prepared statements do not support ? placeholders in LIMIT/OFFSET clauses.
  // Number.isFinite guard prevents NaN from reaching the SQL string (e.g. if caller
  // passes NaN explicitly; normal path always receives valid integers from PAGE_SIZE).
  const safeSize = Math.min(100, Math.max(1, Math.trunc(Number.isFinite(pageSize) ? pageSize : PAGE_SIZE)));
  const offset = Math.max(0, Math.trunc(Number.isFinite(page) ? page : 0)) * safeSize;
  const { where, params } = buildWhere(query, ente, year);
  // ORDER BY (lei_id, dispositivo_path) is globally unique → stable pagination across pages.
  const sql = `SELECT * FROM versoes WHERE ${where} ORDER BY lei_id, dispositivo_path LIMIT ${safeSize} OFFSET ${offset}`;
  return runSql(sql, params, toJson);
}

export async function countLeisFiltered(
  query: string,
  opts: Pick<SearchOptions, 'ente' | 'year'> = {},
): Promise<number> {
  const { where, params } = buildWhere(query, opts.ente, opts.year);
  const rows = await runSql<{ cnt: bigint | number }>(
    `SELECT COUNT(*)::BIGINT AS cnt FROM versoes WHERE ${where}`,
    params,
    (r) => (r as { toJSON(): { cnt: bigint | number } }).toJSON(),
  );
  return Number(rows[0]?.cnt ?? 0);
}

/** @deprecated Use searchLeisFiltered instead. Max 100 rows (capped by searchLeisFiltered). */
export async function searchLeis(query: string, limit = 20): Promise<LeiRow[]> {
  return searchLeisFiltered(query, { pageSize: limit });
}
