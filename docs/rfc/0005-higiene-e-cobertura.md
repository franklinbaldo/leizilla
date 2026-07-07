# RFC-0005: Higiene de repositório e cobertura de testes

**Status**: aceito — implementado no PR desta RFC
**Data**: 2026-07-07
**Relacionados**: CLAUDE.md §"Testing & CI" (lacunas conhecidas), RFC-0002

## Problema

Pequenos desalinhamentos que, somados, corroem a confiança no repositório:

1. **`test_rondonia_e2e.py` na raiz do repo**, fora de `tests/` — não segue o padrão
   do projeto, não é claramente coletado pela suíte e polui a raiz. Usa dados reais de
   RO (pge-ro/cotel_scrap) contra `DuckDBStorage` — é um teste legítimo e offline, só
   está no lugar errado.
2. **Módulos sem nenhum teste direto**: `config.py` (parsing de env vars com defaults
   numéricos — um typo em `CRAWLER_DELAY` viraria crash em runtime) e `entes.py`
   (catálogo dos 27 estados + federal — base de todos os slugs de identifier IA).
   `ocr.py` tem cobertura fraca, e o incidente do M10.2 (regex `[\x7f-\xff]` que
   removia ç/ã/é de todo texto jurídico) mostrou que limpeza de texto é exatamente
   onde regressão silenciosa dói.
3. **Configuração morta**: override mypy para `anthropic.*` em `pyproject.toml` que o
   próprio mypy reporta como "unused section" em toda execução — ruído que treina
   todo mundo a ignorar warnings.

## Decisão (implementada neste PR)

1. Mover `test_rondonia_e2e.py` → `tests/test_rondonia_e2e.py`, adaptando ao estilo
   pytest da suíte (sem `sys.exit`/`main`, usando `tmp_path`).
2. Criar `tests/test_config.py`: defaults, override por env var, tipos numéricos dos
   parâmetros de crawler, paths derivados de `DATA_DIR`.
3. Criar `tests/test_entes.py`: 27 UFs + federal presentes, slugs kebab-case únicos,
   lookup por slug.
4. Reforçar `tests/test_ocr.py`: preservação de acentuação portuguesa (regressão do
   M10.2), normalização de espaços/hifenização, comportamento com entrada vazia.
5. Remover o componente não usado do override mypy em `pyproject.toml`.

Critério de pronto: `uv run leizilla dev check` + `uv run mypy src/` verdes, sem o
aviso de seção não usada, com os novos testes passando offline (nenhuma chamada de
rede real — regra da suíte).

## Fora de escopo

- Cobertura de `publisher.py`/`cli.py` além da existente (já são os módulos mais
  testados).
- Threshold de cobertura no CI — reavaliar depois do go-live (RFC-0004), quando a
  suíte parar de crescer toda semana.
