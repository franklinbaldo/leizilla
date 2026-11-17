import { describe, expect, it } from 'vitest';
import {
  agruparRelacoes,
  buildCatalogoWhere,
  comCamadaDeTexto,
  estagioDe,
  normalizarBusca,
  parseArquivos,
  parseConsulta,
  situacaoRotulo,
  truncar,
  type RelacaoRow,
} from './catalogo';

describe('normalizarBusca', () => {
  // Os mesmos casos de tests/test_catalogo.py::TestNormalizarBusca — o portal precisa
  // aplicar à consulta exatamente o algoritmo que o pipeline aplicou ao campo `busca`.
  it.each([
    ['Lei nº 1.234 — Crédito Suplementar', 'lei n 1 234 credito suplementar'],
    ['  AÇÃO   Pública, §2º  ', 'acao publica 2'],
    ['Decreto-Lei n. 9A', 'decreto lei n 9a'],
    ['Orçamento-Programa (ICMS/RO)', 'orcamento programa icms ro'],
    ['', ''],
    ['ç ã é ü ñ', 'c a e u n'],
  ])('%s', (entrada, esperado) => {
    expect(normalizarBusca(entrada)).toBe(esperado);
  });
});

describe('parseConsulta', () => {
  it('remove o ponto de milhar e separa o número', () => {
    const c = parseConsulta('Lei 1.234');
    expect(c.tokens).toEqual(['lei', '1234']);
    expect(c.numeros).toEqual([1234]);
  });
  it('ignora acentos e repetições', () => {
    expect(parseConsulta('Crédito crédito suplementar').tokens).toEqual(['credito', 'suplementar']);
  });
  it('não toma datas nem anos soltos por número fora do limite', () => {
    expect(parseConsulta('12345678901').numeros).toEqual([]);
  });
  it('consulta vazia', () => {
    expect(parseConsulta('  ').tokens).toEqual([]);
  });
});

describe('buildCatalogoWhere', () => {
  it('sem consulta só exige norma listada', () => {
    const q = buildCatalogoWhere('', {});
    expect(q.where).toBe("situacao = 'listada'");
    expect(q.score).toBe('0');
  });
  it('um termo textual casa início de palavra', () => {
    const q = buildCatalogoWhere('crédito', {});
    expect(q.where).toContain("strpos(' ' || busca, ?) > 0");
    expect(q.whereParams).toEqual([' credito']);
  });
  it('um termo numérico casa número exato ou palavra inteira, e pesa na relevância', () => {
    const q = buildCatalogoWhere('lei 80', {});
    expect(q.whereParams).toEqual([' lei', 80, ' 80 ']);
    expect(q.score).toContain('numero IN (?)');
    expect(q.scoreParams[0]).toBe(80);
  });
  it('tipo + número ganha bônus pelo título exato ("lei n 80 ")', () => {
    const q = buildCatalogoWhere('lei 80', {});
    expect(q.scoreParams).toContain('lei n 80 ');
    expect(buildCatalogoWhere('credito suplementar', {}).scoreParams).not.toContain('credito suplementar n ');
  });
  it('aplica tipo, ano e década', () => {
    const q = buildCatalogoWhere('', { tipo: 'lc', ano: 2010, decada: 2010 });
    expect(q.where).toBe("situacao = 'listada' AND tipo = ? AND ano = ? AND decada = ?");
    expect(q.whereParams).toEqual(['lc', 2010, 2010]);
  });
  it('várias palavras ganham bônus de frase', () => {
    const q = buildCatalogoWhere('plano de carreira', {});
    expect(q.scoreParams).toContain(' plano de carreira');
  });
  it('nunca interpola o texto do usuário no SQL', () => {
    const q = buildCatalogoWhere("x'); DROP TABLE catalogo_t; --", {});
    expect(q.where).not.toContain('DROP');
    expect(q.score).not.toContain('DROP');
  });
});

describe('estagioDe', () => {
  const base = { preservada: null, legivel: null, estruturada: null };
  it('segue a ordem estruturada > legível > preservada', () => {
    expect(estagioDe({ preservada: true, legivel: true, estruturada: true })).toBe('estruturada');
    expect(estagioDe({ preservada: true, legivel: true, estruturada: false })).toBe('legivel');
    expect(estagioDe({ preservada: true, legivel: false, estruturada: false })).toBe('preservada');
  });
  it('só catálogo exige preservação medida como falsa', () => {
    expect(estagioDe({ ...base, preservada: false })).toBe('so-catalogo');
    expect(estagioDe(base)).toBe('nao-medido');
  });
});

describe('situacaoRotulo', () => {
  it('a situação neutra não tem selo', () => {
    expect(situacaoRotulo('sem-indicacao-de-revogacao')).toBeNull();
    expect(situacaoRotulo(null)).toBeNull();
  });
  it('revogada nunca diz mais que o índice', () => {
    expect(situacaoRotulo('revogada')).toBe('Revogada segundo o índice');
    expect(situacaoRotulo('retificada')).toBe('Retificada segundo o índice');
  });
});

describe('truncar / parseArquivos', () => {
  it('corta em fronteira de palavra', () => {
    const t = truncar('Dispõe sobre a criação do Conselho Estadual das Cidades do Estado', 40);
    expect(t.endsWith('…')).toBe(true);
    expect(t.length).toBeLessThanOrEqual(41);
    expect(t).not.toMatch(/\s…$/);
  });
  it('texto curto fica intacto', () => {
    expect(truncar('Curto.', 40)).toBe('Curto.');
  });
  it('parseArquivos é fail-open', () => {
    expect(parseArquivos('lixo')).toEqual([]);
    expect(parseArquivos(null)).toEqual([]);
    expect(parseArquivos('[{"nome":"L1.pdf","url":"https://x/L1.pdf","rendicao":"original"}]')).toEqual([
      { nome: 'L1.pdf', url: 'https://x/L1.pdf', rendicao: 'original' },
    ]);
  });
});

const rel = (over: Partial<RelacaoRow>): RelacaoRow => ({
  relacao_id: 'r1',
  origem_id: 'leizilla-raw-ro-casacivil-lei-00200',
  verbo: 'altera',
  verbo_texto: 'Altera',
  parcial: true,
  alvo_tipo: 'lei',
  alvo_categoria: 'estadual-ou-nao-qualificada',
  alvo_numero: 100,
  alvo_sufixo: '',
  alvo_data: '1990-01-01',
  alvo_ano: 1990,
  alvo_texto: 'Lei nº 100, de 1 de janeiro de 1990',
  alvo_id: 'leizilla-raw-ro-casacivil-lei-00100',
  confianca: 'resolvida',
  nota: null,
  trecho: 'Altera a Lei nº 100',
  fonte_relacao: 'ementa',
  alvo_titulo: 'Lei n. 100, de 01-01-1990',
  origem_titulo: 'Lei n. 200, de 05-05-1995',
  ...over,
});

describe('agruparRelacoes', () => {
  const id200 = 'leizilla-raw-ro-casacivil-lei-00200';
  const id100 = 'leizilla-raw-ro-casacivil-lei-00100';

  it('mostra nos dois sentidos, com link para a outra norma', () => {
    const rows = [rel({}), rel({ relacao_id: 'r2', verbo: 'revoga', origem_id: 'leizilla-raw-ro-casacivil-decreto-00300', alvo_id: id200 })];
    const da200 = agruparRelacoes(rows, id200);
    expect(da200.ativas).toHaveLength(1);
    expect(da200.ativas[0].rotulo).toBe('Altera');
    expect(da200.ativas[0].itens[0].href).toContain(encodeURIComponent(id100));
    expect(da200.passivas[0].rotulo).toBe('Revogada por');
    const da100 = agruparRelacoes(rows, id100);
    expect(da100.passivas[0].rotulo).toBe('Alterada por');
    expect(da100.passivas[0].itens[0].titulo).toBe('Lei n. 200, de 05-05-1995');
  });

  it('relação não resolvida é texto, sem link, com o motivo', () => {
    const g = agruparRelacoes(
      [rel({ alvo_id: null, confianca: 'nao-resolvida', nota: 'federal', alvo_texto: 'Lei Federal nº 8.666' })],
      id200,
    );
    const item = g.ativas[0].itens[0];
    expect(item.href).toBeNull();
    expect(item.titulo).toBe('Lei Federal nº 8.666');
    expect(item.nota).toBe('norma federal');
  });

  it('relação não resolvida nunca aparece como "alterada por" de ninguém', () => {
    const g = agruparRelacoes([rel({ alvo_id: null, confianca: 'nao-resolvida' })], id100);
    expect(g.passivas).toHaveLength(0);
  });

  it('ambígua com alvo vira link com observação', () => {
    const g = agruparRelacoes([rel({ confianca: 'ambigua', nota: 'identidade-incerta' })], id200);
    expect(g.ativas[0].itens[0].href).not.toBeNull();
    expect(g.ativas[0].itens[0].nota).toBe('identidade incerta no índice');
  });

  it('ordena os grupos: revoga antes de altera', () => {
    const g = agruparRelacoes([rel({}), rel({ relacao_id: 'r3', verbo: 'revoga' })], id200);
    expect(g.ativas.map((x) => x.rotulo)).toEqual(['Revoga', 'Altera']);
  });
});

describe('comCamadaDeTexto', () => {
  const base = {
    norma_id: 'leizilla-raw-ro-casacivil-decreto-32251',
    legivel: false,
    com_texto: false,
  };

  it('sobe legivel e com_texto quando a norma tem texto na camada', () => {
    const ids = new Set([base.norma_id]);
    expect(comCamadaDeTexto(base, ids)).toEqual({ ...base, legivel: true, com_texto: true });
  });

  it('não mexe na linha quando a norma não tem texto na camada', () => {
    const row = { ...base, legivel: false };
    expect(comCamadaDeTexto(row, new Set(['outra-norma']))).toBe(row);
  });

  it('nunca rebaixa um legivel já verdadeiro', () => {
    const row = { ...base, legivel: true };
    expect(comCamadaDeTexto(row, new Set())).toEqual(row);
  });
});
