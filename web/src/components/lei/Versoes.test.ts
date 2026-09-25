/**
 * Fixture de renderização do componente Versoes.svelte — issue #167 criterio 3
 * / kr-public-semantic-legibility (docs/okf/project-dag.md).
 *
 * Uma captura visual ao vivo de /lei/ está bloqueada por browser-read-cors-integrity
 * (o Internet Archive não envia CORS para .parquet, então o DuckDB-WASM real não
 * carrega em navegador). Este arquivo é o "canonical UI fixture" que o próprio DAG
 * apontou como caminho de retomada: monta o componente de verdade (Svelte 5
 * `mount`/`unmount`, jsdom) contra linhas sintéticas representativas — o mesmo
 * padrão de model.test.ts, mas exercitando o componente em vez das funções puras.
 *
 * Pergunta que este arquivo responde: o rótulo de `inicio_tipo === 'data-publicacao'`
 * ("vigência desde a publicação") lê como categórico/definitivo mesmo quando não há
 * `inicio_fontes` (evidência) por trás dele — o caso legado que motivou #167?
 */
import { afterEach, describe, expect, it } from 'vitest';
import { mount, unmount } from 'svelte';
import type { LeiRow } from '../../lib/db';
import Versoes from './Versoes.svelte';

function makeRow(overrides: Partial<LeiRow> = {}): LeiRow {
  return {
    lei_id: 'leizilla-ro-lei-00001-2000',
    ente: 'ro',
    tipo_lei: 'lei',
    numero_lei: '1',
    ano_lei: 2000,
    data_ato: '2000-01-01',
    urn_lex_lei: null,
    vigente_em: null,
    lei_revogada: false,
    lei_revogada_em: null,
    lei_revogada_por: null,
    lei_revogada_tipo: null,
    dispositivo_path: 'art-1',
    dispositivo_tipo: 'artigo',
    dispositivo_ordem: 1,
    dispositivo_parent_path: null,
    dispositivo_revogado: false,
    dispositivo_revogado_em: null,
    dispositivo_revogado_por: null,
    dispositivo_revogado_tipo: null,
    urn_dispositivo: null,
    versao_id: 'v1',
    em: '2000-01-01',
    ate: null,
    alterado_por: null,
    inicio_tipo: 'data-publicacao',
    inicio_fontes: null,
    fontes: null,
    num_fontes: 0,
    tem_divergencia: false,
    hash_texto: null,
    texto: 'texto',
    texto_normalizado: 'texto',
    ...overrides,
  };
}

// Cada linha é a única versão de um dispositivo distinto, mas com `alterado_por`
// preenchido — groupHistorico() (model.ts) só inclui um dispositivo na linha do
// tempo quando `versions.length > 1 || v.ate != null || v.alterado_por != null`
// (SCHEMA.md §3.1 grain dispositivo×versão); sem isso, a linha nem apareceria em
// Versoes.svelte e não haveria rótulo `inicio_tipo` algum para observar.

/** art-1 — a alegação forte: data do ato, extraída da URN (default, sem prova de publicação exigida). */
const dataAtoRow = makeRow({
  dispositivo_path: 'art-1',
  dispositivo_ordem: 1,
  versao_id: 'v1',
  em: '2020-01-01',
  ate: null,
  alterado_por: 'leizilla-ro-lei-00002-2021',
  inicio_tipo: 'data-ato',
  inicio_fontes: null,
});

/** art-2 — data-publicacao com evidência (PR #230): publicação comprovada por fonte no IA. */
const dataPublicacaoComEvidenciaRow = makeRow({
  dispositivo_path: 'art-2',
  dispositivo_ordem: 2,
  versao_id: 'v1',
  em: '2019-06-01',
  ate: null,
  alterado_por: 'leizilla-ro-lei-00003-2022',
  inicio_tipo: 'data-publicacao',
  inicio_fontes: JSON.stringify([{ ia_id: 'leizilla-raw-ro-casacivil-lei-00042' }]),
});

/**
 * art-3 — data-publicacao SEM evidência: a linha legada que #167 sinaliza. Antes
 * do fix histórico (PR #228), o ETL podia atribuir `data-publicacao` como default
 * silencioso em `<inicio>` malformado, sem nenhuma `<fonte>` comprovando a
 * alegação — SCHEMA.md §4.4 diz que isso "nunca é o default inferido da URN", mas
 * uma linha assim pode existir no dataset de qualquer forma (dado legado, ou um
 * XML mal-formado futuro que escape o consistency checker).
 */
const dataPublicacaoLegadaSemEvidenciaRow = makeRow({
  dispositivo_path: 'art-3',
  dispositivo_ordem: 3,
  versao_id: 'v1',
  em: '2015-03-01',
  ate: null,
  alterado_por: 'leizilla-ro-lei-00004-2016',
  inicio_tipo: 'data-publicacao',
  inicio_fontes: null,
});

function renderVersoes(rows: LeiRow[]) {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const app = mount(Versoes, { target, props: { rows } });
  return { target, app };
}

describe('Versoes.svelte — rótulo de inicio_tipo (issue #167 criterio 3)', () => {
  let cleanup: (() => void) | null = null;

  afterEach(() => {
    cleanup?.();
    cleanup = null;
  });

  it('renderiza uma seção de histórico por dispositivo, uma por linha fornecida', () => {
    const { target, app } = renderVersoes([
      dataAtoRow,
      dataPublicacaoComEvidenciaRow,
      dataPublicacaoLegadaSemEvidenciaRow,
    ]);
    cleanup = () => unmount(app);

    const sections = target.querySelectorAll('section.historico');
    expect(sections).toHaveLength(3);
  });

  it('data-ato: rótulo forte, sem link de evidência e sem aviso de "sem evidência"', () => {
    const { target, app } = renderVersoes([dataAtoRow]);
    cleanup = () => unmount(app);

    const li = target.querySelector('section.historico li') as HTMLElement;
    expect(li.textContent).toContain('vigência desde a data do ato');
    expect(li.querySelector('a')).toBeNull();
    expect(li.textContent).not.toContain('evidência');
  });

  it('data-publicacao COM inicio_fontes: mesmo texto-base do rótulo, mas com link de evidência para o IA', () => {
    const { target, app } = renderVersoes([dataPublicacaoComEvidenciaRow]);
    cleanup = () => unmount(app);

    const li = target.querySelector('section.historico li') as HTMLElement;
    expect(li.textContent).toContain('vigência desde a publicação');
    expect(li.textContent).toContain('(evidência:');

    const link = li.querySelector('a');
    expect(link).not.toBeNull();
    expect(link?.getAttribute('href')).toBe(
      'https://archive.org/details/leizilla-raw-ro-casacivil-lei-00042',
    );
    // não é a variante "legado sem evidência"
    expect(li.textContent).not.toContain('sem evidência registrada');
  });

  it('data-publicacao SEM inicio_fontes (linha legada): o MESMO texto-base do rótulo aparece, ' +
    'sem nenhum link — a alegação categórica não muda com a ausência de prova', () => {
    const { target, app } = renderVersoes([dataPublicacaoLegadaSemEvidenciaRow]);
    cleanup = () => unmount(app);

    const li = target.querySelector('section.historico li') as HTMLElement;
    // Achado central de #167: o rótulo-base é idêntico ao caso evidenciado acima —
    // "vigência desde a publicação" não se qualifica sozinho.
    expect(li.textContent).toContain('vigência desde a publicação');
    expect(li.querySelector('a')).toBeNull();

    // Fix aplicado nesta mudança: a ausência de prova agora é explícita, não
    // silenciosa — sem isto, esta seção seria textualmente idêntica (exceto pelo
    // link) à do caso comprovado, exatamente a ambiguidade que #167 sinalizou.
    expect(li.textContent).toContain('(sem evidência registrada no dataset)');
    expect(li.querySelector('.inicio-sem-evidencia')).not.toBeNull();
  });

  it('caracterização direta: o texto-base do rótulo de data-publicacao é idêntico com e sem evidência ' +
    '— só o aviso extra distingue os dois casos', () => {
    const comEvidencia = renderVersoes([dataPublicacaoComEvidenciaRow]);
    const semEvidencia = renderVersoes([dataPublicacaoLegadaSemEvidenciaRow]);
    cleanup = () => {
      unmount(comEvidencia.app);
      unmount(semEvidencia.app);
    };

    const spanComEvidencia = comEvidencia.target.querySelector('.inicio') as HTMLElement;
    const spanSemEvidencia = semEvidencia.target.querySelector('.inicio') as HTMLElement;
    expect(spanComEvidencia.textContent).toBe(spanSemEvidencia.textContent);
    expect(spanComEvidencia.textContent).toBe('— vigência desde a publicação');
  });

  it('sem histórico (dispositivo único, sem ate/alterado_por): mostra o aviso de "nenhum" em vez de qualquer rótulo', () => {
    const rowSemHistorico = makeRow({
      dispositivo_path: 'art-9',
      ate: null,
      alterado_por: null,
      inicio_tipo: 'data-publicacao',
    });
    const { target, app } = renderVersoes([rowSemHistorico]);
    cleanup = () => unmount(app);

    expect(target.querySelectorAll('section.historico')).toHaveLength(0);
    expect(target.textContent).toContain('Nenhum dispositivo desta norma tem mais de uma versão');
  });
});
