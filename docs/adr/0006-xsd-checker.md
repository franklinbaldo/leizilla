# ADR-0006 — XSD Leizilla v0.1 + Consistency Checker

**Status**: Aprovada  
**Data**: 2026-05-20  
**Contexto**: M0.2b (implementado); registrado formalmente em M1

## Decisão

O schema canônico Leizilla XML é definido por dois instrumentos complementares:

1. **XSD** (`docs/schemas/leizilla-v0.1.xsd`): valida estrutura e tipos.
   Rodado via `xmllint --schema` no CI.

2. **Consistency checker** (`scripts/check_schema_consistency.py`): valida
   invariantes semânticos que o XSD não captura (ex: `path` único no documento,
   `urn-lex` bem-formada, referências `ia-id` não-vazias, formato `em` ISO 8601).

## Invariantes do checker (SCHEMA.md §7)

O checker cobre 9 invariantes (§7.1–§7.9). §7.9 permanece reservado (OCR ruim
foi removido do modelo — ver decisão 2026-05-20 no IMPLEMENTATION.md).

## Fixtures de teste

`tests/fixtures/leizilla_xml/*.xml` — 6 fixtures cobrindo: lei mínima, múltiplas
fontes, revogação total, revogação parcial, vigência não-óbvia, parse parcial.
Cada fixture passa XSD + checker.

## CI gate

`.github/workflows/schema-validate.yml`:
- XSD validation via `xmllint`
- Consistency checker via `python3 scripts/check_schema_consistency.py`
- XSLT Leizilla→LexML + validação do LexML resultante (ADR-0007)

## Versionamento

Schema é v0.1 durante M0–M4. Promove para v1.0 em M5 (frontend estável).
Breaking changes exigem novo arquivo XSD + fixtures de migração.
