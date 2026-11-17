/**
 * Consultas do catálogo oficial (ADR-0017) sobre o DuckDB-WASM.
 *
 * `catalogo.parquet` (livro-razão de completude estendido) e `relacoes.parquet` são
 * materializados uma vez em tabelas em memória (`catalogo_t`, `relacoes_t`): a busca
 * varre a coluna `busca` de ~45 mil linhas e não deve decodificar Parquet a cada tecla.
 * Tudo é aditivo e fail-open: sem os arquivos publicados, `catalogoAvailable()` é false
 * e o portal segue com a busca anterior (`versoes` + `textos`).
 */

import {
  getCatalogoSourceUrl,
  getDb,
  getRelacoesSourceUrl,
  getTextoIdsComTexto,
  PAGE_SIZE,
  runSql,
} from './db';
import {
  buildCatalogoWhere,
  comCamadaDeTexto,
  type CatalogoRow,
  type FiltrosCatalogo,
  type RelacaoRow,
} from './catalogo';

const CATALOGO_COLUNAS = `norma_id, tipo, numero::INTEGER AS numero, sufixo, situacao, titulo, data,
  ano::INTEGER AS ano, decada::INTEGER AS decada, ementa, coddoc::INTEGER AS coddoc, arquivos,
  preservada, com_texto, legivel, estruturada, identidade_incerta, rendicoes, situacao_norma,
  situacao_evidencias, url_oficial, url_ia, link_publico, ia_item, texto_id,
  catalogo_obtido_em, busca`;

/** Colunas devolvidas ao portal (sem `busca`, que só serve ao filtro). */
const CATALOGO_SELECT = CATALOGO_COLUNAS.replace(', busca', '').replace(/\s+/g, ' ');

const toJson = <T>(r: unknown): T => (r as { toJSON(): T }).toJSON();

/**
 * Aplica a camada de texto às linhas do catálogo (ver `comCamadaDeTexto`): a página e o
 * selo de cada norma dependem do `textos` publicado agora, não do catálogo ter sido
 * regenerado depois. Fail-open: se a consulta falhar, as linhas seguem como vieram.
 */
async function comTextoDaCamada<T extends CatalogoRow>(rows: T[]): Promise<T[]> {
  if (rows.length === 0) return rows;
  const comTexto = await getTextoIdsComTexto(rows.map((r) => r.norma_id)).catch(
    () => new Set<string>(),
  );
  return rows.map((r) => comCamadaDeTexto(r, comTexto));
}

let _catalogoReady: Promise<boolean> | null = null;
let _relacoesReady: Promise<boolean> | null = null;

async function materializar(sql: string): Promise<boolean> {
  const db = await getDb();
  const conn = await db.connect();
  try {
    await conn.query(sql);
    return true;
  } catch {
    return false;
  } finally {
    await conn.close();
  }
}

/** `false` se o espelho do catálogo não existe ou não tem o contrato esperado. */
export function catalogoAvailable(): Promise<boolean> {
  if (!_catalogoReady) {
    _catalogoReady = materializar(
      `CREATE TABLE IF NOT EXISTS catalogo_t AS
         SELECT ${CATALOGO_COLUNAS} FROM read_parquet('${getCatalogoSourceUrl()}')`,
    ).catch((err) => {
      _catalogoReady = null;
      throw err;
    });
  }
  return _catalogoReady;
}

/** `false` se `relacoes.parquet` não está disponível: a página só omite o bloco. */
export function relacoesAvailable(): Promise<boolean> {
  if (!_relacoesReady) {
    _relacoesReady = catalogoAvailable()
      .then((ok) =>
        ok
          ? materializar(
              `CREATE TABLE IF NOT EXISTS relacoes_t AS
                 SELECT * FROM read_parquet('${getRelacoesSourceUrl()}')`,
            )
          : false,
      )
      .catch((err) => {
        _relacoesReady = null;
        throw err;
      });
  }
  return _relacoesReady;
}

function medir<T>(nome: string, trabalho: Promise<T>): Promise<T> {
  const inicio = typeof performance !== 'undefined' ? performance.now() : 0;
  return trabalho.finally(() => {
    if (typeof performance !== 'undefined' && performance.measure) {
      try {
        performance.measure(nome, { start: inicio, end: performance.now() });
      } catch {
        /* ambiente sem User Timing nível 3 */
      }
    }
  });
}

/** Uma página de resultados e o total de normas que casam (uma única varredura). */
export interface PaginaCatalogo {
  rows: CatalogoRow[];
  total: number;
}

/**
 * Relevância para consulta textual; sem consulta, mais recentes primeiro (data do ato,
 * depois número). `pageSize` fica entre 1 e 100. O total vem da mesma varredura
 * (`COUNT(*) OVER ()`): contar à parte dobraria o custo da busca.
 */
export async function searchCatalogo(
  q: string,
  filtros: FiltrosCatalogo = {},
  opts: { page?: number; pageSize?: number } = {},
): Promise<PaginaCatalogo> {
  const { where, whereParams, score, scoreParams } = buildCatalogoWhere(q, filtros);
  const size = Math.min(100, Math.max(1, Math.trunc(opts.pageSize ?? PAGE_SIZE)));
  const offset = Math.max(0, Math.trunc(opts.page ?? 0)) * size;
  const temConsulta = q.trim().length > 0 && score !== '0';
  const order = temConsulta
    ? '_score DESC, data DESC NULLS LAST, numero DESC, norma_id'
    : 'data DESC NULLS LAST, numero DESC, norma_id';
  const sql = `SELECT ${CATALOGO_SELECT}, _total FROM (
      SELECT *, ${score} AS _score, COUNT(*) OVER () AS _total FROM catalogo_t WHERE ${where}
    ) ORDER BY ${order} LIMIT ${size} OFFSET ${offset}`;
  const rows = await medir(
    'leizilla:catalogo-search',
    runSql<CatalogoRow & { _total: bigint | number }>(
      sql,
      [...scoreParams, ...whereParams],
      toJson<CatalogoRow & { _total: bigint | number }>,
    ),
  );
  const total = rows.length > 0 ? Number(rows[0]._total) : 0;
  const semTotal = rows.map(({ _total, ...row }) => row as CatalogoRow);
  return { rows: await comTextoDaCamada(semTotal), total };
}

/** Décadas com normas listadas, da mais recente para a mais antiga. */
export async function listDecadasCatalogo(): Promise<number[]> {
  const rows = await runSql<{ decada: number }>(
    "SELECT DISTINCT decada FROM catalogo_t WHERE situacao = 'listada' AND decada IS NOT NULL ORDER BY decada DESC",
    [],
    toJson<{ decada: number }>,
  );
  return rows.map((r) => Number(r.decada));
}

export async function listTiposCatalogoOficial(): Promise<string[]> {
  const rows = await runSql<{ tipo: string }>(
    "SELECT DISTINCT tipo FROM catalogo_t WHERE situacao = 'listada' ORDER BY tipo",
    [],
    toJson<{ tipo: string }>,
  );
  return rows.map((r) => r.tipo);
}

/** Norma do catálogo pelo `norma_id` (o raw_id legado), ou null. */
export async function getNormaCatalogo(normaId: string): Promise<CatalogoRow | null> {
  const rows = await runSql<CatalogoRow>(
    `SELECT ${CATALOGO_SELECT} FROM catalogo_t WHERE norma_id = ? LIMIT 1`,
    [normaId],
    toJson<CatalogoRow>,
  );
  return (await comTextoDaCamada(rows))[0] ?? null;
}

/**
 * Norma do catálogo que a lei estruturada cita como fonte (`versoes.fontes[].ia_id`).
 * `fontes` é JSON em texto; o `ia_id` é extraído por regex para não depender da extensão
 * JSON no WASM (mesma técnica da camada de texto).
 */
export async function getCatalogoDeLei(leiId: string): Promise<CatalogoRow | null> {
  const rows = await runSql<CatalogoRow>(
    `SELECT ${CATALOGO_SELECT} FROM catalogo_t WHERE norma_id IN (
       SELECT DISTINCT unnest(regexp_extract_all(fontes, '"ia_id":\\s*"([^"]+)"', 1))
       FROM versoes WHERE lei_id = ? AND fontes IS NOT NULL
     ) ORDER BY norma_id LIMIT 1`,
    [leiId],
    toJson<CatalogoRow>,
  );
  return (await comTextoDaCamada(rows))[0] ?? null;
}

/** Relações em que a norma age ou sofre a ação, com o título da outra ponta. */
export async function getRelacoes(normaId: string): Promise<RelacaoRow[]> {
  if (!(await relacoesAvailable())) return [];
  return runSql<RelacaoRow>(
    `SELECT r.*, o.titulo AS origem_titulo, a.titulo AS alvo_titulo
       FROM relacoes_t r
       LEFT JOIN catalogo_t o ON o.norma_id = r.origem_id
       LEFT JOIN catalogo_t a ON a.norma_id = r.alvo_id
      WHERE r.origem_id = ? OR r.alvo_id = ?
      ORDER BY r.verbo, o.data, a.data, r.relacao_id`,
    [normaId, normaId],
    toJson<RelacaoRow>,
  );
}
