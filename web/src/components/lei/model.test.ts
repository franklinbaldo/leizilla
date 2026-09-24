import { afterEach, describe, expect, it, vi } from 'vitest';
import type { LeiRow } from '../../lib/db';
import {
  absoluteLeiUrl,
  aggregateFontes,
  buildTree,
  copyText,
  currentRows,
  downloadBlob,
  groupHistorico,
  rowsToCsv,
  rowsToJson,
} from './model';

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
    fontes: null,
    num_fontes: 0,
    tem_divergencia: false,
    hash_texto: null,
    texto: 'texto',
    texto_normalizado: 'texto',
    ...overrides,
  };
}

describe('currentRows', () => {
  it('keeps the single version of a dispositivo unchanged', () => {
    const rows = [makeRow({ versao_id: 'v1' })];
    expect(currentRows(rows).map((r) => r.versao_id)).toEqual(['v1']);
  });

  it('picks the vigente (ate == null) version over a superseded one', () => {
    const rows = [
      makeRow({ versao_id: 'v1', em: '2000-01-01', ate: '2010-01-01' }),
      makeRow({ versao_id: 'v2', em: '2010-01-01', ate: null }),
    ];
    expect(currentRows(rows).map((r) => r.versao_id)).toEqual(['v2']);
  });

  it('keeps the latest redação when a dispositivo is entirely revoked (all versions have ate)', () => {
    const rows = [
      makeRow({ versao_id: 'v1', em: '2000-01-01', ate: '2010-01-01' }),
      makeRow({ versao_id: 'v2', em: '2010-01-01', ate: '2020-01-01' }),
    ];
    expect(currentRows(rows).map((r) => r.versao_id)).toEqual(['v2']);
  });

  it('is order-independent (out-of-order input rows)', () => {
    const rows = [
      makeRow({ versao_id: 'v2', em: '2010-01-01', ate: null }),
      makeRow({ versao_id: 'v1', em: '2000-01-01', ate: '2010-01-01' }),
    ];
    expect(currentRows(rows).map((r) => r.versao_id)).toEqual(['v2']);
  });

  it('breaks a tie between two open (ate == null) versions with the same `em` by keeping the later-processed row', () => {
    const rows = [
      makeRow({ versao_id: 'v1', em: '2000-01-01', ate: null }),
      makeRow({ versao_id: 'v2', em: '2000-01-01', ate: null }),
    ];
    expect(currentRows(rows).map((r) => r.versao_id)).toEqual(['v2']);
  });
});

describe('buildTree', () => {
  it('nests artigo > parágrafo > inciso > alínea by dispositivo_parent_path', () => {
    const rows = [
      makeRow({ dispositivo_path: 'art-1', dispositivo_parent_path: null, dispositivo_ordem: 1 }),
      makeRow({
        dispositivo_path: 'art-1-par-1',
        dispositivo_parent_path: 'art-1',
        dispositivo_ordem: 2,
      }),
      makeRow({
        dispositivo_path: 'art-1-par-1-inc-1',
        dispositivo_parent_path: 'art-1-par-1',
        dispositivo_ordem: 3,
      }),
      makeRow({
        dispositivo_path: 'art-1-par-1-inc-1-ali-a',
        dispositivo_parent_path: 'art-1-par-1-inc-1',
        dispositivo_ordem: 4,
      }),
    ];
    const { roots } = buildTree(rows);
    expect(roots).toHaveLength(1);
    expect(roots[0].row.dispositivo_path).toBe('art-1');
    expect(roots[0].children[0].row.dispositivo_path).toBe('art-1-par-1');
    expect(roots[0].children[0].children[0].row.dispositivo_path).toBe('art-1-par-1-inc-1');
    expect(roots[0].children[0].children[0].children[0].row.dispositivo_path).toBe(
      'art-1-par-1-inc-1-ali-a',
    );
  });

  it('groups organizacional blocks (capítulo) with their child artigos', () => {
    const rows = [
      makeRow({
        dispositivo_path: 'cap-1',
        dispositivo_tipo: 'capitulo',
        dispositivo_parent_path: null,
        dispositivo_ordem: 1,
      }),
      makeRow({ dispositivo_path: 'art-1', dispositivo_parent_path: 'cap-1', dispositivo_ordem: 2 }),
    ];
    const { roots } = buildTree(rows);
    expect(roots).toHaveLength(1);
    expect(roots[0].row.dispositivo_tipo).toBe('capitulo');
    expect(roots[0].children.map((c) => c.row.dispositivo_path)).toEqual(['art-1']);
  });

  it('fails open by promoting to top-level when dispositivo_parent_path points nowhere in the set', () => {
    const rows = [
      makeRow({ dispositivo_path: 'art-1', dispositivo_parent_path: 'cap-inexistente', dispositivo_ordem: 1 }),
    ];
    const { roots } = buildTree(rows);
    expect(roots.map((r) => r.row.dispositivo_path)).toEqual(['art-1']);
  });

  it('orders siblings by dispositivo_ordem, not input order', () => {
    const rows = [
      makeRow({ dispositivo_path: 'art-2', dispositivo_ordem: 2 }),
      makeRow({ dispositivo_path: 'art-1', dispositivo_ordem: 1 }),
    ];
    const { roots } = buildTree(rows);
    expect(roots.map((r) => r.row.dispositivo_path)).toEqual(['art-1', 'art-2']);
  });

  it('returns the ementa separately, excluded from the tree', () => {
    const rows = [
      makeRow({ dispositivo_path: 'ementa', dispositivo_ordem: 0 }),
      makeRow({ dispositivo_path: 'art-1', dispositivo_ordem: 1 }),
    ];
    const { ementa, roots } = buildTree(rows);
    expect(ementa?.dispositivo_path).toBe('ementa');
    expect(roots.map((r) => r.row.dispositivo_path)).toEqual(['art-1']);
  });
});

describe('groupHistorico', () => {
  it('excludes a dispositivo with a single, still-open version (no history)', () => {
    const rows = [makeRow({ dispositivo_path: 'art-1', ate: null })];
    expect(groupHistorico(rows)).toEqual([]);
  });

  it('includes a dispositivo with multiple versions, sorted chronologically', () => {
    const rows = [
      makeRow({ dispositivo_path: 'art-1', versao_id: 'v2', em: '2010-01-01', ate: null }),
      makeRow({ dispositivo_path: 'art-1', versao_id: 'v1', em: '2000-01-01', ate: '2010-01-01' }),
    ];
    const groups = groupHistorico(rows);
    expect(groups).toHaveLength(1);
    expect(groups[0].versions.map((v) => v.versao_id)).toEqual(['v1', 'v2']);
  });

  it('includes a single-version dispositivo that was revoked (has `ate` or `alterado_por`)', () => {
    const rows = [makeRow({ dispositivo_path: 'art-1', ate: '2020-01-01' })];
    expect(groupHistorico(rows)).toHaveLength(1);
  });
});

describe('aggregateFontes', () => {
  it('deduplicates sources by ia_id and collects distinct divergent texts, sorted by ia_id', () => {
    const rows = [
      makeRow({
        fontes: JSON.stringify([
          { ia_id: 'b', diverge: true, texto_divergente: 'redação B' },
        ]),
      }),
      makeRow({
        fontes: JSON.stringify([
          { ia_id: 'a', diverge: false },
          { ia_id: 'b', diverge: true, texto_divergente: 'redação B' },
        ]),
      }),
    ];
    const agg = aggregateFontes(rows);
    expect(agg.map((a) => a.ia_id)).toEqual(['a', 'b']);
    expect(agg[1].diverge).toBe(true);
    expect(agg[1].textos_divergentes).toEqual(['redação B']);
  });
});

describe('absoluteLeiUrl', () => {
  it('resolves against location.origin (jsdom-provided)', () => {
    expect(absoluteLeiUrl('leizilla-ro-lei-00001-2000')).toContain(
      '/lei/?id=leizilla-ro-lei-00001-2000',
    );
  });
});

describe('rowsToCsv / rowsToJson', () => {
  it('escapes commas, quotes and newlines in CSV fields', () => {
    const rows = [makeRow({ texto: 'linha "citada", com vírgula\ne quebra' })];
    const csv = rowsToCsv(rows);
    expect(csv).toContain('"linha ""citada"", com vírgula\ne quebra"');
  });

  it('serializes date columns as ISO and bigint as number in both formats', () => {
    const rows = [makeRow({ ano_lei: 2000n as unknown as number, data_ato: new Date(Date.UTC(2000, 0, 1)) })];
    const csv = rowsToCsv(rows);
    const json = JSON.parse(rowsToJson(rows));
    expect(csv).toContain('2000-01-01');
    expect(json[0].data_ato).toBe('2000-01-01');
    expect(json[0].ano_lei).toBe(2000);
  });
});

describe('copyText', () => {
  // jsdom does not implement document.execCommand at all, so vi.spyOn (which
  // requires an existing method) can't be used here — assign/delete directly.
  function stubExecCommand(impl: (cmd: string) => boolean): ReturnType<typeof vi.fn> {
    const fn = vi.fn(impl);
    (document as unknown as { execCommand: typeof fn }).execCommand = fn;
    return fn;
  }

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    delete (document as unknown as { execCommand?: unknown }).execCommand;
  });

  it('uses navigator.clipboard.writeText when available and succeeds', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText } });

    const ok = await copyText('olá mundo');

    expect(ok).toBe(true);
    expect(writeText).toHaveBeenCalledWith('olá mundo');
  });

  it('falls back to execCommand when clipboard.writeText throws', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('denied'));
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    const execCommand = stubExecCommand(() => true);

    const ok = await copyText('via fallback');

    expect(ok).toBe(true);
    expect(execCommand).toHaveBeenCalledWith('copy');
    // the temporary textarea must not leak into the document
    expect(document.querySelector('textarea')).toBeNull();
  });

  it('falls back to execCommand when navigator.clipboard is absent', async () => {
    vi.stubGlobal('navigator', {});
    const execCommand = stubExecCommand(() => true);

    const ok = await copyText('sem clipboard API');

    expect(ok).toBe(true);
    expect(execCommand).toHaveBeenCalledWith('copy');
  });

  it('returns false when both clipboard and execCommand fail', async () => {
    vi.stubGlobal('navigator', {});
    stubExecCommand(() => false);

    expect(await copyText('sem sorte')).toBe(false);
  });

  it('returns false when execCommand throws', async () => {
    vi.stubGlobal('navigator', {});
    stubExecCommand(() => {
      throw new Error('not supported');
    });

    expect(await copyText('erro')).toBe(false);
  });
});

describe('downloadBlob', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('creates an anchor with the right href/download, clicks it, then revokes the URL', () => {
    const createObjectURL = vi.fn().mockReturnValue('blob:mock-url');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL });

    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    downloadBlob('versoes.csv', 'a,b\n1,2\n', 'text/csv');

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-url');
    // the temporary anchor must not leak into the document
    expect(document.querySelector('a[download="versoes.csv"]')).toBeNull();
  });

  it('names the blob content with the given mime type', () => {
    let capturedBlob: Blob | undefined;
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn((blob: Blob) => {
        capturedBlob = blob;
        return 'blob:mock-url';
      }),
      revokeObjectURL: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    downloadBlob('versoes.json', '{}', 'application/json');

    expect(capturedBlob?.type).toBe('application/json');
  });
});
