---
type: Configuracao
title: LLM — Parser
description: Biblioteca e modelo usados no parse de OCR/HTML para XML estruturado.
tags: [llm, anthropic, parse]
timestamp: 2026-06-25T00:00:00Z
---

O parser (`src/leizilla/parser.py`) usa o **Anthropic SDK** diretamente.

## Modelo padrão

```
claude-haiku-4-5
```

Definido em `parser.py` como `_HAIKU = "claude-haiku-4-5"`. Pode ser sobrescrito via flag `--model` nos comandos `parse` e `parse-all`.

## Provider e chave

| Env var | Descrição |
|---|---|
| `ANTHROPIC_API_KEY` | Obrigatória. Se ausente, `parse_law()` levanta `RuntimeError("ANTHROPIC_API_KEY not configured")`. |

## Validação

```python
api_key = config.ANTHROPIC_API_KEY
if not api_key:
    raise RuntimeError("ANTHROPIC_API_KEY not configured")
client = anthropic.Anthropic(api_key=api_key)
```

## Trocar modelo em runtime

```bash
# Via flag --model
uv run leizilla parse --model claude-haiku-4-5-20251001 --raw-id leizilla-raw-ro-casacivil-lei-00500
uv run leizilla parse-all --model claude-opus-4-8 --start-coddoc 1 --end-coddoc 100
```

# Citations

[1] [Contrato de parse](parse-contract.md)
[2] [src/leizilla/parser.py](/src/leizilla/parser.py)
[3] [src/leizilla/config.py](/src/leizilla/config.py)
