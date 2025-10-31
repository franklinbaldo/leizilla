# ADR 0004: Separação Engine/Site com Execução via uvx

**Data:** 2025-10-31
**Status:** Aceito
**Responsáveis:** Franklin Baldo
**Contexto:** Pós-MVP, preparação para frontend e separação de responsabilidades

## Contexto

### Problema Identificado

Com o MVP funcional do leizilla (engine de crawling e ETL), surgiu a necessidade de criar uma interface web para visualização dos dados. As opções tradicionais apresentavam trade-offs indesejados:

1. **Monorepo com backend tradicional**:
   - Servidores contínuos (custo, manutenção)
   - Acoplamento entre engine e frontend
   - Infraestrutura complexa

2. **Datasets pré-gerados sem atualização**:
   - Dados estáticos rapidamente desatualizados
   - Sem possibilidade de crawls sob demanda
   - Usuários não podem refrescar dados

3. **API REST tradicional**:
   - Servidores 24/7 (custo, complexidade)
   - Contradiz filosofia de zero-infraestrutura
   - Ponto único de falha

### Solução: uvx como Ponte Entre Repositórios

A ferramenta `uvx` (do projeto uv/astral-sh) permite executar aplicações Python diretamente de repositórios git:

```bash
uvx git+https://github.com/user/repo.git@version command args
```

Isso possibilita:
- **Execução remota** do engine sem instalação local
- **Versionamento explícito** via git tags
- **GitHub Actions como backend** (compute gratuito)
- **Separação limpa** de repositórios e responsabilidades

## Decisão

### Arquitetura de Dois Repositórios

#### leizilla (Engine Repository - Atual)

**Responsabilidades**:
- Crawling de fontes oficiais (.gov.br)
- ETL e processamento de dados
- Exportação de datasets (Parquet, DuckDB)
- CLI completo e versionado
- Schema de dados e migrações

**Não faz**:
- Interface web
- Hosting de dados
- Renderização HTML

**Consumido via**:
```bash
uvx git+https://github.com/franklinbaldo/leizilla.git@v1.2.3 leizilla <command>
```

#### leizilla-site (Frontend Repository - Novo)

**Responsabilidades**:
- Interface web estática (HTML/CSS/JS)
- DuckDB-WASM para busca client-side
- Orquestração de execuções do engine
- GitHub Actions executando uvx
- Hospedagem em GitHub Pages

**Não faz**:
- Crawling ou ETL (delega ao engine)
- Backend tradicional (usa GitHub Actions)
- Duplicação de código do engine

**Executa engine via**:
```yaml
# .github/workflows/scheduled-crawl.yml
steps:
  - name: Run discovery
    run: |
      uvx git+https://github.com/franklinbaldo/leizilla.git@v1.2.3 \
        leizilla discover --origem rondonia
```

### Fluxo de Dados

```
┌──────────────────────────────────────────────────────────────┐
│  leizilla (Engine)                                           │
│  - Versioned releases (v1.0.0, v1.1.0, ...)                 │
│  - CLI com JSON output (--format json)                      │
│  - Dataset index generation (export-index)                  │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     │ uvx git+https://...@v1.2.3
                     ▼
┌──────────────────────────────────────────────────────────────┐
│  GitHub Actions (Compute)                                    │
│  - Scheduled: Weekly crawls                                  │
│  - Manual: User-triggered refreshes                          │
│  - Outputs: Parquet files, DuckDB, index.json               │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     │ GitHub Releases + Artifacts
                     ▼
┌──────────────────────────────────────────────────────────────┐
│  leizilla-site (Frontend)                                    │
│  - Static HTML/JS on GitHub Pages                           │
│  - Loads datasets from Releases                             │
│  - DuckDB-WASM for search                                   │
│  - Admin panel triggers Actions                             │
└──────────────────────────────────────────────────────────────┘
```

### Versionamento e Compatibilidade

**Engine (leizilla)**:
- Semantic versioning: `v{major}.{minor}.{patch}`
- Git tags: `v1.0.0`, `v1.1.0`, `v1.2.3`, etc.
- Breaking changes → major bump
- New features → minor bump
- Bug fixes → patch bump

**Site (leizilla-site)**:
- Pins engine version in workflows:
  ```yaml
  env:
    ENGINE_VERSION: v1.2.3
  ```
- Testa nova versão antes de promover
- Pode usar diferentes versões em diferentes workflows
- Independente do ciclo de release do engine

**Matriz de Compatibilidade**:
| Site Version | Compatible Engine | Notes                    |
|--------------|-------------------|--------------------------|
| v1.0.x       | v1.2.x, v1.3.x    | Initial release          |
| v1.1.x       | v1.3.x, v1.4.x    | New search filters       |
| v2.0.x       | v2.0.x+           | Breaking: New data schema|

### Modificações no Engine para Compatibilidade

Para suportar execução via uvx e consumo pelo site:

#### 1. JSON Output Mode

Comandos agora suportam `--format json`:

```python
@app.command("search")
def cmd_search(
    ...,
    format: str = typer.Option("text", help="Formato de saída (text, json)"),
):
    if format == "json":
        output = {'count': len(laws), 'results': laws}
        echo(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        # Human-readable text output
```

Comandos afetados:
- `leizilla search --format json`
- `leizilla stats --format json`

#### 2. Dataset Index Generation

Novo comando para gerar metadados dos datasets:

```python
@app.command("export-index")
def cmd_export_index(
    origem: Optional[str] = None,
    output: str = "leizilla_index.json",
):
    """Exporta índice de datasets com metadados"""
    db = DatabaseManager()
    metadata = db.get_dataset_metadata(origem=origem)
    # Outputs JSON with file names, counts, URLs, checksums
```

Formato do índice:
```json
{
  "version": "1.0",
  "generated_at": "2025-10-31T12:00:00Z",
  "datasets": [
    {
      "origem": "rondonia",
      "year": null,
      "file": "leis_rondonia_completo.parquet",
      "law_count": 12345,
      "description": "Complete dataset for rondonia"
    }
  ],
  "stats": {
    "total_laws": 12345,
    "origins": ["rondonia"],
    "years": [2020, 2021, 2022, 2023, 2024]
  }
}
```

#### 3. DatabaseManager Alias

```python
# storage.py
DatabaseManager = DuckDBStorage  # Alias para compatibilidade CLI
```

#### 4. get_dataset_metadata() Method

```python
# storage.py
def get_dataset_metadata(self, origem: Optional[str] = None) -> Dict[str, Any]:
    """Retorna metadados completos para índice de datasets"""
    # Consulta DB e gera metadados estruturados
```

## Consequências

### Positivas

1. **Separação limpa de responsabilidades**:
   - Engine foca em dados
   - Site foca em UX
   - Equipes podem trabalhar independentemente

2. **Zero custo de infraestrutura**:
   - Engine: código no GitHub (grátis)
   - Compute: GitHub Actions (grátis, 2000 min/mês)
   - Site: GitHub Pages (grátis)
   - Storage: Internet Archive (grátis)

3. **Versionamento explícito**:
   - Site controla qual engine usar
   - Testa antes de promover versões
   - Rollback trivial (muda tag no YAML)

4. **Execução local idêntica**:
   - Usuários rodam mesmos comandos
   - Debugging simplificado
   - Transparência total

5. **Resiliência**:
   - Engine pode evoluir sem quebrar site
   - Site pode usar múltiplas versões do engine
   - Sem acoplamento temporal

### Negativas

1. **Latência de GitHub Actions**:
   - Workflows levam 30-60s para iniciar
   - Não é real-time
   - Mitigação: Scheduled crawls + cache

2. **Limites do GitHub**:
   - 2000 minutos/mês no free tier
   - Workflows timeout em 6 horas
   - Mitigação: Crawls incrementais

3. **Complexidade de debugging**:
   - Erros em Actions são remotos
   - Logs menos acessíveis que local
   - Mitigação: JSON output + bons logs

4. **Dependência do GitHub**:
   - Workflow triggers via API
   - Rate limits (5000 req/hora autenticado)
   - Mitigação: Cachear resultados

### Neutras

1. **Dois repositórios**:
   - Mais organização, mas mais coordenação
   - Issues separados por área
   - CIs separados

2. **Documentação duplicada**:
   - Cada repo tem CLAUDE.md
   - Precisa manter sincronizados
   - Mitigação: Docs centralizados no engine

## Alternativas Consideradas

### 1. Monorepo com Lerna/Turborepo

**Prós**: Single source of truth, atomic commits across engine/site
**Contras**: Mais complexo, não usa uvx, perde versionamento independente
**Razão da rejeição**: Perde benefícios de uvx e separação limpa

### 2. Datasets Estáticos no GitHub Releases

**Prós**: Simples, sem execução dinâmica
**Contras**: Dados desatualizados, sem crawls sob demanda
**Razão da rejeição**: Não permite refresh por usuários

### 3. Serverless API (Cloudflare Workers)

**Prós**: Latência baixa, execução on-demand
**Contras**: Ainda é infra, limites de execução (10-30s)
**Razão da rejeição**: Contradiz filosofia zero-infra

### 4. Docker Containers + GitHub Container Registry

**Prós**: Reprodutibilidade perfeita
**Contras**: Mais pesado que uvx, builds mais lentos
**Razão da rejeição**: uvx é mais leve e alinhado com Python

## Implementação

### Fase 1: Preparação do Engine (Completo)

- [x] Adicionar `--format json` aos comandos relevantes
- [x] Implementar `export-index` command
- [x] Criar `get_dataset_metadata()` no storage
- [x] Adicionar `DatabaseManager` alias
- [x] Testar execução via uvx localmente
- [x] Documentar em CLAUDE.md
- [x] Criar ADR (este documento)

### Fase 2: Criação do leizilla-site (Futuro)

- [ ] Criar repositório franklinbaldo/leizilla-site
- [ ] Implementar workflows de GitHub Actions
- [ ] Criar frontend estático com DuckDB-WASM
- [ ] Configurar GitHub Pages
- [ ] Documentar integração no README

### Fase 3: Integração e Testes (Futuro)

- [ ] Testar workflow completo
- [ ] Validar versionamento
- [ ] Documentar processo de upgrade de engine
- [ ] Criar guia de troubleshooting

## Referências

- **uv/uvx Documentation**: https://docs.astral.sh/uv/concepts/tools/
- **GitHub Actions**: https://docs.github.com/en/actions
- **DuckDB-WASM**: https://duckdb.org/docs/api/wasm/overview
- **Leizilla Site Plan**: `docs/plans/LEIZILLA_SITE_IMPLEMENTATION_PLAN.md`
- **ADR 0001**: Internet Archive como pilar central (validação no CausaGanha)
- **ADR 0002**: Frontend estático vanilla (princípios aplicados ao site)

## Notas de Implementação

### Testando Localmente com uvx

```bash
# Testar versão específica
uvx git+https://github.com/franklinbaldo/leizilla.git@v1.2.3 leizilla --help

# Testar branch
uvx git+https://github.com/franklinbaldo/leizilla.git@main leizilla stats --format json

# Testar commit específico
uvx git+https://github.com/franklinbaldo/leizilla.git@abc123def leizilla discover --origem rondonia --limit 5
```

### Workflow de Upgrade de Versão

1. Engine lança nova versão: `v1.3.0`
2. Site testa via workflow manual:
   ```bash
   Actions → Test Engine Version → v1.3.0
   ```
3. Se sucesso, atualiza `ENGINE_VERSION` em workflows
4. Commit e push
5. Próximo scheduled run usa nova versão

### Troubleshooting

**Problema**: `uvx` não encontra versão
**Solução**: Verificar se tag existe no GitHub (`git tag`)

**Problema**: Workflow timeout
**Solução**: Reduzir `--limit` ou fazer crawl incremental

**Problema**: JSON malformado
**Solução**: Validar localmente com `jq`: `leizilla stats --format json | jq`

---

**Status**: ✅ Aceito e implementado
**Próximos passos**: Criação do repositório leizilla-site conforme plano em `docs/plans/LEIZILLA_SITE_IMPLEMENTATION_PLAN.md`
