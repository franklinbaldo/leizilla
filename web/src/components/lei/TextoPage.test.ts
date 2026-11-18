/**
 * Renderização de TextoPage.svelte (camada de texto, ADR-0015) com o DuckDB fora: `getTexto`
 * é mockado. Cobre o caso de uma norma cujo texto é do OCR próprio do Leizilla (ADR-0019),
 * com `texto_url` nulo: o texto aparece, o aviso de origem aparece e o link para o
 * arquivo do Internet Archive some.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import * as db from '../../lib/db';
import type { TextoRow } from '../../lib/db';
import TextoPage from './TextoPage.svelte';

vi.mock('../../lib/db', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/db')>()),
  getTexto: vi.fn(),
  getStructuredLeiId: vi.fn(async () => null),
}));

const ID = 'leizilla-raw-ro-casacivil-decreto-32251';
const KREUZBERG = 'kreuzberg+paddleocr (re-OCR direcionado, ADR-0019)';

function makeRow(overrides: Partial<TextoRow> = {}): TextoRow {
  return {
    texto_id: ID,
    ente: 'ro',
    fonte: 'casacivil',
    tipo: 'decreto',
    numero: 32251,
    rendicao: null,
    qualidade: 'boa',
    sha256_fonte: 'a'.repeat(64),
    capturado_em: '2026-01-01T00:00:00Z',
    ia_item: 'leizilla-raw-ro-casacivil-decreto-32251',
    pdf_url: 'https://archive.org/download/x/x.pdf',
    texto_url: null,
    ocr_motor: KREUZBERG,
    ocr_modulo_versao: null,
    ocr_parametros: null,
    ocr_derivado_em: '2026-11-01T00:00:00Z',
    sha1_texto_ia: null,
    sha256_texto: null,
    num_caracteres: 40,
    artigos_fecham: false,
    artigos_total: 0,
    artigos_ultimo: 0,
    ancoras: null,
    trecho: null,
    texto: 'DECRETO Nº 32.251\n\nArt. 1º Fica aprovado o regulamento.',
    ...overrides,
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
});

async function render(props: { textoId: string; embedded?: boolean }) {
  app = mount(TextoPage, { target, props });
  flushSync();
  await vi.waitFor(() => {
    if (target.querySelector('[aria-busy]')) throw new Error('ainda carregando');
  });
}

describe('TextoPage com texto_url nulo', () => {
  it('mostra o texto da camada mesmo sem arquivo no Internet Archive', async () => {
    vi.mocked(db.getTexto).mockResolvedValue(makeRow());
    await render({ textoId: ID, embedded: true });

    expect(target.querySelector('.texto-ocr')?.textContent).toContain('Fica aprovado o regulamento');
    expect(target.textContent).not.toContain('Ainda não');
    expect(target.textContent).not.toContain('Texto não encontrado');
  });

  it('não mostra o link "arquivo de texto" do Internet Archive', async () => {
    vi.mocked(db.getTexto).mockResolvedValue(makeRow({ texto_url: null }));
    await render({ textoId: ID, embedded: true });

    expect(target.textContent).not.toContain('arquivo de texto');
    expect(target.querySelector('a[href*="_djvu"]')).toBeNull();
  });

  it('diz que o texto é do OCR próprio do Leizilla quando o motor é kreuzberg', async () => {
    vi.mocked(db.getTexto).mockResolvedValue(makeRow());
    await render({ textoId: ID, embedded: true });

    const aviso = (target.querySelector('.aviso')?.textContent ?? '').replace(/\s+/g, ' ');
    expect(aviso).toContain('OCR do próprio Leizilla');
    expect(aviso).toContain('o Internet Archive ainda não tem texto deste documento');
  });

  it('não diz isso para um texto do OCR do Internet Archive', async () => {
    vi.mocked(db.getTexto).mockResolvedValue(
      makeRow({ ocr_motor: 'tesseract', texto_url: 'https://archive.org/download/x/x_djvu.txt' }),
    );
    await render({ textoId: ID, embedded: true });

    expect(target.textContent).not.toContain('OCR do próprio Leizilla');
    expect(target.textContent).toContain('arquivo de texto');
  });
});

describe('TextoPage com mais de uma rendição (ADR-0015, adendo 2026-11-18)', () => {
  const OUTRA = JSON.stringify([
    {
      rendicao: 'original',
      sha256: 'b'.repeat(64),
      capturado_em: '2026-06-01T00:00:00Z',
      pdf_url: 'https://archive.org/download/x/orig.pdf',
      texto_url: 'https://archive.org/download/x/orig_djvu.txt',
    },
  ]);

  it('mostra o texto compilado como versão publicada pela Casa Civil, com a data, e liga ao original', async () => {
    vi.mocked(db.getTexto).mockResolvedValue(
      makeRow({ rendicao: 'compilada', ocr_motor: 'tesseract', outras_rendicoes: OUTRA }),
    );
    await render({ textoId: ID, embedded: true });

    const aviso = (target.querySelector('.aviso')?.textContent ?? '').replace(/\s+/g, ' ');
    expect(target.querySelector('.selo-rendicao')?.textContent).toBe('texto compilado');
    expect(aviso).toContain('versão compilada publicada pela Casa Civil');
    expect(aviso).toContain('capturada em');
    expect(aviso).toContain('Não é uma consolidação feita ou conferida pelo Leizilla');
    const outras = target.querySelector('[data-testid="outras-rendicoes"]');
    expect(outras?.textContent).toContain('PDF do texto original');
    expect(outras?.querySelector('a[href$="orig.pdf"]')).not.toBeNull();
    expect(outras?.querySelector('a[href$="orig_djvu.txt"]')).not.toBeNull();
  });

  it('norma só com o original: rótulo "texto original" e nenhum link extra', async () => {
    vi.mocked(db.getTexto).mockResolvedValue(makeRow({ rendicao: 'original', ocr_motor: 'tesseract' }));
    await render({ textoId: ID, embedded: true });

    expect(target.querySelector('.selo-rendicao')?.textContent).toBe('texto original');
    expect(target.textContent).not.toContain('versão compilada');
    expect(target.querySelector('[data-testid="outras-rendicoes"]')).toBeNull();
  });

  it('linha de textos.parquet antigo (sem rendicao nem outras_rendicoes) segue como original', async () => {
    vi.mocked(db.getTexto).mockResolvedValue(makeRow({ rendicao: null, ocr_motor: 'tesseract' }));
    await render({ textoId: ID, embedded: true });

    expect(target.querySelector('.selo-rendicao')?.textContent).toBe('texto original');
  });

  it('JSON malformado em outras_rendicoes não quebra a página', async () => {
    vi.mocked(db.getTexto).mockResolvedValue(makeRow({ outras_rendicoes: '{nope' }));
    await render({ textoId: ID, embedded: true });

    expect(target.querySelector('[data-testid="outras-rendicoes"]')).toBeNull();
    expect(target.querySelector('.texto-ocr')).not.toBeNull();
  });
});

describe('TextoPage sem linha na camada de texto', () => {
  it('embutida, diz que o texto ainda não foi publicado', async () => {
    vi.mocked(db.getTexto).mockResolvedValue(null);
    await render({ textoId: ID, embedded: true });

    expect(target.textContent).toContain('ainda não foi publicado na camada de texto');
  });
});
