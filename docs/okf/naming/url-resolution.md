---
type: Convencao
title: Resolução de URL
description: Como o identificador lógico raw é convertido para URL de download no IA.
tags: [naming, url, internet-archive]
timestamp: 2026-06-25T00:00:00Z
---

`resolve_ia_id_to_url(ia_id, suffix, hash_8)` converte identificador lógico em URL de download.

## Algoritmo

```
1. Se não começa com "leizilla-raw-" → passthrough: archive.org/download/{ia_id}/{ia_id}{suffix}
2. Extrai {ente} por correspondência mais longa no catálogo entes.py
3. Extrai {fonte} e {chave} do restante
4. Calcula (tipo, num) via parse_chave_numeric(chave)
5. Se num > 0:
     range_ia_id = get_range_identifier(ente, fonte, tipo, num)
     filename    = {num:06d}_{hash_8}{suffix}
     → archive.org/download/{range_ia_id}/{filename}
6. Se num == 0 (fallback):
     → archive.org/download/leizilla_{ente}_{fonte}_fallback/{chave}_{hash_8}{suffix}
```

## Lookup do hash (em ordem de prioridade)

1. Parâmetro explícito `hash_8`
2. Campo `metadados.hash_8` na tabela `leis` do DuckDB local
3. Download de `manifest.csv` do range bucket no IA (função `discover_hash_from_manifest`)

Se nenhum hash encontrado, a URL é gerada **sem hash** (`{num:06d}{suffix}`) — pode não existir no IA se o upload sempre inclui hash.

## Exemplos

```python
resolve_ia_id_to_url("leizilla-raw-ro-casacivil-lei-00500", "_djvu.txt")
# → https://archive.org/download/leizilla_ro_casacivil_lei_0001-1000/000500_cd4889ac_djvu.txt
#   (hash lido do DuckDB ou manifest)

resolve_ia_id_to_url("leizilla-raw-ro-casacivil-lei-05120", ".pdf", hash_8="a1b2c3d4")
# → https://archive.org/download/leizilla_ro_casacivil_lei_5001-6000/005120_a1b2c3d4.pdf
```

## Ente disambiguation

Entes são casados do **mais longo para o mais curto** (`ro-porto-velho` antes de `ro`) para evitar que prefixos menores consumam parte do nome de entes mais específicos.

# Citations

[1] [src/leizilla/ia_utils.py](/src/leizilla/ia_utils.py) — `resolve_ia_id_to_url`
[2] [Range Buckets](../storage/range-buckets.md)
[3] [Chaves de documento](chaves.md)
