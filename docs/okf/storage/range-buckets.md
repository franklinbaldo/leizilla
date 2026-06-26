---
type: Infraestrutura
title: Range Buckets
description: PDFs são agrupados em buckets de 1000 itens no IA. Nunca uploads individuais por item.
tags: [storage, internet-archive, naming]
timestamp: 2026-06-25T00:00:00Z
---

PDFs brutos são agrupados em **range buckets** de 1000 itens. O upload físico sempre vai para o bucket — nunca para um item individual por lei.

## Fórmula do identificador do bucket

```
leizilla_{ente}_{fonte}_{tipo}_{start:04d}-{end:04d}
```

Para chaves `coddoc` (assembleia) e outros tipos não-identificáveis, o item é o **holding area** `_unidentified`:
```
leizilla_{ente}_{fonte}_unidentified
```

## Delimitadores

| Caracter | Papel |
|---|---|
| `_` (underscore) | Separa **seções** do identificador (ente, fonte, tipo, range) |
| `-` (hífen) | Uso **interno** dentro de seções (ex: `decreto-lei`, `ro-porto-velho`) |

**Regra**: `{fonte}` nunca contém hífen — quebraria o parser de identificadores.

## Cálculo do range

```python
start = ((num - 1) // 1000) * 1000 + 1
end   = start + 999
```

Limites acima de 9999 usam 5 dígitos — comportamento intencional.

## Exemplos

| Número | Tipo | Bucket |
|---|---|---|
| 500 | lei | `leizilla_ro_casacivil_lei_0001-1000` |
| 5120 | lei | `leizilla_ro_casacivil_lei_5001-6000` |
| 300 | decreto | `leizilla_ro_casacivil_decreto_0001-1000` |
| 42 | assembleia (coddoc) | `leizilla_ro_assembleia_unidentified` |

## Nomes de arquivo dentro do bucket

```
{uuid5}.pdf
{uuid5}_meta.json
{uuid5}_djvu.txt
```

O `uuid5` é um hash de 8 caracteres gerado deterministicamente a partir do conteúdo (UUIDv5 truncado):

```python
sha256_hex = hashlib.sha256(pdf_bytes).hexdigest()
uuid5      = str(uuid.uuid5(uuid.NAMESPACE_DNS, sha256_hex))[:8]
# ex: "a1b2c3d4"
```

Mesmo conteúdo → mesmo uuid5 → mesmo nome de arquivo. Garante idempotência e deduplicação.

## index.csv

Cada bucket mantém `index.csv` com as colunas:

| Coluna | Descrição |
|---|---|
| `tipo` | tipo normativo (lei, lc, decreto, …) |
| `numero` | número da norma na fonte |
| `rendicao` | original \| compilada \| atual \| "" |
| `formato` | pdf \| html \| docx |
| `uuid5` | nome do arquivo (8 chars) |
| `sha256` | hash completo — dedup + detecção de colisão |
| `captured_at` | ISO-8601 — ordena versões (newest wins) |
| `source` | chave de colheita / URL de origem |

Append-only; newest-wins em `(tipo, numero, rendicao, formato)`.

# Citations

[1] [src/leizilla/ia_utils.py](/src/leizilla/ia_utils.py) — `get_range_identifier`, `raw_filename`, `INDEX_COLUMNS`
[2] [Resolução de URL](../naming/url-resolution.md)
[3] [ADR-0010: raw content-addressed](/docs/adr/0010-raw-content-addressed-parsed-urn.md)
