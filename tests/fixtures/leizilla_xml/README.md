# Fixtures Leizilla XML v0.1

Casos de teste representativos do schema definido em
`docs/schemas/leizilla-v0.1.xsd`. Cada fixture cobre um cenário distinto
e é validada via `tests/test_lexml_export.py` (M0.2).

## Fixtures

| Arquivo | Cenário | Cobertura |
|---|---|---|
| `simple.xml` | Lei curta sem alterações, sem blocos organizacionais. | Caso mais comum: lei estadual pequena com poucos artigos. Valida o caminho feliz. |
| `with-alterations.xml` | Lei com timeline de versões: artigo alterado por lei posterior. | Valida `<versao numero=N>` com `vigente-de`/`vigente-ate` e `alterado-por`. |
| `with-blocos-organizacionais.xml` | Lei estruturada com livro/título/capítulo/seção. | Valida path organizacional namespaceado e nesting de blocos com dispositivos normativos. |
| `with-bloco-livre.xml` | Fallback de OCR ruim: `<bloco-livre quality="raw">`. | Valida o caminho de fallback quando LLM não consegue estruturar. |

## Como validar localmente

```bash
xmllint --schema docs/schemas/leizilla-v0.1.xsd \
        tests/fixtures/leizilla_xml/simple.xml \
        --noout
```

Ou via pytest (M0.2):
```bash
uv run pytest tests/test_lexml_export.py -v
```

## Convenções nas fixtures

- URN LEX em forma completa: `urn:lex:br;estado:rondonia;lei:YYYY-MM-DD;NNNNN`
  (dialect provisório — ver `docs/SCHEMA.md` §5.5 / §10).
- Datas históricas plausíveis (Rondônia: leis pós-1981 quando o estado foi
  criado).
- `<fonte ia-id="...">` referencia IA identifiers no padrão
  `leizilla-raw-{ente}-{fonte}-{chave}` (não-existentes em IA real; são
  exemplos sintéticos).
- Conteúdo textual é fictício (LEI Nº 9.999/XXXX) para evitar confusão
  com leis reais existentes.
