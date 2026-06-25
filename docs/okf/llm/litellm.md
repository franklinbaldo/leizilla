---
type: Configuracao
title: LiteLLM
description: Camada de abstração LLM — providers, chaves, modelo padrão, configuração.
tags: [llm, litellm, gemini, anthropic]
timestamp: 2026-06-25T00:00:00Z
---

O Leizilla usa LiteLLM para abstrair o provider de LLM. Qualquer modelo compatível com LiteLLM pode ser usado sem mudança de código.

## Modelo padrão

```
gemini/gemini-2.5-flash
```

Configurável via env var `LITELLM_MODEL` sem mudança de código.

## Providers suportados

| Env var | Provider | Prefixo de modelo |
|---|---|---|
| `GEMINI_API_KEY` | Google Gemini (AI Studio) | `gemini/` |
| `ANTHROPIC_API_KEY` | Anthropic Claude | `claude-*` |
| `OPENROUTER_API_KEY` | OpenRouter (qualquer modelo) | `openrouter/` |

LiteLLM lê as env vars **automaticamente** — não é passado `api_key` explícito na chamada `litellm.completion()`.

## Carregamento de chaves

Ordem de prioridade (menor para maior):
1. `../workspace/.env` (chaves compartilhadas do workspace)
2. `leizilla/.env` (override do projeto)

## Validação

`parse_law` exige que pelo menos uma das três chaves esteja configurada. Se nenhuma estiver, levanta `RuntimeError("Nenhuma chave de LLM configurada")`.

## Trocar modelo em runtime

```bash
# Via env var (sem mudar código)
LITELLM_MODEL=openrouter/google/gemini-2.5-flash uv run leizilla parse-all ...

# Via flag --model
uv run leizilla parse --model gemini/gemini-1.5-flash --raw-id ...
```

## Nota sobre gemini-2.5-flash-lite

O modelo `gemini/gemini-2.5-flash-lite` retorna 503 frequentemente (preview com alta demanda). Usar `gemini/gemini-2.5-flash` como fallback.

# Citations

[1] [Contrato de parse](parse-contract.md)
[2] [src/leizilla/config.py](/src/leizilla/config.py)
[3] [src/leizilla/parser.py](/src/leizilla/parser.py)
