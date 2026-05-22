# ADR-0007 — LexML Export (XSLT one-way, gate de CI)

**Status**: Aprovada  
**Data**: 2026-05-20  
**Contexto**: M0.2b (implementado); registrado formalmente em M1

## Decisão

LexML brasileiro é **gate de CI one-way**, não constraint estrutural.
Round-trip (LexML → Leizilla XML) não é objetivo.

O XSLT `scripts/leizilla-to-lexml.xsl` (XSLT 1.0, `xsltproc`) mapeia
Leizilla XML para um subconjunto válido do LexML, validado contra
`tests/fixtures/lexml/lexml-br-rigido.xsd` (XSD oficial bundled localmente
para reprodutibilidade offline).

## Motivação

- **Interoperabilidade gov**: formato LexML é referência do projeto LexML Brasil
  (CGPID 2008). Ter exportação válida demonstra que o Leizilla XML é representável
  no vocabulário oficial.
- **CI como detector de regressão**: se uma mudança no XSD ou fixture quebra o
  XSLT, o CI captura imediatamente.

## Perdas documentadas

Ver `scripts/leizilla-to-lexml.xsl` header e SCHEMA.md §6.2:
- Timeline `<versao>`: colapsa para versão vigente única.
- `<fonte diverge="true">` + texto divergente: descartado.
- `<inicio tipo>`: descartado.
- `<revogacao>` total: descartada (LexML `<Norma>` não tem `situacao`).
- Anexos: descartados (LexML requer `<ReferenciaAnexo>` em docs separados).

## Bundle XSD

`tests/fixtures/lexml/` contém o bundle oficial + patches de `schemaLocation`
para paths locais + stub `mathml2.xsd` (MathML em leis brasileiras é raríssimo;
o stub tem as definições mínimas para satisfazer o parser).

## Implementação

Concluído em PR #12. Validado em CI via `schema-validate.yml`.
