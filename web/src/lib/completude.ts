/**
 * Livro-razão de completude — o acervo contra o índice oficial da fonte.
 *
 * `completeness.json` é calculado no pipeline (`leizilla completeness --upload`,
 * `src/leizilla/completeness.py`) e publicado no item IA do dataset, ao lado de
 * `coverage.json`. Aqui só há tipos e formatação pura; nada consulta o Parquet.
 *
 * Contrato herdado do pipeline: um contador `null` significa "não foi possível
 * medir" (ou "lista anual não lida"), nunca zero.
 */

export interface StageCounts {
  listadas: number | null;
  preservadas: number | null;
  com_texto: number | null;
  legiveis: number | null;
  estruturadas: number | null;
  faltantes: number | null;
  pct_preservadas: number | null;
  pct_com_texto: number | null;
  pct_legiveis: number | null;
  pct_estruturadas: number | null;
}

export interface DecadaCompletude extends StageCounts {
  decada: number;
  anos: number;
  anos_desconhecidos: number;
  completa: boolean;
}

export interface TipoCompletude extends StageCounts {
  tipo: string;
  rotulo: string;
  ano_inicial: number | null;
  ano_final: number | null;
  anos: number;
  anos_lidos: number;
  catalogo_completo: boolean;
  fora_do_indice: number;
  indice_incompleto: number;
  faltantes_intervalos: [number, number][];
  faltantes_com_sufixo: string[];
  por_decada: DecadaCompletude[];
}

export interface CompletudeReport {
  ente: string;
  fonte: string;
  generated_at: string;
  git_sha: string | null;
  catalogo: {
    completo: boolean;
    paginas: number;
    paginas_lidas: number;
    anos_desconhecidos: { tipo: string; ano: number; status: string }[];
    entradas_ilegiveis?: { tipo: string; ano: number; titulo: string }[];
  };
  medicao: { ok_s2_s3: boolean; ok_s4: boolean; ok_legivel: boolean };
  tipos: TipoCompletude[];
  tipos_sem_indice: { tipo: string; preservadas: number }[];
}

/** Versão maior do contrato que esta página sabe ler. */
const SUPPORTED_MAJOR = '0';

/**
 * Valida o mínimo que o painel usa. Fail-open: qualquer coisa fora do contrato
 * devolve null e a página mostra "ainda não publicado" em vez de números errados.
 */
export function parseCompletude(data: unknown): CompletudeReport | null {
  if (typeof data !== 'object' || data === null) return null;
  const d = data as Record<string, unknown>;
  const version = d.leizilla_completeness_version;
  if (typeof version !== 'string' || version.split('.')[0] !== SUPPORTED_MAJOR) return null;
  if (!Array.isArray(d.tipos) || typeof d.catalogo !== 'object' || d.catalogo === null) return null;
  if (typeof d.medicao !== 'object' || d.medicao === null) return null;
  const ok = d.tipos.every(
    (t) =>
      typeof t === 'object' &&
      t !== null &&
      typeof (t as TipoCompletude).tipo === 'string' &&
      typeof (t as TipoCompletude).rotulo === 'string' &&
      Array.isArray((t as TipoCompletude).por_decada) &&
      Array.isArray((t as TipoCompletude).faltantes_intervalos),
  );
  return ok ? (data as CompletudeReport) : null;
}

/** `null` → "?" (não medido); número → pt-BR. */
export function fmtCount(n: number | null | undefined): string {
  return n == null ? '?' : n.toLocaleString('pt-BR');
}

export function fmtPct(p: number | null | undefined): string {
  return p == null ? '—' : `${p.toLocaleString('pt-BR', { maximumFractionDigits: 1 })}%`;
}

/** "Leis ordinárias: 187 de 626 preservadas, 177 legíveis". */
export function headline(t: TipoCompletude): string {
  return (
    `${t.rotulo}: ${fmtCount(t.preservadas)} de ${fmtCount(t.listadas)} ` +
    `${t.preservadas === 1 ? 'preservada' : 'preservadas'}, ` +
    `${fmtCount(t.legiveis)} ${t.legiveis === 1 ? 'legível' : 'legíveis'}`
  );
}

/** Estágios que não puderam ser medidos nesta rodada, em texto ("" se nenhum). */
export function unmeasuredStages(m: CompletudeReport['medicao']): string {
  const stages = [
    !m.ok_s2_s3 && 'preservação e texto (itens do Internet Archive)',
    !m.ok_legivel && 'camada de texto do portal (legíveis)',
    !m.ok_s4 && 'normas estruturadas',
  ].filter((s): s is string => Boolean(s));
  return stages.join('; ');
}

/**
 * De que recorte do índice oficial os números falam. Com o índice lido por
 * inteiro, o período; senão, quantos anos foram lidos — o resto é desconhecido.
 */
export function scopeNote(t: TipoCompletude): string {
  const periodo =
    t.ano_inicial != null && t.ano_final != null ? `${t.ano_inicial}–${t.ano_final}` : '';
  if (t.catalogo_completo) return `índice oficial completo${periodo ? ` (${periodo})` : ''}`;
  return (
    `índice oficial lido em ${t.anos_lidos} de ${t.anos} anos` +
    `${periodo ? ` (${periodo})` : ''} — os demais anos são desconhecidos, não zero`
  );
}

/** Quantas normas os intervalos cobrem. */
export function rangesTotal(ranges: [number, number][]): number {
  return ranges.reduce((acc, [a, b]) => acc + (b - a + 1), 0);
}

/**
 * Intervalos em texto compacto: `[[1,3],[7,7]]` → "1–3, 7". Corta em `max`
 * intervalos e informa quantas normas ficaram de fora (estão no Parquet).
 */
export function formatRanges(
  ranges: [number, number][],
  max = 120,
): { text: string; omitted: number } {
  const shown = ranges.slice(0, max);
  const text = shown.map(([a, b]) => (a === b ? String(a) : `${a}–${b}`)).join(', ');
  return { text, omitted: rangesTotal(ranges.slice(max)) };
}

/** Números faltantes de um tipo, sufixados ("9A") ao final. */
export function missingList(
  t: Pick<TipoCompletude, 'faltantes_intervalos' | 'faltantes_com_sufixo'>,
  max = 120,
): { text: string; omitted: number } {
  const { text, omitted } = formatRanges(t.faltantes_intervalos, max);
  return { text: [text, ...t.faltantes_com_sufixo].filter(Boolean).join(', '), omitted };
}

/** Rótulo da década: 1980 → "1980–89". */
export function decadaLabel(decada: number): string {
  return `${decada}–${String(decada + 9).slice(-2)}`;
}
