# RFC-0006: Parser LLM provider-agnóstico via LiteLLM

**Status**: aceito — implementado no PR desta RFC
**Data**: 2026-07-08
**Supersede**: a decisão de 2026-05-23 ("#59 litellm migration — Fechada … manter SDK
`anthropic` diretamente", IMPLEMENTATION.md, log M10.2)
**Relacionados**: RFC-0004 (go-live: a chave LLM é pré-requisito essencial),
princípio load-bearing #3 ("Etapa 2 é pluggable"), `docs/okf/llm/litellm.md`

## Problema

O parse (Etapa 2) exige `ANTHROPIC_API_KEY` hardcoded como único provider:
`parse_law()` levanta `RuntimeError` sem ela, o `doctor` a trata como essencial e o
runbook de go-live (RFC-0004) a lista como bloqueador. Na prática:

1. **O mantenedor tem chave Gemini, não Anthropic.** O pré-requisito de go-live que
   está parado há 14 meses fica mais barato de destravar se qualquer chave servir.
2. O princípio load-bearing #3 já declara a Etapa 2 pluggable ("Default: Claude Haiku
   via API. Alternativas: …") — mas o código não honra o princípio: trocar de
   provider exige editar `parser.py`.
3. Cost-zero é princípio de projeto; o free tier do Gemini é a rota de custo zero
   para o smoke batch e os primeiros ranges.

### Por que a decisão de 2026-05-23 não se aplica mais

A PR #59 (Jules) foi fechada por três razões, todas endereçadas aqui:

| Razão de 2026-05-23 | Situação nesta RFC |
|---|---|
| "Migração sem justificativa no PR body" | Justificativa explícita: diretiva do mantenedor + go-live destravável com chave Gemini |
| "Quebra prompt caching (`cache_control` no root da mensagem)" | Implementado corretamente: `cache_control` permanece **no content block** do system prompt; `litellm.drop_params` descarta o parâmetro em providers que não suportam. Gemini tem caching implícito do lado do provider |
| "Indireção sem ganho para um projeto Claude-native" | A premissa "Claude-native" foi revogada pelo mantenedor; o ganho agora é concreto (usar a chave disponível) |

## Decisão

### 1. LiteLLM como camada única de chamada

`parser.parse_law()` troca `anthropic.Anthropic().messages.create(...)` por
`litellm.completion(...)`. O contrato do parse (JSON com `xml`/`confidence`/`tipo`/
`numero`/`ano`, gate de confiança ≥ 0.5, XML well-formed) **não muda** — só o
transporte.

### 2. Seleção de modelo (precedência)

1. Flag `--model` nos comandos `parse`/`parse-all` (inalterada; aceita qualquer id
   LiteLLM, ex. `gemini/gemini-2.5-flash`, `claude-haiku-4-5`, `openai/gpt-4o-mini`).
2. Env var **`LLM_MODEL`** (nova).
3. Default automático pela chave disponível: `ANTHROPIC_API_KEY` presente →
   `claude-haiku-4-5` (comportamento atual preservado); senão `GEMINI_API_KEY`/
   `GOOGLE_API_KEY` presente → `gemini/gemini-2.5-flash`; senão erro claro.

### 3. Validação de chave fail-fast por provider

Antes de chamar o LLM, um mapeamento prefixo-do-modelo → env var necessária
(`gemini/`→`GEMINI_API_KEY|GOOGLE_API_KEY`, `claude*`/`anthropic/`→`ANTHROPIC_API_KEY`,
`openai/`→`OPENAI_API_KEY`, …) produz `RuntimeError` com mensagem nomeando a variável
que falta — preserva o comportamento atual de não queimar um batch inteiro por falta
de credencial. Modelos de providers não mapeados passam direto (LiteLLM valida).

### 4. `doctor` e go-live

O check essencial deixa de ser "ANTHROPIC_API_KEY presente" e passa a ser **"existe
chave para o modelo LLM configurado"** (e informa qual modelo/variável). O passo 1 do
runbook da RFC-0004 lê-se agora: configurar `IA_ACCESS_KEY`/`IA_SECRET_KEY` + **uma**
chave LLM (`GEMINI_API_KEY` ou `ANTHROPIC_API_KEY` ou outra suportada) + opcional
`LLM_MODEL`.

### 5. Metadados e rastreabilidade

`parsed_meta.parse_method` continua `f"{model}+{input_type}"` — datasets parseados
com modelos diferentes ficam distinguíveis por item (PRD §3.1, evidência antes de
inferência). Contagem de tokens vem de `response.usage` do LiteLLM (formato OpenAI:
`prompt_tokens`/`completion_tokens`).

## Consequências

- `litellm` entra como dependência de runtime (`pyproject.toml`).
- Workflows que fazem parse (`parse-release.yml`) passam a expor também
  `GEMINI_API_KEY` e `LLM_MODEL` (secrets/vars ausentes viram string vazia — inócuo).
- Testes de `parser.py` mockam `litellm.completion` em vez do SDK `anthropic`;
  seguem 100% offline.
- O SDK `anthropic` sai das dependências diretas (LiteLLM o traz se necessário para
  modelos Claude).
- Qualidade de parse por modelo passa a ser uma variável observável: o
  `--error-threshold` de `parse-all` (M8.2) já cobre degradação; comparações
  formais entre modelos ficam para depois do go-live.

## Alternativas consideradas

- **Abstração própria (Protocol + adapters por provider)**: rejeitada — reinventa o
  LiteLLM com mais código para manter; o projeto já rejeitou manter superfície extra.
- **Manter anthropic-only e pedir a chave ao mantenedor**: rejeitada — mantém o
  go-live bloqueado por um único fornecedor e contradiz o princípio #3.
- **Gemini SDK direto (trocar um lock-in por outro)**: rejeitada — mesmo problema,
  provider diferente.
