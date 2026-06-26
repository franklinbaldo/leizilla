---
type: Convencao
title: Resolução de URL
description: Como o identificador lógico raw é convertido para URL de download no IA.
tags: [naming, url, internet-archive]
timestamp: 2026-06-25T00:00:00Z
---

`resolve_raw_url(ia_id, suffix, timeout=30, rendicao=None)` converte identificador lógico em URL de download.

## Assinatura

```python
def resolve_raw_url(
    ia_id: str,
    suffix: str,           # ex: ".pdf", "_djvu.txt", "_meta.json"
    timeout: int = 30,
    rendicao: Optional[str] = None,
) -> Optional[str]:
```

## Algoritmo

```
1. Extrai ente/fonte/chave do ia_id ("leizilla-raw-{ente}-{fonte}-{chave}")
2. Calcula (tipo, num) via parse_identity(chave)
3. Se num > 0 (chave identificável):
     range_ia_id = get_range_identifier(ente, fonte, tipo, num)
     Busca o uuid5 no index.csv do range bucket (via rendicao ou latest)
     → archive.org/download/{range_ia_id}/{uuid5}{suffix}
4. Se não identificável (coddoc, fallback, etc.):
     → archive.org/download/leizilla_{ente}_{fonte}_unidentified/...
5. Retorna None se uuid5 não encontrado no index.csv
```

## Exemplos

```python
resolve_raw_url("leizilla-raw-ro-casacivil-lei-00500", "_djvu.txt")
# → https://archive.org/download/leizilla_ro_casacivil_lei_0001-1000/a1b2c3d4_djvu.txt
#   (uuid5 "a1b2c3d4" lido do index.csv)

resolve_raw_url("leizilla-raw-ro-casacivil-lei-05120", ".pdf")
# → https://archive.org/download/leizilla_ro_casacivil_lei_5001-6000/cd4889ac.pdf
```

## Ente disambiguation

Entes são casados do **mais longo para o mais curto** (`ro-porto-velho` antes de `ro`) para evitar que prefixos menores consumam parte do nome de entes mais específicos.

# Citations

[1] [src/leizilla/ia_utils.py](/src/leizilla/ia_utils.py) — `resolve_raw_url`
[2] [Range Buckets](../storage/range-buckets.md)
[3] [Chaves de documento](chaves.md)
