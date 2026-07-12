/**
 * Modelo da página da lei — helpers puros sobre linhas do Parquet `versoes`
 * (grain lei × dispositivo × versão; SCHEMA.md §3.1).
 *
 * Tudo aqui é derivação client-side de linhas já buscadas por getLeiRows():
 * árvore do texto vigente, agrupamento de versões, serialização JSON/CSV.
 */

import type { LeiRow } from '../../lib/db';
import { formatDate, leiUrl, parseFontes, type Fonte } from '../../lib/format';

// ---------------------------------------------------------------------------
// Datas — colunas DATE podem chegar como Date, string ou (via Arrow) número
// epoch-millis / bigint. Normalizamos antes de formatar ou comparar.
// ---------------------------------------------------------------------------

export type DateLike = string | Date | number | bigint | null | undefined;

function asDateInput(value: DateLike): string | Date | null {
  if (value == null) return null;
  if (typeof value === 'number' || typeof value === 'bigint') {
    const d = new Date(Number(value));
    return Number.isNaN(d.getTime()) ? null : d;
  }
  return value;
}

/** formatDate tolerante a epoch-millis vindos do Arrow. */
export function fmtDate(value: DateLike): string {
  return formatDate(asDateInput(value));
}

/** Chave numérica de ordenação cronológica (0 para nulos/inválidos). */
export function dateMs(value: DateLike): number {
  const v = asDateInput(value);
  if (v == null) return 0;
  const d = v instanceof Date ? v : new Date(`${v}`.slice(0, 10) + 'T00:00:00Z');
  const t = d.getTime();
  return Number.isNaN(t) ? 0 : t;
}

/** DATE → 'YYYY-MM-DD' para exports (JSON/CSV); null preservado. */
export function isoDate(value: DateLike): string | null {
  const v = asDateInput(value);
  if (v == null) return null;
  if (v instanceof Date) {
    return Number.isNaN(v.getTime()) ? null : v.toISOString().slice(0, 10);
  }
  return `${v}`.slice(0, 10);
}

// ---------------------------------------------------------------------------
// Texto vigente — uma linha por dispositivo (ate IS NULL; fallback: mais
// recente) e árvore via dispositivo_parent_path + dispositivo_ordem.
// ---------------------------------------------------------------------------

export interface DispositivoNode {
  row: LeiRow;
  children: DispositivoNode[];
}

/** Tipos organizacionais (agrupadores) — renderizados como headings. */
export const ORGANIZACIONAIS = new Set([
  'livro',
  'parte',
  'titulo',
  'capitulo',
  'secao',
  'subsecao',
]);

/**
 * Uma linha exibível por dispositivo: prefere a versão vigente (`ate IS
 * NULL`); um dispositivo revogado (todas as versões encerradas) mantém a
 * última redação, para ser exibido riscado com a nota de revogação — leitores
 * jurídicos precisam ver o que existiu, não um buraco na numeração.
 */
export function currentRows(rows: LeiRow[]): LeiRow[] {
  const byPath = new Map<string, LeiRow>();
  for (const row of rows) {
    const prev = byPath.get(row.dispositivo_path);
    if (!prev) {
      byPath.set(row.dispositivo_path, row);
      continue;
    }
    const prevVigente = prev.ate == null;
    const rowVigente = row.ate == null;
    if (rowVigente !== prevVigente) {
      if (rowVigente) byPath.set(row.dispositivo_path, row);
    } else if (dateMs(row.em) >= dateMs(prev.em)) {
      byPath.set(row.dispositivo_path, row);
    }
  }
  return [...byPath.values()];
}

export interface TextoVigente {
  ementa: LeiRow | null;
  roots: DispositivoNode[];
}

/**
 * Árvore do texto vigente. Parent ausente no conjunto (fail-open, dado
 * incremental — SCHEMA.md §0.6) promove o nó a top-level em vez de sumir.
 * A ementa sai da árvore e é renderizada à parte, como resumo da norma.
 */
export function buildTree(rows: LeiRow[]): TextoVigente {
  const vigentes = currentRows(rows);
  const ementa = vigentes.find((r) => r.dispositivo_path === 'ementa') ?? null;

  const nodes = new Map<string, DispositivoNode>();
  for (const row of vigentes) {
    if (row.dispositivo_path === 'ementa') continue;
    nodes.set(row.dispositivo_path, { row, children: [] });
  }

  const roots: DispositivoNode[] = [];
  for (const node of nodes.values()) {
    const parentPath = node.row.dispositivo_parent_path;
    const parent = parentPath ? nodes.get(parentPath) : undefined;
    if (parent && parent !== node) {
      parent.children.push(node);
    } else {
      roots.push(node);
    }
  }

  const byOrdem = (a: DispositivoNode, b: DispositivoNode) =>
    Number(a.row.dispositivo_ordem) - Number(b.row.dispositivo_ordem) ||
    a.row.dispositivo_path.localeCompare(b.row.dispositivo_path);
  const sortRec = (list: DispositivoNode[]) => {
    list.sort(byOrdem);
    for (const n of list) sortRec(n.children);
  };
  sortRec(roots);

  return { ementa, roots };
}

// ---------------------------------------------------------------------------
// Versões — histórico por dispositivo
// ---------------------------------------------------------------------------

export interface DispositivoHistorico {
  path: string;
  versions: LeiRow[]; // ordem cronológica (em asc)
}

/**
 * Dispositivos com histórico relevante: mais de uma versão, alguma versão
 * encerrada (`ate` preenchido) ou alteração declarada (`alterado_por`).
 * Ordem documental (dispositivo_ordem, path).
 */
export function groupHistorico(rows: LeiRow[]): DispositivoHistorico[] {
  const byPath = new Map<string, LeiRow[]>();
  for (const row of rows) {
    const list = byPath.get(row.dispositivo_path) ?? [];
    list.push(row);
    byPath.set(row.dispositivo_path, list);
  }
  const out: DispositivoHistorico[] = [];
  for (const [path, versions] of byPath) {
    const hasHistory =
      versions.length > 1 ||
      versions.some((v) => v.ate != null || v.alterado_por != null);
    if (!hasHistory) continue;
    versions.sort((a, b) => dateMs(a.em) - dateMs(b.em));
    out.push({ path, versions });
  }
  out.sort(
    (a, b) =>
      Number(a.versions[0].dispositivo_ordem) - Number(b.versions[0].dispositivo_ordem) ||
      a.path.localeCompare(b.path),
  );
  return out;
}

/** Labels pt-BR para o enum `inicio_tipo` (SCHEMA.md §3.1). */
export const INICIO_TIPO_LABELS: Record<string, string> = {
  'data-publicacao': 'vigência desde a publicação',
  'texto-lei-alteradora': 'redação dada por lei alteradora',
  'vacatio-legis': 'vacatio legis',
  consolidacao: 'consolidação',
  'inferencia-llm': 'inferido pelo parser',
  'decisao-judicial': 'decisão judicial',
};

export function inicioTipoLabel(tipo: string | null | undefined): string {
  if (!tipo) return '—';
  return INICIO_TIPO_LABELS[tipo] ?? tipo;
}

// ---------------------------------------------------------------------------
// Evidências — fontes agregadas em todas as versões
// ---------------------------------------------------------------------------

export interface FonteAgregada {
  ia_id: string;
  diverge: boolean;
  textos_divergentes: string[];
}

/** Fontes distintas (por ia_id) em todas as versões; marca divergências. */
export function aggregateFontes(rows: LeiRow[]): FonteAgregada[] {
  const byId = new Map<string, FonteAgregada>();
  for (const row of rows) {
    for (const fonte of parseFontes(row.fontes) as Fonte[]) {
      if (!fonte?.ia_id) continue;
      const agg = byId.get(fonte.ia_id) ?? {
        ia_id: fonte.ia_id,
        diverge: false,
        textos_divergentes: [],
      };
      if (fonte.diverge) agg.diverge = true;
      if (fonte.texto_divergente && !agg.textos_divergentes.includes(fonte.texto_divergente)) {
        agg.textos_divergentes.push(fonte.texto_divergente);
      }
      byId.set(fonte.ia_id, agg);
    }
  }
  return [...byId.values()].sort((a, b) => a.ia_id.localeCompare(b.ia_id));
}

/**
 * Busca no IA pelo ia_id entre aspas — resolver honesto: ids lógicos raw vivem
 * DENTRO de itens-balde por faixa (ADR-0010/0011), então /details/ direto pode
 * dar 404.
 */
export function iaSearchUrl(term: string): string {
  return `https://archive.org/search?query=${encodeURIComponent(`"${term}"`)}`;
}

// ---------------------------------------------------------------------------
// Deep-link e clipboard
// ---------------------------------------------------------------------------

/** URL absoluta e estável de um dispositivo (para "copiar link"). */
export function absoluteLeiUrl(leiId: string, dispositivoPath?: string): string {
  return new URL(leiUrl(leiId, dispositivoPath), location.origin).href;
}

/** Clipboard com fallback textarea para contextos sem navigator.clipboard. */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* cai para o fallback */
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Exports (JSON/CSV) — serializam as linhas já buscadas, client-side
// ---------------------------------------------------------------------------

/** Ordem estável das colunas nos exports — espelha LeiRow / SCHEMA.md §3.1. */
export const EXPORT_COLUMNS: Array<keyof LeiRow> = [
  'lei_id',
  'ente',
  'tipo_lei',
  'numero_lei',
  'ano_lei',
  'data_publicacao',
  'urn_lex_lei',
  'vigente_em',
  'lei_revogada',
  'lei_revogada_em',
  'lei_revogada_por',
  'lei_revogada_tipo',
  'dispositivo_path',
  'dispositivo_tipo',
  'dispositivo_ordem',
  'dispositivo_parent_path',
  'dispositivo_revogado',
  'dispositivo_revogado_em',
  'dispositivo_revogado_por',
  'dispositivo_revogado_tipo',
  'urn_dispositivo',
  'versao_id',
  'em',
  'ate',
  'alterado_por',
  'inicio_tipo',
  'fontes',
  'num_fontes',
  'tem_divergencia',
  'hash_texto',
  'texto',
  'texto_normalizado',
];

const DATE_COLUMNS = new Set<keyof LeiRow>([
  'data_publicacao',
  'vigente_em',
  'lei_revogada_em',
  'dispositivo_revogado_em',
  'em',
  'ate',
]);

function exportValue(row: LeiRow, col: keyof LeiRow): unknown {
  const v = row[col];
  if (v == null) return null;
  if (DATE_COLUMNS.has(col)) return isoDate(v as DateLike);
  if (typeof v === 'bigint') return Number(v);
  return v;
}

/** Uma linha por versão, valores normalizados (datas ISO, sem bigint). */
export function rowsToJson(rows: LeiRow[]): string {
  const plain = rows.map((row) => {
    const out: Record<string, unknown> = {};
    for (const col of EXPORT_COLUMNS) out[col] = exportValue(row, col);
    return out;
  });
  return JSON.stringify(plain, null, 2);
}

/** RFC-4180: aspas duplicadas; campo entre aspas se contém , " ou quebra. */
function csvField(value: unknown): string {
  if (value == null) return '';
  const s = typeof value === 'boolean' ? (value ? 'true' : 'false') : String(value);
  if (/[",\r\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

export function rowsToCsv(rows: LeiRow[]): string {
  const lines = [EXPORT_COLUMNS.join(',')];
  for (const row of rows) {
    lines.push(EXPORT_COLUMNS.map((col) => csvField(exportValue(row, col))).join(','));
  }
  return lines.join('\r\n') + '\r\n';
}

/** Download client-side via Blob + object URL. */
export function downloadBlob(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
