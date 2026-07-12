/**
 * Formatação derivada — rótulos, breadcrumbs, URLs de evidência e estágios.
 *
 * SCHEMA.md §0.1: rótulo ("Art. 1º", "§ 2º", "III") é uma função pura de
 * (tipo, path) aplicada em render-time; nada disso é armazenado no Parquet.
 * O token map espelha `etl.path_to_tipo` (§4.2) — hífen-separado, unidades
 * normativas (art, par, inc, ali, item, anexo, disp-*) e organizacionais
 * (liv, parte, tit, cap, sec, subsec).
 */

// ---------------------------------------------------------------------------
// Base path (GitHub Pages serve sob /leizilla)
// ---------------------------------------------------------------------------

export function withBase(path: string): string {
  const base = (import.meta.env?.BASE_URL ?? '/').replace(/\/$/, '');
  return `${base}/${path.replace(/^\//, '')}`;
}

/** URL estável da página de uma lei (rota client-side via query param). */
export function leiUrl(leiId: string, dispositivoPath?: string): string {
  const hash = dispositivoPath && dispositivoPath !== 'ementa' ? `#${dispositivoPath}` : '';
  return withBase(`lei/?id=${encodeURIComponent(leiId)}`) + hash;
}

// ---------------------------------------------------------------------------
// Internet Archive — evidência e preservação
// ---------------------------------------------------------------------------

export function iaDetailsUrl(iaId: string): string {
  return `https://archive.org/details/${encodeURIComponent(iaId)}`;
}

export function iaFileUrl(iaId: string, file: string): string {
  return `https://archive.org/download/${encodeURIComponent(iaId)}/${file}`;
}

/** Metadados de auditoria do parse (parsed_meta.json do item parsed no IA). */
export function parsedMetaUrl(leiId: string): string {
  return iaFileUrl(leiId, 'parsed_meta.json');
}

/** XML canônico da lei (law.xml do item parsed no IA). */
export function lawXmlUrl(leiId: string): string {
  return iaFileUrl(leiId, 'law.xml');
}

export interface Fonte {
  ia_id: string;
  diverge?: boolean;
  texto_divergente?: string | null;
}

/** A coluna `fontes` é JSON serializado (SCHEMA.md §3.1). Fail-open: [] em erro. */
export function parseFontes(fontes: string | null | undefined): Fonte[] {
  if (!fontes) return [];
  try {
    const parsed = JSON.parse(fontes);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// Labels de tipo de norma e ente
// ---------------------------------------------------------------------------

const TIPO_LEI_LABELS: Record<string, string> = {
  lei: 'Lei Ordinária',
  'lei.complementar': 'Lei Complementar',
  'lei-complementar': 'Lei Complementar',
  lc: 'Lei Complementar',
  decreto: 'Decreto',
  'decreto-lei': 'Decreto-Lei',
  'decreto.lei': 'Decreto-Lei',
  'medida.provisoria': 'Medida Provisória',
  'emenda.constitucional': 'Emenda Constitucional',
  constituicao: 'Constituição',
  resolucao: 'Resolução',
  portaria: 'Portaria',
};

export function formatTipoLei(tipo: string | null | undefined): string {
  if (!tipo) return 'Norma';
  return TIPO_LEI_LABELS[tipo] ?? tipo.replace(/[._-]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

const ENTE_LABELS: Record<string, string> = {
  ro: 'Rondônia',
  sp: 'São Paulo',
  federal: 'Federal',
};

export function formatEnte(ente: string | null | undefined): string {
  if (!ente) return '—';
  return ENTE_LABELS[ente] ?? ente.toUpperCase();
}

/** Título curto de exibição: "Lei Ordinária nº 1.234/2003". */
export function leiTitle(row: {
  tipo_lei: string;
  numero_lei: string | null;
  ano_lei: number | bigint | null;
}): string {
  const tipo = formatTipoLei(row.tipo_lei);
  const numero = row.numero_lei ? `nº ${row.numero_lei}` : 's/nº';
  const ano = row.ano_lei != null ? `/${row.ano_lei}` : '';
  return `${tipo} ${numero}${ano}`;
}

// ---------------------------------------------------------------------------
// Rótulos de dispositivo (derivados do path — SCHEMA.md §4.2)
// ---------------------------------------------------------------------------

function toRoman(n: number): string {
  if (!Number.isFinite(n) || n <= 0 || n >= 4000) return String(n);
  const table: Array<[number, string]> = [
    [1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'], [100, 'C'], [90, 'XC'],
    [50, 'L'], [40, 'XL'], [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I'],
  ];
  let out = '';
  let rest = n;
  for (const [v, s] of table) {
    while (rest >= v) {
      out += s;
      rest -= v;
    }
  }
  return out;
}

/** Convenção legística: 1º–9º ordinais, 10 em diante cardinais. */
function ordinal(n: string): string {
  const num = parseInt(n, 10);
  return num >= 1 && num <= 9 ? `${num}º` : n;
}

export interface PathSegment {
  /** token do path, ex: "art-5" */
  token: string;
  /** tipo derivado, ex: "artigo" */
  tipo: string;
  /** rótulo de exibição, ex: "Art. 5º" */
  rotulo: string;
}

/**
 * Decompõe um path composto ("art-5-par-2-inc-3") em segmentos rotulados.
 * Espelha o walk greedy de `etl.path_to_tipo` (3 tokens, depois 2, depois 1).
 * Fail-open: um trecho não reconhecido vira um segmento literal.
 */
export function pathSegments(path: string): PathSegment[] {
  if (!path) return [];
  if (path === 'ementa') return [{ token: path, tipo: 'ementa', rotulo: 'Ementa' }];
  if (path === 'preambulo') return [{ token: path, tipo: 'preambulo', rotulo: 'Preâmbulo' }];
  if (path === 'titulo-lei') return [{ token: path, tipo: 'titulo-lei', rotulo: 'Título da lei' }];

  const parts = path.split('-');
  const segments: PathSegment[] = [];
  let i = 0;
  while (i < parts.length) {
    const three = parts.slice(i, i + 3).join('-');
    const two = parts.slice(i, i + 2).join('-');
    let m: RegExpMatchArray | null;

    if ((m = three.match(/^art-(\d+)-([a-z])$/))) {
      segments.push({ token: three, tipo: 'artigo', rotulo: `Art. ${ordinal(m[1])}-${m[2].toUpperCase()}` });
      i += 3;
    } else if ((m = three.match(/^disp-transitoria-(\d+)$/))) {
      segments.push({ token: three, tipo: 'disposicao-transitoria', rotulo: `Disposição Transitória ${m[1]}` });
      i += 3;
    } else if ((m = three.match(/^disp-final-(\d+)$/))) {
      segments.push({ token: three, tipo: 'disposicao-final', rotulo: `Disposição Final ${m[1]}` });
      i += 3;
    } else if ((m = two.match(/^art-(\d+)$/))) {
      segments.push({ token: two, tipo: 'artigo', rotulo: `Art. ${ordinal(m[1])}` });
      i += 2;
    } else if ((m = two.match(/^par-(unico|\d+)$/))) {
      segments.push({
        token: two,
        tipo: 'paragrafo',
        rotulo: m[1] === 'unico' ? 'Parágrafo único' : `§ ${ordinal(m[1])}`,
      });
      i += 2;
    } else if ((m = two.match(/^inc-(\d+)$/))) {
      segments.push({ token: two, tipo: 'inciso', rotulo: toRoman(parseInt(m[1], 10)) });
      i += 2;
    } else if ((m = two.match(/^ali-([a-z])$/))) {
      segments.push({ token: two, tipo: 'alinea', rotulo: `${m[1]})` });
      i += 2;
    } else if ((m = two.match(/^item-(\d+)$/))) {
      segments.push({ token: two, tipo: 'item', rotulo: `item ${m[1]}` });
      i += 2;
    } else if ((m = two.match(/^anexo-(\d+)$/))) {
      segments.push({ token: two, tipo: 'anexo', rotulo: `Anexo ${toRoman(parseInt(m[1], 10))}` });
      i += 2;
    } else if ((m = two.match(/^liv-(\d+)$/))) {
      segments.push({ token: two, tipo: 'livro', rotulo: `Livro ${toRoman(parseInt(m[1], 10))}` });
      i += 2;
    } else if ((m = two.match(/^parte-(\d+)$/))) {
      segments.push({ token: two, tipo: 'parte', rotulo: `Parte ${toRoman(parseInt(m[1], 10))}` });
      i += 2;
    } else if ((m = two.match(/^tit-(\d+)$/))) {
      segments.push({ token: two, tipo: 'titulo', rotulo: `Título ${toRoman(parseInt(m[1], 10))}` });
      i += 2;
    } else if ((m = two.match(/^cap-(\d+)$/))) {
      segments.push({ token: two, tipo: 'capitulo', rotulo: `Capítulo ${toRoman(parseInt(m[1], 10))}` });
      i += 2;
    } else if ((m = two.match(/^sec-(\d+)$/))) {
      segments.push({ token: two, tipo: 'secao', rotulo: `Seção ${toRoman(parseInt(m[1], 10))}` });
      i += 2;
    } else if ((m = two.match(/^subsec-(\d+)$/))) {
      segments.push({ token: two, tipo: 'subsecao', rotulo: `Subseção ${toRoman(parseInt(m[1], 10))}` });
      i += 2;
    } else {
      // Trecho não reconhecido — preserva literal (fail-open)
      segments.push({ token: parts[i], tipo: 'desconhecido', rotulo: parts[i] });
      i += 1;
    }
  }
  return segments;
}

/** Rótulo do próprio dispositivo (último segmento): "art-5-par-2" → "§ 2º". */
export function rotulo(path: string): string {
  const segs = pathSegments(path);
  return segs.length ? segs[segs.length - 1].rotulo : path;
}

/** Caminho completo legível: "art-5-par-2-inc-3" → "Art. 5º › § 2º › III". */
export function breadcrumb(path: string): string {
  return pathSegments(path)
    .map((s) => s.rotulo)
    .join(' › ');
}

// ---------------------------------------------------------------------------
// Estágios do funil (PRD §6): S1 arquivar → S2 identificar → S3 texto →
// S4 estruturar → S5 temporal. Tudo que está no Parquet `versoes` alcançou S4.
// ---------------------------------------------------------------------------

export interface Stage {
  id: 'S1' | 'S2' | 'S3' | 'S4' | 'S5';
  label: string;
  description: string;
}

export const STAGES: Stage[] = [
  {
    id: 'S1',
    label: 'Arquivado',
    description: 'O documento original foi preservado no Internet Archive, com hash de conteúdo e deduplicação.',
  },
  {
    id: 'S2',
    label: 'Identificado',
    description: 'A identidade (tipo, número, ano) foi extraída do contexto de descoberta; a norma entra no catálogo navegável.',
  },
  {
    id: 'S3',
    label: 'Com texto',
    description: 'Texto extraído via OCR do Internet Archive ou HTML nativo — habilita busca textual e leitura sem PDF.',
  },
  {
    id: 'S4',
    label: 'Estruturado',
    description: 'Leizilla XML validado: dispositivos, linha do tempo de versões e proveniência por fonte. É o que está neste dataset.',
  },
  {
    id: 'S5',
    label: 'Consolidação temporal',
    description: 'Alterações entre normas resolvidas como log imutável de eventos. Fora do MVP — ainda não implementado.',
  },
];

// ---------------------------------------------------------------------------
// Datas e citação
// ---------------------------------------------------------------------------

export function formatDate(
  value: string | Date | number | bigint | null | undefined,
): string {
  if (value == null) return '—';
  let d: Date;
  if (value instanceof Date) {
    d = value;
  } else if (typeof value === 'number' || typeof value === 'bigint') {
    // Colunas DATE do Arrow podem chegar como epoch-millis numéricos.
    d = new Date(Number(value));
  } else {
    d = new Date(`${value}`.slice(0, 10) + 'T00:00:00Z');
  }
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString('pt-BR', { timeZone: 'UTC' });
}

/**
 * Citação estável de um dispositivo: identidade da norma + caminho legível +
 * URN-LEX (quando disponível) + URL profunda da página da lei.
 */
export function citation(
  row: {
    ente: string;
    tipo_lei: string;
    numero_lei: string | null;
    ano_lei: number | bigint | null;
    dispositivo_path: string;
    urn_dispositivo?: string | null;
    lei_id: string;
  },
  // Usa a origem real do navegador (funciona em mirrors/self-host/preview);
  // cai para o domínio canônico só quando não há `location` (ex.: testes em Node).
  origin: string = typeof location !== 'undefined' ? location.origin : 'https://franklinbaldo.github.io',
): string {
  const parts = [`${formatEnte(row.ente)}. ${leiTitle(row)}`];
  if (row.dispositivo_path && row.dispositivo_path !== 'ementa') {
    parts.push(breadcrumb(row.dispositivo_path));
  }
  const url = new URL(leiUrl(row.lei_id, row.dispositivo_path), origin);
  parts.push(`Leizilla, ${url.href}`);
  if (row.urn_dispositivo) parts.push(row.urn_dispositivo);
  return parts.join('. ');
}
