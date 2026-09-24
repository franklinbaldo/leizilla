import { describe, expect, it } from 'vitest';
import {
  breadcrumb,
  citation,
  formatDate,
  formatEnte,
  formatTipoLei,
  iaDetailsUrl,
  iaFileUrl,
  leiTitle,
  leiUrl,
  parseFontes,
  pathSegments,
  rotulo,
  withBase,
} from './format';

describe('withBase / leiUrl', () => {
  it('joins the base URL and path without doubling slashes', () => {
    expect(withBase('lei/?id=1')).toBe('/lei/?id=1');
    expect(withBase('/lei/?id=1')).toBe('/lei/?id=1');
  });

  it('links to a dispositivo via hash, skipping ementa', () => {
    expect(leiUrl('leizilla-ro-lei-00001-2000', 'art-1')).toMatch(/#art-1$/);
    expect(leiUrl('leizilla-ro-lei-00001-2000', 'ementa')).not.toMatch(/#/);
    expect(leiUrl('leizilla-ro-lei-00001-2000')).not.toMatch(/#/);
  });
});

describe('Internet Archive evidence URLs', () => {
  it('builds details and file URLs', () => {
    expect(iaDetailsUrl('leizilla-ro-lei-1')).toBe('https://archive.org/details/leizilla-ro-lei-1');
    expect(iaFileUrl('leizilla-ro-lei-1', 'law.xml')).toBe(
      'https://archive.org/download/leizilla-ro-lei-1/law.xml',
    );
  });
});

describe('parseFontes', () => {
  it('parses a JSON array of fontes', () => {
    expect(parseFontes('[{"ia_id":"a"}]')).toEqual([{ ia_id: 'a' }]);
  });

  it('fails open (empty array) on invalid JSON, non-array JSON, null and undefined', () => {
    expect(parseFontes('not json')).toEqual([]);
    expect(parseFontes('{"ia_id":"a"}')).toEqual([]);
    expect(parseFontes(null)).toEqual([]);
    expect(parseFontes(undefined)).toEqual([]);
  });
});

describe('formatTipoLei / formatEnte', () => {
  it('maps known tipo/ente codes to labels', () => {
    expect(formatTipoLei('lei')).toBe('Lei Ordinária');
    expect(formatTipoLei('decreto-lei')).toBe('Decreto-Lei');
    expect(formatEnte('ro')).toBe('Rondônia');
  });

  it('falls open on unknown/missing values', () => {
    expect(formatTipoLei(null)).toBe('Norma');
    expect(formatTipoLei('foo.bar')).toBe('Foo Bar');
    expect(formatEnte(null)).toBe('—');
    expect(formatEnte('ac')).toBe('AC');
  });
});

describe('leiTitle', () => {
  it('formats tipo + numero + ano', () => {
    expect(leiTitle({ tipo_lei: 'lei', numero_lei: '1.234', ano_lei: 2003 })).toBe(
      'Lei Ordinária nº 1.234/2003',
    );
  });

  it('falls open when numero or ano are missing', () => {
    expect(leiTitle({ tipo_lei: 'lei', numero_lei: null, ano_lei: 2003 })).toBe(
      'Lei Ordinária s/nº/2003',
    );
    expect(leiTitle({ tipo_lei: 'lei', numero_lei: '1', ano_lei: null })).toBe(
      'Lei Ordinária nº 1',
    );
  });

  it('accepts a bigint ano (Arrow columns)', () => {
    expect(leiTitle({ tipo_lei: 'lei', numero_lei: '1', ano_lei: 2003n })).toBe(
      'Lei Ordinária nº 1/2003',
    );
  });
});

describe('pathSegments / rotulo / breadcrumb', () => {
  it('handles the fixed top-level tokens', () => {
    expect(rotulo('ementa')).toBe('Ementa');
    expect(rotulo('preambulo')).toBe('Preâmbulo');
    expect(rotulo('titulo-lei')).toBe('Título da lei');
    expect(pathSegments('')).toEqual([]);
  });

  it('renders ordinal articles 1-9 and cardinal from 10', () => {
    expect(rotulo('art-1')).toBe('Art. 1º');
    expect(rotulo('art-10')).toBe('Art. 10');
  });

  it('renders a lettered article suffix from constitutional amendment renumbering', () => {
    expect(rotulo('art-5-a')).toBe('Art. 5º-A');
  });

  it('renders parágrafo único and numbered parágrafo', () => {
    expect(rotulo('par-unico')).toBe('Parágrafo único');
    expect(rotulo('par-2')).toBe('§ 2º');
  });

  it('renders inciso as upper-case roman numerals', () => {
    expect(rotulo('inc-3')).toBe('III');
    expect(rotulo('inc-4')).toBe('IV');
  });

  it('renders alínea as a lower-case letter followed by a parenthesis', () => {
    expect(rotulo('ali-a')).toBe('a)');
  });

  it('renders organizacional units (capítulo/seção/subseção) as roman numerals', () => {
    expect(rotulo('cap-2')).toBe('Capítulo II');
    expect(rotulo('sec-1')).toBe('Seção I');
    expect(rotulo('subsec-1')).toBe('Subseção I');
  });

  it('fails open on an unrecognized token, preserving each part literally', () => {
    expect(pathSegments('paragrafo-esquisito')).toEqual([
      { token: 'paragrafo', tipo: 'desconhecido', rotulo: 'paragrafo' },
      { token: 'esquisito', tipo: 'desconhecido', rotulo: 'esquisito' },
    ]);
    expect(rotulo('paragrafo-esquisito')).toBe('esquisito');
  });

  it('builds a readable breadcrumb from a composite path', () => {
    expect(breadcrumb('art-5-par-2-inc-3')).toBe('Art. 5º › § 2º › III');
  });
});

describe('formatDate', () => {
  it('formats an ISO date string in pt-BR', () => {
    expect(formatDate('2003-05-10')).toBe('10/05/2003');
  });

  it('formats epoch-millis as number or bigint (Arrow DATE columns)', () => {
    const epochMs = Date.UTC(2003, 4, 10);
    expect(formatDate(epochMs)).toBe('10/05/2003');
    expect(formatDate(BigInt(epochMs))).toBe('10/05/2003');
  });

  it('formats a native Date', () => {
    expect(formatDate(new Date(Date.UTC(2003, 4, 10)))).toBe('10/05/2003');
  });

  it('falls open to an em-dash on null/undefined and echoes back unparseable input', () => {
    expect(formatDate(null)).toBe('—');
    expect(formatDate(undefined)).toBe('—');
    expect(formatDate('not-a-date')).toBe('not-a-date');
  });
});

describe('citation', () => {
  const baseRow = {
    ente: 'ro',
    tipo_lei: 'lei',
    numero_lei: '1.234',
    ano_lei: 2003,
    dispositivo_path: 'art-1',
    urn_dispositivo: 'urn:lex:br;ro:estadual:lei:2003-05-10;1.234!art1',
    lei_id: 'leizilla-ro-lei-01234-2003',
  };

  it('includes ente, título, breadcrumb, URL and URN', () => {
    const result = citation(baseRow, 'https://franklinbaldo.github.io');
    expect(result).toContain('Rondônia. Lei Ordinária nº 1.234/2003');
    expect(result).toContain('Art. 1º');
    expect(result).toContain('https://franklinbaldo.github.io/lei/?id=leizilla-ro-lei-01234-2003');
    expect(result).toContain('urn:lex:br;ro:estadual:lei:2003-05-10;1.234!art1');
  });

  it('omits the breadcrumb for the ementa and the URN when absent', () => {
    const result = citation({ ...baseRow, dispositivo_path: 'ementa', urn_dispositivo: null });
    expect(result).not.toContain('›');
    expect(result.split('. ')).not.toContain(null);
  });

  it('falls back to origin.href when no explicit origin is passed (jsdom provides `location`)', () => {
    const result = citation(baseRow);
    expect(result).toContain('/lei/?id=leizilla-ro-lei-01234-2003');
  });
});
