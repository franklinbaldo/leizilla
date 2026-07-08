---
type: Configuracao
title: LLM — Parser
description: Biblioteca (LiteLLM), seleção de modelo e chaves usadas no parse de OCR/HTML para XML estruturado.
tags: [llm, litellm, parse]
timestamp: 2026-07-08T00:00:00Z
---

O parser (`src/leizilla/parser.py`) usa **LiteLLM** (`litellm.completion`) como
camada única de chamada — qualquer provider suportado pelo LiteLLM serve
(RFC-0006). O contrato do parse (JSON, gate de confiança, XML well-formed) não
depende do provider.

## Seleção de modelo (precedência)

1. Flag `--model` nos comandos `parse` e `parse-all` (qualquer id LiteLLM).
2. Env var `LLM_MODEL`.
3. Default automático pela chave disponível: `ANTHROPIC_API_KEY` presente →
   `claude-haiku-4-5`; senão `GEMINI_API_KEY`/`GOOGLE_API_KEY` presente →
   `gemini/gemini-2.5-flash`; senão erro claro.

## Provider e chaves

| Env var | Descrição |
|---|---|
| `LLM_MODEL` | Opcional. Id de modelo LiteLLM (ex. `gemini/gemini-2.5-flash`). Se ausente, o default é escolhido pela chave disponível. |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Chave Google para modelos `gemini/…`. |
| `ANTHROPIC_API_KEY` | Chave Anthropic para modelos `claude*` / `anthropic/…`. |
| `OPENAI_API_KEY` | Chave OpenAI para modelos `openai/…`. |

Uma chave basta — a que corresponder ao modelo em uso.

## Validação (fail-fast por provider)

Antes de chamar o LLM, um mapeamento prefixo-do-modelo → env var necessária
(`gemini/` → `GEMINI_API_KEY|GOOGLE_API_KEY`; `claude*`/`anthropic/` →
`ANTHROPIC_API_KEY`; `openai/` → `OPENAI_API_KEY`) levanta `RuntimeError`
nomeando a variável que falta — nenhum batch é queimado por falta de
credencial. Modelos de providers não mapeados passam direto (o próprio LiteLLM
valida).

## Trocar modelo em runtime

```bash
# Via flag --model
uv run leizilla parse --model gemini/gemini-2.5-flash --raw-id leizilla-raw-ro-casacivil-lei-00500
uv run leizilla parse-all --model claude-haiku-4-5 --start-coddoc 1 --end-coddoc 100

# Via env var
LLM_MODEL=gemini/gemini-2.5-flash uv run leizilla parse-all --start-coddoc 1 --end-coddoc 100
```

## Prompt caching

Para modelos Anthropic, o `cache_control` permanece **no content block** do
system prompt (formato correto de prompt caching). Para os demais providers,
`litellm.drop_params` descarta o parâmetro não suportado. Gemini tem caching
implícito do lado do provider — nada a configurar.

# Citations

[1] [Contrato de parse](parse-contract.md)
[2] [RFC-0006](/docs/rfc/0006-llm-provider-agnostico-litellm.md)
[3] [src/leizilla/parser.py](/src/leizilla/parser.py)
[4] [src/leizilla/config.py](/src/leizilla/config.py)
