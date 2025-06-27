# ADR 0003: Schema DuckDB para Indexação de Leis

**Data:** 2025-06-27  
**Status:** Aceito  
**Responsáveis:** Franklin Baldo  
**Contexto:** Definição de estrutura de dados para MVP  

## Contexto

### Necessidade de Schema Definido

O sistema precisa de uma estrutura de dados clara para armazenar leis brasileiras de forma eficiente e pesquisável:

1. **Busca Eficiente**: Índices apropriados para consultas rápidas
2. **Metadados Ricos**: Informações sobre origem, data, tipo de lei
3. **Texto Completo**: OCR extraído do Internet Archive
4. **Flexibilidade**: Schema que permita expansão futura
5. **Export Parquet**: Compatível com DuckDB → Parquet export

### Requisitos Funcionais

- **Identificação única** de cada lei
- **Busca por texto completo** no conteúdo
- **Filtros por data, origem, tipo**
- **Metadados estruturados** (JSON flexível)
- **Versionamento** de dados
- **Performance** para queries client-side

## Decisão

### Schema Principal: Tabela `leis`

```sql
CREATE TABLE leis (
  -- Identificação única
  id VARCHAR PRIMARY KEY,                    -- Format: "{origem}-{tipo}-{ano}-{numero}"
  
  -- Metadados básicos
  titulo TEXT NOT NULL,                      -- Título/ementa da lei
  numero VARCHAR,                            -- Número oficial da lei
  ano INTEGER,                              -- Ano de publicação
  data_publicacao DATE,                     -- Data oficial de publicação
  tipo_lei VARCHAR,                         -- "lei", "decreto", "portaria", etc.
  origem VARCHAR NOT NULL,                  -- "rondonia", "federal", "sao_paulo", etc.
  
  -- Conteúdo
  texto_completo TEXT,                      -- OCR completo do Internet Archive
  texto_normalizado TEXT,                   -- Texto limpo para busca
  
  -- Metadados extensíveis
  metadados JSON,                           -- Flexível: autores, tags, links, etc.
  
  -- URLs e referências
  url_original VARCHAR,                     -- URL da fonte oficial
  url_pdf_ia VARCHAR,                       -- URL do PDF no Internet Archive
  url_ocr_ia VARCHAR,                       -- URL do texto OCR no IA
  
  -- Controle interno
  hash_conteudo VARCHAR,                    -- Hash SHA-256 do conteúdo para deduplicação
  status VARCHAR DEFAULT 'ativo',          -- 'ativo', 'revogado', 'suspenso'
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Índices para Performance

```sql
-- Índices para busca
CREATE INDEX idx_leis_origem ON leis(origem);
CREATE INDEX idx_leis_ano ON leis(ano);
CREATE INDEX idx_leis_data ON leis(data_publicacao);
CREATE INDEX idx_leis_tipo ON leis(tipo_lei);
CREATE INDEX idx_leis_status ON leis(status);

-- Índice composto para queries comuns
CREATE INDEX idx_leis_origem_ano ON leis(origem, ano);
CREATE INDEX idx_leis_origem_tipo ON leis(origem, tipo_lei);

-- Full-text search (quando DuckDB suportar)
-- CREATE INDEX idx_leis_texto ON leis USING gin(to_tsvector('portuguese', texto_normalizado));
```

### Formato do ID

O `id` segue padrão estruturado para facilitar identificação:

```
{origem}-{tipo}-{ano}-{numero}

Exemplos:
- "rondonia-lei-2023-001"
- "federal-decreto-2024-11123"  
- "rondonia-portaria-2025-045"
```

### Schema Metadados JSON

```json
{
  "autores": ["Governador", "Deputado X"],
  "orgao_origem": "Assembleia Legislativa",
  "tags": ["meio ambiente", "licenciamento"],
  "leis_relacionadas": ["rondonia-lei-2022-015"],
  "revoga": ["rondonia-lei-2020-003"],
  "situacao_tramitacao": "promulgada",
  "observacoes": "Alterada pela Lei 2024-002",
  "hash_original": "sha256:abc123...",
  "tamanho_pdf": 1245760,
  "paginas": 15,
  "qualidade_ocr": 0.94
}
```

## Alternativas Consideradas

### 1. **Schema Normalizado (Múltiplas Tabelas)**
- **Prós**: Normalização perfeita, sem redundância
- **Contras**: Joins complexos para DuckDB-WASM client-side
- **Rejeitado**: Complexidade desnecessária para MVP

### 2. **Schema Document-Based (Apenas JSON)**
- **Prós**: Máxima flexibilidade
- **Contras**: Queries SQL complexas, sem índices estruturados
- **Rejeitado**: Performance ruim para busca

### 3. **Schema Flat (Apenas Colunas)**
- **Prós**: Simplicidade máxima
- **Contras**: Inflexível, difícil extensão
- **Rejeitado**: Não suporta metadados ricos

## Consequências

### **Positivas**
- **Performance**: Índices otimizados para queries comuns
- **Flexibilidade**: JSON metadados permite extensão
- **Simplicidade**: Uma tabela principal, fácil entendimento
- **Parquet Export**: Schema traduz bem para formato colunar
- **Client-Side**: Queries SQL simples no DuckDB-WASM

### **Negativas**
- **Denormalização**: Alguma redundância em metadados
- **Tamanho**: JSON pode aumentar tamanho do dataset
- **Migração**: Mudanças de schema requerem reprocessamento

### **Mitigações**
- **Versionamento**: Controle de schema via migrations
- **Compressão**: Parquet comprime JSON eficientemente
- **Validação**: Schema validation nos metadados JSON

## Migrations e Versionamento

### **Migration 001: Schema Inicial**
```sql
-- 001_create_leis_table.sql
CREATE TABLE leis (
  id VARCHAR PRIMARY KEY,
  titulo TEXT NOT NULL,
  numero VARCHAR,
  ano INTEGER,
  data_publicacao DATE,
  tipo_lei VARCHAR,
  origem VARCHAR NOT NULL,
  texto_completo TEXT,
  texto_normalizado TEXT,
  metadados JSON,
  url_original VARCHAR,
  url_pdf_ia VARCHAR,
  url_ocr_ia VARCHAR,
  hash_conteudo VARCHAR,
  status VARCHAR DEFAULT 'ativo',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices
CREATE INDEX idx_leis_origem ON leis(origem);
CREATE INDEX idx_leis_ano ON leis(ano);
CREATE INDEX idx_leis_data ON leis(data_publicacao);
CREATE INDEX idx_leis_tipo ON leis(tipo_lei);
CREATE INDEX idx_leis_status ON leis(status);
CREATE INDEX idx_leis_origem_ano ON leis(origem, ano);
CREATE INDEX idx_leis_origem_tipo ON leis(origem, tipo_lei);
```

### **Migration Strategy**
- **Semantic Versioning**: Schema versionado junto com código
- **Backward Compatibility**: Mudanças não-breaking quando possível
- **Data Migration**: Scripts para converter dados existentes

## Implementação

### **Queries Comuns (MVP)**

```sql
-- Buscar todas leis de Rondônia em 2025
SELECT id, titulo, data_publicacao 
FROM leis 
WHERE origem = 'rondonia' AND ano = 2025 
ORDER BY data_publicacao DESC;

-- Busca textual simples
SELECT id, titulo, ano
FROM leis 
WHERE texto_normalizado LIKE '%meio ambiente%'
AND origem = 'rondonia';

-- Estatísticas por ano
SELECT ano, COUNT(*) as total_leis
FROM leis 
WHERE origem = 'rondonia'
GROUP BY ano 
ORDER BY ano DESC;

-- Leis revogadas
SELECT id, titulo, metadados->>'revoga' as revoga
FROM leis 
WHERE JSON_EXTRACT(metadados, '$.revoga') IS NOT NULL;
```

### **Export Parquet**
```sql
-- Export para distribuição
COPY leis TO 'datasets/leis_rondonia_2025.parquet' 
(FORMAT PARQUET, COMPRESSION SNAPPY)
WHERE origem = 'rondonia' AND ano = 2025;

-- Export metadados separado
COPY (
  SELECT id, titulo, ano, tipo_lei, data_publicacao, origem, status
  FROM leis
) TO 'datasets/metadata_leis.parquet' (FORMAT PARQUET);
```

## Métricas de Sucesso

- [ ] **Query Performance**: <100ms para busca por origem+ano
- [ ] **Storage Efficiency**: <1MB por 100 leis em Parquet
- [ ] **Client-Side Performance**: <2s para carregar 1000 leis no browser
- [ ] **Flexibility**: Metadados JSON suporta 95% dos casos sem schema change

---

**Este schema balança simplicidade, performance e flexibilidade para suportar o crescimento do Leizilla de MVP para sistema completo.**