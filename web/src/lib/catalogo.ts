/**
 * Catálogo oficial como produto (ADR-0017) — funções puras.
 *
 * O catálogo é o livro-razão de completude estendido (docs/SCHEMA.md §3.6): uma linha por
 * norma do índice oficial da Casa Civil, com título, data, ementa, situação lida do índice
 * e o estágio que o Leizilla alcançou. As relações entre normas (§3.7) são extraídas das
 * ementas por regras. Aqui só há lógica sem rede: normalização de busca (a mesma de
 * `leizilla.catalogo.normalizar_busca`), montagem do filtro SQL, rótulos honestos e o
 * agrupamento das relações para exibição.
 */

import { formatTipoLei, leiUrl } from './format';

// ---------------------------------------------------------------------------
// Busca
// ---------------------------------------------------------------------------

/**
 * Minúsculas, sem acentos, tudo que não é a-z0-9 vira espaço, sem bordas. É o mesmo
 * algoritmo de `leizilla.catalogo.normalizar_busca`: os dois lados têm os mesmos casos
 * de teste (tests/test_catalogo.py e catalogo.test.ts).
 */
export function normalizarBusca(texto: string): string {
  return texto
    .normalize('NFD')
    .replace(/\p{M}/gu, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

export interface Consulta {
  /** Termos normalizados (sem repetição, na ordem em que foram digitados). */
  tokens: string[];
  /** Termos que são só dígitos e podem ser o número de uma norma. */
  numeros: number[];
  /** A consulta inteira normalizada (para o bônus de frase exata). */
  frase: string;
}

/**
 * "lei 1.234" → tokens ["lei", "1234"], numeros [1234]. O ponto de milhar é removido
 * antes de normalizar, para que "1.234" seja o número 1234 e não "1" e "234".
 */
export function parseConsulta(texto: string): Consulta {
  const semMilhar = texto.replace(/(\d)\.(?=\d{3}(?!\d))/g, '$1');
  const frase = normalizarBusca(semMilhar);
  const tokens = [...new Set(frase.split(' ').filter(Boolean))];
  const numeros = tokens
    .filter((t) => /^\d{1,9}$/.test(t))
    .map((t) => Number.parseInt(t, 10))
    .filter((n) => Number.isSafeInteger(n) && n > 0 && n < 2_000_000_000);
  return { tokens, numeros, frase: tokens.join(' ') === frase ? frase : tokens.join(' ') };
}

export interface FiltrosCatalogo {
  /** Tipo canônico do índice: lei, lc, decreto, decreto-lei. */
  tipo?: string;
  ano?: number;
  decada?: number;
}

export interface ConsultaSql {
  where: string;
  whereParams: Array<string | number>;
  /** Expressão de relevância (maior = melhor) e seus parâmetros. */
  score: string;
  scoreParams: Array<string | number>;
}

/**
 * Filtro e relevância sobre a tabela `catalogo_t` (coluna `busca`, já normalizada).
 * Cada termo textual precisa aparecer como **início de palavra** (acento e caixa não
 * importam); um termo só de dígitos também casa o número da norma exato e a palavra
 * inteira (`lei 80` encontra a Lei nº 80, não a Lei nº 800). Só entram linhas
 * `situacao = 'listada'`: as órfãs do livro-razão não têm título nem ementa.
 */
export function buildCatalogoWhere(q: string, f: FiltrosCatalogo = {}): ConsultaSql {
  const consulta = parseConsulta(q);
  const clauses: string[] = ["situacao = 'listada'"];
  const whereParams: Array<string | number> = [];
  for (const token of consulta.tokens) {
    if (consulta.numeros.includes(Number.parseInt(token, 10)) && /^\d+$/.test(token)) {
      clauses.push("(numero = ? OR strpos(' ' || busca || ' ', ?) > 0)");
      whereParams.push(Number.parseInt(token, 10), ` ${token} `);
    } else {
      clauses.push("strpos(' ' || busca, ?) > 0");
      whereParams.push(` ${token}`);
    }
  }
  if (f.tipo) {
    clauses.push('tipo = ?');
    whereParams.push(f.tipo);
  }
  if (f.ano != null && Number.isInteger(f.ano)) {
    clauses.push('ano = ?');
    whereParams.push(f.ano);
  }
  if (f.decada != null && Number.isInteger(f.decada)) {
    clauses.push('decada = ?');
    whereParams.push(f.decada);
  }

  const parts: string[] = [];
  const scoreParams: Array<string | number> = [];
  if (consulta.numeros.length > 0) {
    parts.push(`CASE WHEN numero IN (${consulta.numeros.map(() => '?').join(', ')}) THEN 100 ELSE 0 END`);
    scoreParams.push(...consulta.numeros);
  }
  if (consulta.tokens.length > 1) {
    parts.push("CASE WHEN strpos(' ' || busca, ?) > 0 THEN 20 ELSE 0 END");
    scoreParams.push(` ${consulta.frase}`);
  }
  // "lei 80" é a Lei nº 80: o título normalizado começa por "lei n 80 ". Quem digitou
  // tipo + número quer a norma cujo título é exatamente esse, antes de "Lei Complementar nº 80".
  const palavras = consulta.tokens.filter((t) => !/^\d+$/.test(t));
  if (consulta.numeros.length === 1 && palavras.length > 0 && consulta.tokens.length === palavras.length + 1) {
    parts.push('CASE WHEN starts_with(busca, ?) THEN 30 ELSE 0 END');
    scoreParams.push(`${palavras.join(' ')} n ${consulta.numeros[0]} `);
  }
  if (consulta.tokens.length > 0) {
    // título e início da ementa pesam mais que uma menção no fim do texto
    parts.push(
      `CASE WHEN ${consulta.tokens.map(() => "strpos(substr(busca, 1, 160), ?) > 0").join(' AND ')} THEN 10 ELSE 0 END`,
    );
    scoreParams.push(...consulta.tokens);
  }
  return {
    where: clauses.join(' AND '),
    whereParams,
    score: parts.length > 0 ? parts.join(' + ') : '0',
    scoreParams,
  };
}

// ---------------------------------------------------------------------------
// Linhas, estágio, situação
// ---------------------------------------------------------------------------

/** Linha do catálogo usada pelo portal (subconjunto de `LEDGER_SCHEMA`). */
export interface CatalogoRow {
  norma_id: string;
  tipo: string;
  numero: number | bigint;
  sufixo: string;
  situacao: string;
  titulo: string;
  data: string | null;
  ano: number | bigint | null;
  ementa: string;
  coddoc: number | bigint | null;
  arquivos: string;
  preservada: boolean | null;
  com_texto: boolean | null;
  legivel: boolean | null;
  estruturada: boolean | null;
  identidade_incerta: boolean | null;
  rendicoes: string;
  situacao_norma: string | null;
  situacao_evidencias: string;
  url_oficial: string | null;
  url_ia: string | null;
  link_publico: string | null;
  ia_item: string | null;
  texto_id: string | null;
  catalogo_obtido_em: string | null;
}

export type Estagio = 'estruturada' | 'legivel' | 'preservada' | 'so-catalogo' | 'nao-medido';

/**
 * Até onde o Leizilla chegou com a norma. `null` numa flag é "não medido", nunca falso:
 * sem nenhuma flag verdadeira, só afirmamos "só catálogo" quando a preservação foi
 * medida e deu falso.
 */
export function estagioDe(
  row: Pick<CatalogoRow, 'preservada' | 'legivel' | 'estruturada'>,
): Estagio {
  if (row.estruturada) return 'estruturada';
  if (row.legivel) return 'legivel';
  if (row.preservada) return 'preservada';
  if (row.preservada === false) return 'so-catalogo';
  return 'nao-medido';
}

export const ESTAGIO_ROTULO: Record<Estagio, string> = {
  estruturada: 'Estruturada',
  legivel: 'Legível',
  preservada: 'Preservada',
  'so-catalogo': 'Só catálogo',
  'nao-medido': 'Catálogo',
};

export const ESTAGIO_DESCRICAO: Record<Estagio, string> = {
  estruturada:
    'O texto foi lido, estruturado em dispositivos e validado: é a leitura mais completa do Leizilla.',
  legivel:
    'O texto extraído por OCR do documento original está publicado, sem revisão e sem estrutura.',
  preservada:
    'O documento original está guardado no Internet Archive, mas ainda não há texto legível publicado.',
  'so-catalogo':
    'A norma consta do índice oficial da Casa Civil, mas o Leizilla ainda não preservou o documento original.',
  'nao-medido':
    'A norma consta do índice oficial; o estágio de preservação não foi medido nesta publicação.',
};

export const SITUACAO_ROTULO: Record<string, string> = {
  revogada: 'Revogada segundo o índice',
  retificada: 'Retificada segundo o índice',
  'tem-compilada': 'Tem versão compilada',
};

export const SITUACAO_DESCRICAO: Record<string, string> = {
  revogada:
    'O índice oficial lista um arquivo de revogação desta norma ou traz, na ementa, a anotação "revogado pelo…". Não é uma conclusão do Leizilla.',
  retificada: 'O índice oficial lista uma versão retificada desta norma.',
  'tem-compilada':
    'O índice oficial lista uma versão compilada (com as alterações incorporadas) desta norma.',
};

/** Rótulo do selo de situação, ou null quando a situação é neutra (não se exibe selo). */
export function situacaoRotulo(situacao: string | null | undefined): string | null {
  return situacao ? (SITUACAO_ROTULO[situacao] ?? null) : null;
}

/** Texto curto da ementa para listagens, cortado em fronteira de palavra. */
export function truncar(texto: string, max = 260): string {
  const t = texto.replace(/\s+/g, ' ').trim();
  if (t.length <= max) return t;
  const corte = t.slice(0, max);
  const espaco = corte.lastIndexOf(' ');
  return `${corte.slice(0, espaco > max * 0.6 ? espaco : max).trimEnd()}…`;
}

export function tipoRotulo(tipo: string): string {
  return formatTipoLei(tipo);
}

/** Lista de arquivos oficiais da norma (coluna `arquivos`, JSON). Fail-open: []. */
export interface ArquivoOficial {
  nome: string;
  url: string;
  rendicao: string;
}

export function parseArquivos(json: string | null | undefined): ArquivoOficial[] {
  if (!json) return [];
  try {
    const parsed: unknown = JSON.parse(json);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (a): a is ArquivoOficial =>
          typeof a === 'object' &&
          a !== null &&
          typeof (a as ArquivoOficial).url === 'string' &&
          typeof (a as ArquivoOficial).nome === 'string',
      )
      .map((a) => ({ nome: a.nome, url: a.url, rendicao: a.rendicao ?? 'outra' }));
  } catch {
    return [];
  }
}

export const RENDICAO_ROTULO: Record<string, string> = {
  original: 'original',
  compilada: 'compilada',
  revogado: 'marcada como revogada',
  retificado: 'retificada',
  outra: 'outro arquivo',
};

// ---------------------------------------------------------------------------
// Relações
// ---------------------------------------------------------------------------

/** Linha de `relacoes` unida ao título da outra norma, quando resolvida. */
export interface RelacaoRow {
  relacao_id: string;
  origem_id: string;
  verbo: string;
  verbo_texto: string;
  parcial: boolean;
  alvo_tipo: string;
  alvo_categoria: string;
  alvo_numero: number | bigint | null;
  alvo_sufixo: string;
  alvo_data: string | null;
  alvo_ano: number | bigint | null;
  alvo_texto: string;
  alvo_id: string | null;
  confianca: string;
  nota: string | null;
  trecho: string;
  fonte_relacao: string;
  /** Título da norma de origem / do alvo, para exibição (join com o catálogo). */
  origem_titulo?: string | null;
  alvo_titulo?: string | null;
}

/** Rótulos do ponto de vista de quem age ("Altera") e de quem sofre ("Alterada por"). */
const VERBO_ATIVO: Record<string, string> = {
  altera: 'Altera',
  revoga: 'Revoga',
  acrescenta: 'Acrescenta dispositivos a',
  'da-nova-redacao': 'Dá nova redação a',
  regulamenta: 'Regulamenta',
  prorroga: 'Prorroga',
  outro: 'Outra ação sobre',
};
const VERBO_PASSIVO: Record<string, string> = {
  altera: 'Alterada por',
  revoga: 'Revogada por',
  acrescenta: 'Recebeu acréscimos de',
  'da-nova-redacao': 'Teve a redação alterada por',
  regulamenta: 'Regulamentada por',
  prorroga: 'Prorrogada por',
  outro: 'Outra ação de',
};
const ORDEM_VERBOS = ['revoga', 'altera', 'da-nova-redacao', 'acrescenta', 'regulamenta', 'prorroga', 'outro'];

export const NOTA_ROTULO: Record<string, string> = {
  federal: 'norma federal',
  municipal: 'norma municipal',
  'constituicao-estadual': 'Constituição Estadual',
  'constituicao-federal': 'Constituição Federal',
  constituicao: 'Constituição',
  'tipo-sem-indice': 'tipo que o índice oficial não lista',
  'ausente-do-indice': 'não consta do índice oficial',
  'data-diverge': 'a data diverge da do índice',
  'data-ilegivel': 'data ilegível',
  cronologia: 'data posterior à da norma',
  autorreferencia: 'a própria norma',
  'sem-numero': 'sem número',
  'identidade-incerta': 'identidade incerta no índice',
  'origem-identidade-incerta': 'identidade incerta no índice',
};

export interface ItemRelacao {
  id: string;
  /** Há norma do catálogo para abrir; senão o item é só texto. */
  href: string | null;
  titulo: string;
  verbo: string;
  parcial: boolean;
  /** Motivo de não ser um link, ou observação sobre uma ligação incerta. */
  nota: string | null;
  confianca: string;
  fonteIndice: boolean;
}

export interface GrupoRelacao {
  rotulo: string;
  itens: ItemRelacao[];
}

function notaLegivel(nota: string | null): string | null {
  if (!nota) return null;
  if (nota.startsWith('sufixo-diverge') || nota.startsWith('candidatos')) {
    return 'mais de uma norma possível';
  }
  return NOTA_ROTULO[nota] ?? nota;
}

/** Como a referência foi escrita: "Lei nº 1.234, de 2003" a partir dos campos lidos. */
export function referenciaEscrita(r: RelacaoRow): string {
  if (r.alvo_texto) return r.alvo_texto;
  const numero = r.alvo_numero != null ? ` nº ${r.alvo_numero}${r.alvo_sufixo}` : '';
  return `${formatTipoLei(r.alvo_tipo)}${numero}`;
}

/**
 * Agrupa as relações de uma norma em "o que ela faz" (ativas) e "o que fazem com ela"
 * (passivas). Uma relação só é link quando tem `alvo_id` e a confiança não é
 * `nao-resolvida`; as demais aparecem como texto, claramente sem link.
 */
export function agruparRelacoes(
  rows: RelacaoRow[],
  normaId: string,
): { ativas: GrupoRelacao[]; passivas: GrupoRelacao[] } {
  const ativas = new Map<string, ItemRelacao[]>();
  const passivas = new Map<string, ItemRelacao[]>();
  for (const r of rows) {
    if (r.origem_id === normaId) {
      const resolvida = r.alvo_id != null && r.confianca !== 'nao-resolvida';
      const item: ItemRelacao = {
        id: r.relacao_id,
        href: resolvida && r.alvo_id ? leiUrl(r.alvo_id) : null,
        titulo: resolvida && r.alvo_titulo ? r.alvo_titulo : referenciaEscrita(r),
        verbo: r.verbo,
        parcial: r.parcial,
        nota: resolvida
          ? r.confianca === 'ambigua'
            ? notaLegivel(r.nota)
            : null
          : (notaLegivel(r.nota) ?? 'não resolvida'),
        confianca: r.confianca,
        fonteIndice: r.fonte_relacao === 'anotacao-do-indice',
      };
      (ativas.get(r.verbo) ?? ativas.set(r.verbo, []).get(r.verbo)!).push(item);
    } else if (r.alvo_id === normaId && r.confianca !== 'nao-resolvida') {
      const item: ItemRelacao = {
        id: r.relacao_id,
        href: leiUrl(r.origem_id),
        titulo: r.origem_titulo || r.origem_id,
        verbo: r.verbo,
        parcial: r.parcial,
        nota: r.confianca === 'ambigua' ? notaLegivel(r.nota) : null,
        confianca: r.confianca,
        fonteIndice: r.fonte_relacao === 'anotacao-do-indice',
      };
      (passivas.get(r.verbo) ?? passivas.set(r.verbo, []).get(r.verbo)!).push(item);
    }
  }
  const montar = (m: Map<string, ItemRelacao[]>, rotulos: Record<string, string>): GrupoRelacao[] =>
    ORDEM_VERBOS.filter((v) => m.has(v)).map((v) => ({
      rotulo: rotulos[v] ?? v,
      itens: m.get(v) ?? [],
    }));
  return { ativas: montar(ativas, VERBO_ATIVO), passivas: montar(passivas, VERBO_PASSIVO) };
}
