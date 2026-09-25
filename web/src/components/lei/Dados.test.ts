/**
 * Fixture de renderização do componente Dados.svelte — issue #167 criterio 3 /
 * kr-public-semantic-legibility (docs/okf/project-dag.md). Ver Versoes.test.ts
 * para o contexto completo do "canonical UI fixture" e por que ele existe.
 *
 * Achado principal deste arquivo: Dados.svelte NÃO renderiza `inicio_tipo`,
 * `inicio_fontes` nem qualquer rótulo de proveniência de vigência — ele lista
 * downloads, links do dataset completo e o URN-LEX da norma. O rótulo
 * "vigência desde a publicação" que #167 sinaliza só existe em Versoes.svelte
 * (linha do tempo por dispositivo); a preocupação do issue não se aplica a este
 * componente. Estes testes documentam isso, para que #167 não seja fechado
 * assumindo incorretamente que Dados.svelte também precisaria de uma mudança de
 * texto.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mount, unmount } from 'svelte';
import type { LeiRow } from '../../lib/db';
import Dados from './Dados.svelte';

function makeRow(overrides: Partial<LeiRow> = {}): LeiRow {
  return {
    lei_id: 'leizilla-ro-lei-00001-2000',
    ente: 'ro',
    tipo_lei: 'lei',
    numero_lei: '1',
    ano_lei: 2000,
    data_ato: '2000-01-01',
    urn_lex_lei: 'urn:lex:br:estado.rondonia:lei:2000-01-01;1',
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
    // Deliberadamente a variante legada-sem-evidência de #167 — se Dados.svelte
    // tivesse qualquer rótulo de inicio_tipo, este seria o caso a pegar.
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

describe('Dados.svelte — escopo de #167 criterio 3', () => {
  let cleanup: (() => void) | null = null;

  afterEach(() => {
    cleanup?.();
    cleanup = null;
    vi.unstubAllGlobals();
  });

  it('não renderiza inicio_tipo, "publicação" nem "evidência" — o rótulo de #167 não existe aqui', () => {
    // ReleaseCitation (filho) chama fetch() num $effect; sem stub isso seria uma
    // chamada de rede real ao Internet Archive durante o teste (o repo mantém
    // testes offline/determinísticos — CLAUDE.md). Fail-open por design (db.ts
    // fetchLatestPointer): uma rejeição aqui só faz ReleaseCitation cair na
    // citação genérica, não falha o teste.
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('rede desabilitada no teste')));

    const rows = [makeRow()];
    const target = document.createElement('div');
    document.body.appendChild(target);
    const app = mount(Dados, { target, props: { rows, leiId: rows[0].lei_id } });
    cleanup = () => unmount(app);

    const text = target.textContent ?? '';
    expect(text).not.toContain('inicio_tipo');
    expect(text).not.toContain('vigência desde a publicação');
    expect(text).not.toContain('vigência desde a data do ato');
    expect(text).not.toContain('evidência');
    // O que ele de fato mostra: contagem de linhas, downloads e o URN-LEX.
    expect(text).toContain('1 linha');
    expect(text).toContain(rows[0].urn_lex_lei);
  });
});
