import * as duckdb from '@duckdb/duckdb-wasm';

const PARQUET_URL =
  (typeof import.meta !== 'undefined' && import.meta.env?.PUBLIC_PARQUET_URL) ||
  'https://archive.org/download/leizilla-dataset-ro-v0/versoes.parquet';

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
  tipo_lei: string;
  numero_lei: string | null;
  ano_lei: number;
  dispositivo_path: string;
  dispositivo_tipo: string;
  texto: string | null;
  texto_normalizado: string | null;
  em: string | null;
  ate: Date | null;
}

export const PAGE_SIZE = 20;

export interface SearchOptions {
  ente?: string;
  // Um valor exato, ou vários aliases equivalentes (ex: ['lei.complementar','lc'])
  // que o filtro casa via tipo_lei IN (...).
  tipoLei?: string | string[];
  year?: number;
  page?: number;
  pageSize?: number;
}

type RowMapper<T> = (r: unknown) => T;
const toJson: RowMapper<LeiRow> = (r) => (r as { toJSON(): LeiRow }).toJSON();

function buildWhere(query: string, opts: SearchOptions = {}) {
  const { ente, tipoLei, year } = opts;
  const clauses = ['ate IS NULL'];
  const params: Array<string | number> = [];
  if (query.trim()) {
    clauses.push('texto_normalizado ILIKE ?');
    params.push(`%${query.trim()}%`);
  }
  // Sem busca textual (modo navegação) NÃO filtramos por dispositivo aqui:
  // colapsamos para uma linha representativa por norma em searchLeisFiltered,
  // para não esconder leis publicadas sem ementa (SCHEMA.md §0.6).
  if (ente) {
    clauses.push('ente = ?');
    params.push(ente);
  }
  if (tipoLei) {
    // tipoLei pode ser um valor único ou vários aliases do mesmo tipo de norma
    // (lei.complementar / lc) — casamos todos de uma vez.
    const vals = (Array.isArray(tipoLei) ? tipoLei : [tipoLei]).filter(Boolean);
    if (vals.length === 1) {
      clauses.push('tipo_lei = ?');
      params.push(vals[0]);
    } else if (vals.length > 1) {
      clauses.push(`tipo_lei IN (${vals.map(() => '?').join(', ')})`);
      params.push(...vals);
    }
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
  const { page = 0, pageSize = PAGE_SIZE } = opts;
  // Math.trunc + bounds enforce integer values — LIMIT/OFFSET cannot be injected.
  // DuckDB prepared statements do not support ? placeholders in LIMIT/OFFSET clauses.
  // Number.isFinite guard prevents NaN from reaching the SQL string (e.g. if caller
  // passes NaN explicitly; normal path always receives valid integers from PAGE_SIZE).
  const safeSize = Math.min(100, Math.max(1, Math.trunc(Number.isFinite(pageSize) ? pageSize : PAGE_SIZE)));
  const offset = Math.max(0, Math.trunc(Number.isFinite(page) ? page : 0)) * safeSize;
  const { where, params } = buildWhere(query, opts);
  let sql: string;
  if (query.trim()) {
    // Busca textual: uma linha por dispositivo que casa (mostra os trechos).
    // ORDER BY (lei_id, dispositivo_path) is globally unique → stable pagination.
    sql = `SELECT * FROM versoes WHERE ${where} ORDER BY lei_id, dispositivo_path LIMIT ${safeSize} OFFSET ${offset}`;
  } else {
    // Navegação: uma linha representativa por norma. Preferimos a ementa, com
    // fallback para o primeiro dispositivo (leis em estágio incremental podem
    // não ter ementa; SCHEMA.md §0.6) — assim nenhuma norma publicada some.
    sql = `SELECT * EXCLUDE (_rn) FROM (
        SELECT *, ROW_NUMBER() OVER (
          PARTITION BY lei_id
          ORDER BY (dispositivo_path = 'ementa') DESC, dispositivo_ordem, dispositivo_path
        ) AS _rn
        FROM versoes WHERE ${where}
      ) WHERE _rn = 1
      ORDER BY lei_id LIMIT ${safeSize} OFFSET ${offset}`;
  }
  return runSql(sql, params, toJson);
}

export async function countLeisFiltered(
  query: string,
  opts: Pick<SearchOptions, 'ente' | 'tipoLei' | 'year'> = {},
): Promise<number> {
  const { where, params } = buildWhere(query, opts);
  // Navegação conta normas distintas (1 linha representativa por lei_id); busca
  // textual conta dispositivos que casam — coerente com searchLeisFiltered.
  const countExpr = query.trim() ? 'COUNT(*)' : 'COUNT(DISTINCT lei_id)';
  const rows = await runSql<{ cnt: bigint | number }>(
    `SELECT ${countExpr}::BIGINT AS cnt FROM versoes WHERE ${where}`,
    params,
    (r) => (r as { toJSON(): { cnt: bigint | number } }).toJSON(),
  );
  return Number(rows[0]?.cnt ?? 0);
}

/**
 * Distinct `tipo_lei` values present in the dataset, for the type filter.
 *
 * Driven by the data so the dropdown always uses the persisted representation
 * (the ETL stores e.g. `lei.complementar` or `lc`, never a hardcoded slug) —
 * a hardcoded option list would silently filter to zero matches if it drifted.
 */
export async function listTiposLei(): Promise<string[]> {
  const rows = await runSql<{ tipo_lei: string }>(
    "SELECT DISTINCT tipo_lei FROM versoes " +
      "WHERE tipo_lei IS NOT NULL AND tipo_lei <> 'desconhecido' ORDER BY tipo_lei",
    [],
    (r) => (r as { toJSON(): { tipo_lei: string } }).toJSON(),
  );
  return rows.map((r) => r.tipo_lei).filter(Boolean);
}

/** @deprecated Use searchLeisFiltered instead. Max 100 rows (capped by searchLeisFiltered). */
export async function searchLeis(query: string, limit = 20): Promise<LeiRow[]> {
  return searchLeisFiltered(query, { pageSize: limit });
}
