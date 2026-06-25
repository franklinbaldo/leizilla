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

Para tipo `coddoc` (assembleia), o tipo é **omitido**:
```
leizilla_{ente}_{fonte}_{start:04d}-{end:04d}
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
| 42 | assembleia (coddoc) | `leizilla_ro_assembleia_0001-1000` |

## Nomes de arquivo dentro do bucket

```
{num:06d}_{hash_8}.pdf
{num:06d}_{hash_8}_meta.json
```

O nome **sem hash** (`{num:06d}.pdf`) é reservado para artefatos canônicos futuros.

## Hash

8 caracteres, gerado deterministicamente:
```python
sha256_hex = hashlib.sha256(pdf_bytes).hexdigest()
hash_8     = str(uuid.uuid5(uuid.NAMESPACE_DNS, sha256_hex))[:8]
```

Mesmo conteúdo → mesmo hash → mesmo nome de arquivo. Garante idempotência.

## manifest.csv

Cada bucket mantém `manifest.csv` com colunas `filename,url`. Atualizado incrementalmente a cada upload. Usado pelo discover para verificação cruzada.

# Citations

[1] [src/leizilla/ia_utils.py](/src/leizilla/ia_utils.py) — `get_range_identifier`, `get_ia_filename`
[2] [Resolução de URL](../naming/url-resolution.md)
[3] [ADR-0005: Padrão de identificadores IA](/docs/adr/0005-ia-identifiers.md)
