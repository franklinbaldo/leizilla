# Fixtures Leizilla XML v0.1

Casos de teste representativos do schema definido em
`docs/schemas/leizilla-v0.1.xsd`. Cada fixture cobre um cenário distinto
e exercita uma parte específica do design (ver `docs/SCHEMA.md`).

## Matriz de cobertura

| Arquivo | Cenário | Cobre |
|---|---|---|
| `simple.xml` | Lei pequena sem alterações, sem blocos organizacionais. | Caminho feliz: herança de vigência pura (zero `em`, zero `vigente-ate`). `<fonte>` única por versão. Tokens normativos básicos (`ementa`, `art-N`, `art-N-par-unico`). |
| `with-alteracoes.xml` | Lei com múltiplas alterações + dispositivo inserido por lei posterior + divergência multi-fonte. | Versões com `em` + `alterado-por`. `<fonte diverge="true">` com `<texto>` filho inline. Prova explícita de `<inicio tipo="vacatio-legis">` num dispositivo. |
| `with-blocos-organizacionais.xml` | CF/88 como exemplo pedagógico. | Path organizacional namespaceado (`tit-1`, `tit-2`, `tit-2-cap-1`) vs path normativo global (`art-1`, `art-5`) aninhado em blocos. URN LEX de constituição sem `;numero`. "Texto" do bloco organizacional é o nome do bloco. |
| `with-revogacoes.xml` | Revogações parciais em todas as formas estruturadas. | 4 `<revogacao>` parciais: `expressa`, `inconstitucionalidade` (URN de ADI), `caducidade` (sem `por`), `tacita` (URN da lei posterior). |
| `with-revogacao-total.xml` | Revogação total da lei. | `<revogacao>` no root, antes de `<dispositivo>`. Demonstra posição estrutural = escopo. |
| `with-ocr-ruim.xml` | Fallback OCR irrecuperável. | `<dispositivo path="ocr-ruim" quality="raw">`. Lei sem `urn-lex` (data não-extraível). Convivência: ementa parseada + corpo ilegível na mesma lei. |

## Como validar localmente

XSD bem-formedness e validação contra fixtures:

```bash
# Bem-formedness do schema
xmllint --noout docs/schemas/leizilla-v0.1.xsd

# Validação de cada fixture contra o schema
for f in tests/fixtures/leizilla_xml/*.xml; do
  xmllint --noout --schema docs/schemas/leizilla-v0.1.xsd "$f"
done
```

Ou via pytest (M0.2 — script ainda não escrito):

```bash
uv run pytest tests/test_leizilla_xml.py -v
```

## Convenções nas fixtures

- **URN LEX em forma completa**: `urn:lex:br;{jurisdicao};{tipo}:{YYYY-MM-DD};{numero}` para leis ordinárias; sem `;numero` final para constituições. Dialect provisório — ver `docs/SCHEMA.md` §5.6 e §8.
- **Datas históricas plausíveis** (Rondônia: leis pós-1981 quando o estado foi criado; CF/88 datada de 1988-10-05).
- **`<fonte ia-id>`** segue `leizilla-raw-{ente}-{fonte}-{chave}` (SCHEMA.md §5.1). IA identifiers são exemplos sintéticos — não existem em IA real.
- **Conteúdo textual** é fictício ou trecho público notório (CF/88 art. 1º, par. único). Leis fictícias usam numeração improvável (Lei 9.999/1999, Lei 1.234/2003, Lei 500/1990) para evitar confusão com leis reais existentes.
- **OCR ruim** em `with-ocr-ruim.xml` simula erros comuns (0→0, 1→|, 5→5/S) presentes em PDFs digitalizados pré-2000.

## O que estes fixtures NÃO cobrem (M0.3+)

- Invariantes do consistency checker (§7 do SCHEMA.md) — `scripts/check_schema_consistency.py` pendente em M0.2.
- Round-trip Leizilla XML → LexML — `scripts/leizilla-to-lexml.xsl` pendente em M0.2.
- Negative test cases (XML inválido propositalmente para garantir que o validador pega) — pendente em M0.2.
- Lei muito grande com 100+ dispositivos — performance/scaling fica para M4 benchmarks.

## Histórico

Versão atual (v2) é o redesign first-principles. A versão v1 foi proposta no PR #7 com modelagem dispositivo-cêntrica mas ainda carregando `<header>`, `<rotulo>`, atributo `tipo`/`parent`/`urn`, `<versoes>` wrapper, `<bloco-livre>` separado, etc. PR #7 está superseded — fica como referência histórica.

Migração detalhada na tabela em `docs/SCHEMA.md` §9.
