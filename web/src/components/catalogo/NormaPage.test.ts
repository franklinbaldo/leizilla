/**
 * Decisão entre "texto" e "ainda não há texto" em NormaPage.svelte (/lei/?id=leizilla-raw-…).
 * Os dados do catálogo e da camada de texto são mockados. O catálogo chega já com a camada
 * de texto aplicada (`comTextoDaCamada` em catalogoDb.ts): `legivel` vem do `textos`, não
 * do catálogo gerado antes da linha existir.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import * as catalogoDb from '../../lib/catalogoDb';
import * as db from '../../lib/db';
import type { TextoRow } from '../../lib/db';
import type { CatalogoRow } from '../../lib/catalogo';
import NormaPage from './NormaPage.svelte';

vi.mock('../../lib/db', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/db')>()),
  getTexto: vi.fn(),
  getStructuredLeiId: vi.fn(async () => null),
}));
vi.mock('../../lib/catalogoDb', () => ({
  catalogoAvailable: vi.fn(async () => true),
  getNormaCatalogo: vi.fn(),
  getRelacoes: vi.fn(async () => []),
  relacoesAvailable: vi.fn(async () => false),
}));

const ID = 'leizilla-raw-ro-casacivil-decreto-32251';

function makeCatalogo(overrides: Partial<CatalogoRow> = {}): CatalogoRow {
  return {
    norma_id: ID,
    tipo: 'decreto',
    numero: 32251,
    sufixo: '',
    situacao: 'listada',
    titulo: 'Decreto nº 32.251',
    data: '2026-01-01',
    ano: 2026,
    ementa: 'Aprova o regulamento.',
    coddoc: null,
    arquivos: '[]',
    preservada: true,
    com_texto: false,
    legivel: false,
    estruturada: false,
    identidade_incerta: false,
    rendicoes: '[]',
    situacao_norma: null,
    situacao_evidencias: '[]',
    url_oficial: null,
    url_ia: 'https://archive.org/download/x/x.pdf',
    link_publico: null,
    ia_item: ID,
    texto_id: ID,
    catalogo_obtido_em: '2026-11-16',
    ...overrides,
  };
}

function makeTexto(): TextoRow {
  return {
    texto_id: ID,
    ente: 'ro',
    fonte: 'casacivil',
    tipo: 'decreto',
    numero: 32251,
    rendicao: null,
    qualidade: 'boa',
    sha256_fonte: 'a'.repeat(64),
    capturado_em: null,
    ia_item: ID,
    pdf_url: 'https://archive.org/download/x/x.pdf',
    texto_url: null,
    ocr_motor: 'kreuzberg+paddleocr (re-OCR direcionado, ADR-0019)',
    ocr_modulo_versao: null,
    ocr_parametros: null,
    ocr_derivado_em: null,
    sha1_texto_ia: null,
    sha256_texto: null,
    num_caracteres: 40,
    artigos_fecham: true,
    artigos_total: 1,
    artigos_ultimo: 1,
    ancoras: null,
    trecho: null,
    texto: 'DECRETO Nº 32.251\n\nArt. 1º Fica aprovado o regulamento.',
  };
}

let target: HTMLElement;
let app: Record<string, unknown> | undefined;

beforeEach(() => {
  target = document.createElement('div');
  document.body.appendChild(target);
});

afterEach(() => {
  if (app) void unmount(app);
  app = undefined;
  target.remove();
  vi.mocked(db.getTexto).mockReset();
  vi.mocked(catalogoDb.getNormaCatalogo).mockReset();
});

async function render() {
  app = mount(NormaPage, { target, props: { normaId: ID } });
  flushSync();
  await vi.waitFor(() => {
    if (target.querySelector('[aria-busy]')) throw new Error('ainda carregando');
    if (!target.textContent?.includes('Dados do índice oficial') && !target.querySelector('h3'))
      throw new Error('ainda sem conteúdo');
  });
}

describe('NormaPage: texto da camada de texto', () => {
  it('mostra o texto quando a camada de texto tem a norma (legivel aplicado do textos)', async () => {
    vi.mocked(catalogoDb.getNormaCatalogo).mockResolvedValue(
      makeCatalogo({ legivel: true, com_texto: true }),
    );
    vi.mocked(db.getTexto).mockResolvedValue(makeTexto());
    await render();

    expect(target.textContent).toContain('Fica aprovado o regulamento');
    expect(target.textContent).not.toContain('Ainda não há texto legível');
    expect(target.textContent).toContain('OCR do próprio Leizilla');
  });

  it('sem linha na camada de texto e sem legivel: diz que ainda não há texto', async () => {
    vi.mocked(catalogoDb.getNormaCatalogo).mockResolvedValue(makeCatalogo({ legivel: false }));
    vi.mocked(db.getTexto).mockResolvedValue(null);
    await render();

    expect(target.textContent).toContain('Ainda não há texto legível publicado para esta norma.');
    expect(target.querySelector('.texto-ocr')).toBeNull();
  });
});
