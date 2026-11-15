import { describe, expect, it } from 'vitest';
import {
  decadaLabel,
  fmtCount,
  fmtPct,
  formatRanges,
  headline,
  missingList,
  parseCompletude,
  rangesTotal,
  scopeNote,
  unmeasuredStages,
  type TipoCompletude,
} from './completude';
import { COMPLETENESS_JSON_URL, COMPLETENESS_PARQUET_URL, COVERAGE_JSON_URL } from './db';

const LEI: TipoCompletude = {
  tipo: 'lei',
  rotulo: 'Leis ordinárias',
  ano_inicial: 1983,
  ano_final: 2026,
  anos: 44,
  anos_lidos: 7,
  catalogo_completo: false,
  listadas: 626,
  preservadas: 187,
  com_texto: 177,
  legiveis: 177,
  estruturadas: null,
  faltantes: 439,
  pct_preservadas: 29.9,
  pct_com_texto: 28.3,
  pct_legiveis: 28.3,
  pct_estruturadas: null,
  fora_do_indice: 0,
  indice_incompleto: 1669,
  faltantes_intervalos: [
    [24, 24],
    [49, 50],
  ],
  faltantes_com_sufixo: [],
  por_decada: [],
};

const REPORT = {
  leizilla_completeness_version: '0.1',
  ente: 'ro',
  fonte: 'casacivil',
  generated_at: '2026-11-15T13:00:00+00:00',
  git_sha: null,
  catalogo: { completo: false, paginas: 179, paginas_lidas: 25, anos_desconhecidos: [] },
  medicao: { ok_s2_s3: true, ok_s4: false, ok_legivel: true },
  tipos: [LEI],
  tipos_sem_indice: [],
};

describe('parseCompletude', () => {
  it('accepts the published contract', () => {
    expect(parseCompletude(REPORT)?.tipos[0].rotulo).toBe('Leis ordinárias');
  });

  it('fails open on anything else', () => {
    expect(parseCompletude(null)).toBeNull();
    expect(parseCompletude('x')).toBeNull();
    expect(parseCompletude({ ...REPORT, leizilla_completeness_version: '1.0' })).toBeNull();
    expect(parseCompletude({ ...REPORT, tipos: 'x' })).toBeNull();
    expect(parseCompletude({ ...REPORT, tipos: [{ tipo: 'lei' }] })).toBeNull();
    expect(parseCompletude({ ...REPORT, medicao: null })).toBeNull();
  });
});

describe('headline / scopeNote', () => {
  it('states preserved and readable against the official total', () => {
    expect(headline(LEI)).toBe('Leis ordinárias: 187 de 626 preservadas, 177 legíveis');
  });

  it('never shows an unmeasured counter as zero', () => {
    expect(headline({ ...LEI, preservadas: null, legiveis: null })).toBe(
      'Leis ordinárias: ? de 626 preservadas, ? legíveis',
    );
  });

  it('agrees in number', () => {
    expect(headline({ ...LEI, preservadas: 1, legiveis: 1 })).toBe(
      'Leis ordinárias: 1 de 626 preservada, 1 legível',
    );
  });

  it('names the stages that could not be measured', () => {
    expect(unmeasuredStages({ ok_s2_s3: true, ok_s4: true, ok_legivel: true })).toBe('');
    expect(unmeasuredStages({ ok_s2_s3: true, ok_s4: false, ok_legivel: true })).toBe(
      'normas estruturadas',
    );
    expect(unmeasuredStages({ ok_s2_s3: false, ok_s4: false, ok_legivel: false })).toBe(
      'preservação e texto (itens do Internet Archive); camada de texto do portal (legíveis); normas estruturadas',
    );
  });

  it('says how much of the official index was read', () => {
    expect(scopeNote(LEI)).toBe(
      'índice oficial lido em 7 de 44 anos (1983–2026) — os demais anos são desconhecidos, não zero',
    );
    expect(scopeNote({ ...LEI, catalogo_completo: true, anos_lidos: 44 })).toBe(
      'índice oficial completo (1983–2026)',
    );
  });
});

describe('formatting', () => {
  it('formats counts and percentages in pt-BR', () => {
    expect(fmtCount(3358)).toBe('3.358');
    expect(fmtCount(null)).toBe('?');
    expect(fmtPct(29.9)).toBe('29,9%');
    expect(fmtPct(null)).toBe('—');
    expect(decadaLabel(1980)).toBe('1980–89');
    expect(decadaLabel(2000)).toBe('2000–09');
  });

  it('compacts missing-number ranges and reports what was cut', () => {
    expect(formatRanges(LEI.faltantes_intervalos)).toEqual({ text: '24, 49–50', omitted: 0 });
    expect(rangesTotal(LEI.faltantes_intervalos)).toBe(3);
    expect(missingList({ faltantes_intervalos: [], faltantes_com_sufixo: ['9A'] })).toEqual({
      text: '9A',
      omitted: 0,
    });
    expect(
      missingList({ faltantes_intervalos: [[2, 9]], faltantes_com_sufixo: ['4591A', '4591B'] }),
    ).toEqual({ text: '2–9, 4591A, 4591B', omitted: 0 });
    expect(
      formatRanges(
        [
          [1, 3],
          [7, 7],
          [10, 19],
        ],
        2,
      ),
    ).toEqual({ text: '1–3, 7', omitted: 10 });
  });
});

describe('published URLs', () => {
  it('live next to coverage.json on the dataset item', () => {
    expect(COVERAGE_JSON_URL).toBe(
      'https://archive.org/download/leizilla-dataset-ro-v0-latest/coverage.json',
    );
    expect(COMPLETENESS_JSON_URL).toBe(
      'https://archive.org/download/leizilla-dataset-ro-v0-latest/completeness.json',
    );
    expect(COMPLETENESS_PARQUET_URL).toBe(
      'https://archive.org/download/leizilla-dataset-ro-v0-latest/completeness.parquet',
    );
  });
});
