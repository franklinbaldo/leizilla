/**
 * Camada de texto (ADR-0015) — funções puras sobre uma linha de `textos`.
 *
 * O texto é verbatim (OCR do Internet Archive, sem correção). As âncoras de artigo são
 * dado derivado: offsets em **code points Unicode** sobre esse texto. Aqui elas só
 * dividem o texto em trechos navegáveis — a concatenação dos trechos é sempre idêntica
 * ao texto original.
 */

export interface Ancora {
  /** Número do artigo como lido pela sequência (pode diferir do literal do OCR). */
  n: number;
  /** Letra de sufixo ("A" em Art. 8º-A), ou null. */
  sufixo: string | null;
  /** Início do marcador no texto (code point, inclusivo). */
  ini: number;
  /** Fim do marcador no texto (code point, exclusivo). */
  fim: number;
}

/** A coluna `ancoras` é JSON serializado. Fail-open: [] em qualquer malformação. */
export function parseAncoras(json: string | null | undefined): Ancora[] {
  if (!json) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(json);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  const out: Ancora[] = [];
  for (const item of parsed) {
    if (typeof item !== 'object' || item === null) return [];
    const a = item as Record<string, unknown>;
    if (
      !Number.isInteger(a.n) ||
      !Number.isInteger(a.ini) ||
      !Number.isInteger(a.fim) ||
      (a.sufixo != null && typeof a.sufixo !== 'string')
    ) {
      return [];
    }
    out.push({
      n: a.n as number,
      sufixo: (a.sufixo as string | null | undefined) ?? null,
      ini: a.ini as number,
      fim: a.fim as number,
    });
  }
  return out;
}

/** Id de âncora no mesmo formato dos paths estruturados: "art-4", "art-8-a". */
export function ancoraId(a: Pick<Ancora, 'n' | 'sufixo'>): string {
  return a.sufixo ? `art-${a.n}-${a.sufixo.toLowerCase()}` : `art-${a.n}`;
}

/** Rótulo legístico: 1º–9º ordinais, 10 em diante cardinais. */
export function ancoraRotulo(a: Pick<Ancora, 'n' | 'sufixo'>): string {
  const base = a.n >= 1 && a.n <= 9 ? `${a.n}º` : String(a.n);
  return `Art. ${base}${a.sufixo ? `-${a.sufixo.toUpperCase()}` : ''}`;
}

export interface Segmento {
  /** Id do elemento quando o trecho começa num artigo; null para o que vem antes. */
  id: string | null;
  rotulo: string | null;
  /** Fatia exata do texto original. */
  texto: string;
}

/**
 * Divide o texto nos inícios das âncoras. Não altera nenhum caractere: a junção de
 * `segmento.texto` reproduz `texto`. Âncoras fora do texto ou fora de ordem invalidam a
 * navegação inteira (um único trecho, sem ids) em vez de arriscar um corte errado.
 */
export function segmentar(texto: string, ancoras: Ancora[]): Segmento[] {
  const whole: Segmento[] = [{ id: null, rotulo: null, texto }];
  if (ancoras.length === 0) return whole;

  // Offsets são code points; strings JS indexam UTF-16. Só há diferença quando o
  // texto tem caracteres fora do BMP — aí convertemos por um mapa de posições.
  const codePoints = Array.from(texto);
  const astral = codePoints.length !== texto.length;
  let unitAt: (cp: number) => number = (cp) => cp;
  if (astral) {
    const starts = new Array<number>(codePoints.length + 1);
    let unit = 0;
    for (let i = 0; i < codePoints.length; i += 1) {
      starts[i] = unit;
      unit += codePoints[i].length;
    }
    starts[codePoints.length] = unit;
    unitAt = (cp) => starts[cp];
  }

  let previousEnd = 0;
  for (const a of ancoras) {
    if (a.ini < previousEnd || a.fim <= a.ini || a.fim > codePoints.length) return whole;
    previousEnd = a.fim;
  }

  const segmentos: Segmento[] = [];
  const usados = new Set<string>();
  const first = unitAt(ancoras[0].ini);
  if (first > 0) segmentos.push({ id: null, rotulo: null, texto: texto.slice(0, first) });
  ancoras.forEach((a, i) => {
    const start = unitAt(a.ini);
    const end = i + 1 < ancoras.length ? unitAt(ancoras[i + 1].ini) : texto.length;
    const id = ancoraId(a);
    // Id repetido (não deveria ocorrer numa sequência que fecha): o trecho continua
    // legível, só não vira um segundo alvo de navegação.
    const unico = !usados.has(id);
    usados.add(id);
    segmentos.push({
      id: unico ? id : null,
      rotulo: unico ? ancoraRotulo(a) : null,
      texto: texto.slice(start, end),
    });
  });
  return segmentos;
}

/**
 * Divide um trecho nas linhas em branco, mantendo os separadores no fim de cada
 * parte — a junção reproduz o trecho. Serve só para a apresentação em parágrafos
 * (o CSS recolhe as quebras simples do OCR); nenhum caractere é removido do DOM.
 */
export function paragrafos(texto: string): string[] {
  const partes = texto.split(/(\n[ \t\r]*\n\s*)/);
  const out: string[] = [];
  for (let i = 0; i < partes.length; i += 2) {
    const parte = partes[i] + (partes[i + 1] ?? '');
    if (parte) out.push(parte);
  }
  return out;
}
