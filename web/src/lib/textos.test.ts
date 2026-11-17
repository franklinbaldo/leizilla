import { describe, expect, it } from 'vitest';
import { buildTextoWhere, isTextoId, numeroFromTerm } from './db';
import {
  ancoraId,
  ancoraRotulo,
  ocrEhProprio,
  paragrafos,
  parseAncoras,
  segmentar,
  type Ancora,
} from './textos';

describe('ocrEhProprio', () => {
  it('reconhece o re-OCR do próprio Leizilla (kreuzberg)', () => {
    expect(ocrEhProprio('kreuzberg+paddleocr (re-OCR direcionado, ADR-0019)')).toBe(true);
  });

  it('não confunde com o OCR do Internet Archive nem com motor ausente', () => {
    expect(ocrEhProprio('tesseract')).toBe(false);
    expect(ocrEhProprio('abbyy')).toBe(false);
    expect(ocrEhProprio(null)).toBe(false);
    expect(ocrEhProprio(undefined)).toBe(false);
  });
});

const TEXTO = 'LEI N. 7\n\nArt. 1º Fica criada.\nArt. 22 Mantida.\nArt. 3º Vigora.\n';
const at = (needle: string) => {
  const ini = TEXTO.indexOf(needle);
  return { ini, fim: ini + needle.length };
};
const ANCORAS: Ancora[] = [
  { n: 1, sufixo: null, ...at('Art. 1º') },
  { n: 2, sufixo: null, ...at('Art. 22') },
  { n: 3, sufixo: null, ...at('Art. 3º') },
];

describe('parseAncoras', () => {
  it('reads the JSON column', () => {
    expect(parseAncoras(JSON.stringify(ANCORAS))).toEqual(ANCORAS);
  });

  it('fails open on anything malformed', () => {
    expect(parseAncoras(null)).toEqual([]);
    expect(parseAncoras('{')).toEqual([]);
    expect(parseAncoras('{"n":1}')).toEqual([]);
    expect(parseAncoras('[{"n":"1","ini":0,"fim":2}]')).toEqual([]);
  });
});

describe('ancoraId / ancoraRotulo', () => {
  it('follows the structured path and label conventions', () => {
    expect(ancoraId({ n: 4, sufixo: null })).toBe('art-4');
    expect(ancoraId({ n: 8, sufixo: 'A' })).toBe('art-8-a');
    expect(ancoraRotulo({ n: 4, sufixo: null })).toBe('Art. 4º');
    expect(ancoraRotulo({ n: 12, sufixo: null })).toBe('Art. 12');
    expect(ancoraRotulo({ n: 8, sufixo: 'a' })).toBe('Art. 8º-A');
  });
});

describe('segmentar', () => {
  it('never changes the text: segments concatenate back to the original', () => {
    const segs = segmentar(TEXTO, ANCORAS);
    expect(segs.map((s) => s.texto).join('')).toBe(TEXTO);
    expect(segs.map((s) => s.id)).toEqual([null, 'art-1', 'art-2', 'art-3']);
    // O OCR leu "22" onde a sequência lê o art. 2º: o rótulo navega, o texto fica.
    expect(segs[2].rotulo).toBe('Art. 2º');
    expect(segs[2].texto.startsWith('Art. 22 Mantida.')).toBe(true);
  });

  it('returns the whole text when there are no anchors', () => {
    expect(segmentar(TEXTO, [])).toEqual([{ id: null, rotulo: null, texto: TEXTO }]);
  });

  it('refuses to cut on out-of-bounds or out-of-order anchors', () => {
    const whole = [{ id: null, rotulo: null, texto: TEXTO }];
    expect(segmentar(TEXTO, [{ n: 1, sufixo: null, ini: 5, fim: 9999 }])).toEqual(whole);
    expect(segmentar(TEXTO, [ANCORAS[1], ANCORAS[0]])).toEqual(whole);
  });

  it('treats offsets as code points when the text has astral characters', () => {
    const texto = '𝐋ei\nArt. 1º Um.\nArt. 2º Dois.\n';
    const cps = Array.from(texto);
    const cpIndex = (needle: string) => Array.from(texto.slice(0, texto.indexOf(needle))).length;
    const ancoras: Ancora[] = [
      { n: 1, sufixo: null, ini: cpIndex('Art. 1º'), fim: cpIndex('Art. 1º') + 7 },
      { n: 2, sufixo: null, ini: cpIndex('Art. 2º'), fim: cpIndex('Art. 2º') + 7 },
    ];
    expect(cps.length).toBe(texto.length - 1);
    const segs = segmentar(texto, ancoras);
    expect(segs.map((s) => s.texto).join('')).toBe(texto);
    expect(segs[1].texto.startsWith('Art. 1º')).toBe(true);
    expect(segs[2].texto.startsWith('Art. 2º')).toBe(true);
  });

  it('keeps a repeated id readable but not as a second navigation target', () => {
    const dup = [ANCORAS[0], { ...ANCORAS[1], n: 1 }];
    const segs = segmentar(TEXTO, dup);
    expect(segs.map((s) => s.id)).toEqual([null, 'art-1', null]);
    expect(segs.map((s) => s.texto).join('')).toBe(TEXTO);
  });
});

describe('paragrafos', () => {
  it('splits on blank lines without dropping a character', () => {
    const texto = 'GOVERNO\nDO\nESTADO\n\n \nLEI\nN. 7\n\n\nArt. 1º\n';
    const partes = paragrafos(texto);
    expect(partes.join('')).toBe(texto);
    expect(partes).toEqual(['GOVERNO\nDO\nESTADO\n\n \n', 'LEI\nN. 7\n\n\n', 'Art. 1º\n']);
    expect(paragrafos('')).toEqual([]);
    expect(paragrafos('sem quebra')).toEqual(['sem quebra']);
  });
});

describe('text-layer catalog filters', () => {
  it('recognises text-layer ids by the raw prefix', () => {
    expect(isTextoId('leizilla-raw-ro-casacivil-lei-00007')).toBe(true);
    expect(isTextoId('leizilla-ro-lei-00007-1983')).toBe(false);
  });

  it('extracts a norm number from a search term', () => {
    expect(numeroFromTerm('lei 1.234')).toBe(1234);
    expect(numeroFromTerm('57')).toBe(57);
    expect(numeroFromTerm('servidores públicos')).toBeNull();
    expect(numeroFromTerm('0')).toBeNull();
  });

  it('matches text-only norms by number, never by full text', () => {
    expect(buildTextoWhere('lei 57')).toEqual({ where: 'numero = ?', params: [57] });
    expect(buildTextoWhere('servidores').where).toBe('FALSE');
    expect(buildTextoWhere('')).toEqual({ where: 'TRUE', params: [] });
  });

  it('excludes text-only norms from a year filter and applies ente/tipo', () => {
    expect(buildTextoWhere('', { year: 1990 }).where).toBe('FALSE');
    expect(buildTextoWhere('', { ente: 'ro', tipoLei: ['lc', 'lei.complementar'] })).toEqual({
      where: 'ente = ? AND tipo IN (?, ?)',
      params: ['ro', 'lc', 'lei.complementar'],
    });
  });
});
