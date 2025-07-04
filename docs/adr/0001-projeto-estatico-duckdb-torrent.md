# ADR 0001: Internet Archive como Pilar Central da Arquitetura Distribuída

**Data:** 2025-06-27  
**Status:** Aceito  
**Responsáveis:** Franklin Baldo  
**Contexto:** Pré-MVP, definição arquitetural fundamental

## Contexto

### Problema Identificado

A indexação de legislação brasileira enfrenta desafios técnicos e econômicos significativos:

1. **Custos de OCR**: Processar milhares de PDFs jurídicos com serviços comerciais pode custar centenas ou milhares de dólares mensalmente
2. **Infraestrutura de armazenamento**: Manter terabytes de PDFs e dados processados exige recursos computacionais contínuos
3. **Distribuição resiliente**: Garantir acesso permanente e distribuído aos dados sem pontos únicos de falha
4. **Transparência radical**: Assegurar que tanto dados quanto metadados sejam publicamente auditáveis

### Validação Prévia: Experiência do CausaGanha

O projeto [CausaGanha](https://github.com/franklinbaldo/causaganha) comprovou a viabilidade técnica desta arquitetura ao processar **21+ anos de decisões judiciais** (2004-2025) com:

- **5.058+ diários oficiais** processados via Internet Archive
- **OCR gratuito** de milhares de PDFs complexos
- **Shared database distribuída** via IA com sistema de locks
- **Pipeline async** com processamento simultâneo
- **Torrent automático** para distribuição P2P
- **Zero custos operacionais** de infraestrutura

## Decisão

### Internet Archive como Fundação Arquitetural

O Leizilla adotará o **Internet Archive como pilar central** da arquitetura, replicando e refinando o modelo validado pelo CausaGanha:

#### 1. **OCR Gratuito e Automático**

- **Upload de PDFs** → IA executa OCR automaticamente
- **Economia estimada**: US$ 2.000-5.000/mês vs serviços comerciais como AWS Textract
- **Qualidade comprovada**: CausaGanha processou documentos jurídicos complexos com 95%+ precisão

#### 2. **Armazenamento Permanente e Distribuído**

- **Durabilidade infinita**: IA garante preservação digital permanente
- **Acesso global**: CDN mundial com URLs públicas
- **Custo zero**: Hospedagem gratuita para dados de interesse público

#### 3. **Distribuição P2P Nativa**

- **Torrent automático**: IA gera .torrent para cada dataset
- **Resiliência**: Acesso descentralizado mesmo se IA ficar indisponível
- **Escalabilidade**: Distribuição cresce com adoção

#### 4. **Shared Database Distribuída**

- **DuckDB via IA**: Database unificado hospedado no IA
- **Sistema de locks**: Evita conflitos em ambiente distribuído
- **Cross-platform**: Acesso desde desenvolvimento local até GitHub Actions

### Fluxo de Dados Detalhado

```
1. CRAWL & COLLECT
   Playwright → PDFs Oficiais (.gov.br)
   ↓
2. IMMEDIATE ARCHIVAL
   PDF Upload → Internet Archive → OCR Trigger
   ↓
3. OCR PROCESSING
   IA OCR Engine → Texto Extraído → Torrent Generation
   ↓
4. ETL PROCESSING
   Texto IA → DuckDB Local → Normalização → Estruturação
   ↓
5. SHARED DATABASE
   DuckDB Local → IA Shared DB → Lock Management
   ↓
6. DATASET PUBLICATION
   Parquet + JSONL → IA Mirror → GitHub Releases → Torrent Distribution
   ↓
7. CLIENT-SIDE SEARCH
   DuckDB-WASM → Parquet Files → SQL Queries → Browser Interface
```

### Componentes Arquiteturais

#### **Pipeline de Processamento**

- **Python 3.12** + **Playwright** para crawling robusto
- **AnyIO** para processamento assíncrono
- **DuckDB** para ETL local e staging
- **Internet Archive CLI** para upload e sync

#### **Formatos de Dados**

- **Parquet**: Analytics otimizado (DuckDB nativo)
- **JSON Lines**: Pipeline interoperável
- **Torrent**: Distribuição P2P automática

#### **Distribuição Multi-Canal**

- **Primary**: Internet Archive (permanente)
- **Mirror**: GitHub Releases (versionado)
- **P2P**: Torrents (descentralizado)

## Alternativas Consideradas e Rejeitadas

### 1. **Backend Tradicional + OCR Comercial**

- **Custos**: US$ 500-2000/mês (AWS Textract + RDS + EC2)
- **Complexidade**: Gerenciamento de infraestrutura contínuo
- **Escalabilidade**: Limitada por orçamento
- **Transparência**: Dados em silos privados
- **Rejeitado**: Custos proibitivos e complexidade desnecessária

### 2. **GraphQL + Headless CMS**

- **Custos**: US$ 100-500/mês (Strapi + hosting)
- **Performance**: Latência de rede para queries
- **OCR**: Ainda precisaria de serviço externo caro
- **Rejeitado**: Não resolve problema fundamental de custos

### 3. **Solução Pure P2P (IPFS)**

- **Descoberta**: Complexidade de discovery de conteúdo
- **Disponibilidade**: Dependente de nodes voluntários
- **OCR**: Sem solução integrada
- **Rejeitado**: Muito experimental para dados críticos

## Consequências

### **Positivas (Validadas pelo CausaGanha)**

#### **Econômicas**

- **Zero custos de OCR**: Economia de US$ 24.000-60.000/ano vs comercial
- **Zero custos de hosting**: IA oferece armazenamento gratuito ilimitado
- **Zero custos de CDN**: Distribuição global incluída

#### **Técnicas**

- **Performance superior**: DuckDB local + Parquet > queries remotas
- **Resiliência comprovada**: CausaGanha opera 24/7 há meses sem downtime
- **Escalabilidade validada**: Processa datasets de 21+ anos automaticamente

#### **Transparência**

- **Auditabilidade total**: Todos PDFs e dados publicamente acessíveis
- **Versionamento**: Histórico completo de mudanças via IA
- **Reprodutibilidade**: Pipeline determinístico e documentado

### **Desafios e Mitigações**

#### **Dependência do Internet Archive**

- **Risco**: IA indisponível temporariamente
- **Mitigação**: Torrents + GitHub Releases como backup
- **Mitigação**: Pipeline local funciona offline

#### **Complexidade de Sincronização**

- **Risco**: Conflitos em ambiente distribuído
- **Mitigação**: Sistema de locks testado no CausaGanha
- **Mitigação**: Retry logic + exponential backoff

#### **Limitações de Busca Client-Side**

- **Risco**: Queries complexas podem ser lentas no browser
- **Mitigação**: Índices pré-computados em DuckDB
- **Mitigação**: Paginação e lazy loading

### **Riscos Específicos e Planos de Contingência**

#### **OCR Quality Issues**

- **Monitoramento**: Automated quality checks via sampling
- **Fallback**: Manual correction pipeline para casos críticos
- **Backup**: PyMuPDF local como OCR secundário

#### **IA Rate Limiting**

- **Detection**: Monitor upload success rates
- **Response**: Batch size reduction + retry delays
- **Alternative**: Temporary local storage buffer

## Métricas de Sucesso

### **Econômicas**

- [ ] OCR cost: US$ 0/mês (vs US$ 2.000+ comercial)
- [ ] Storage cost: US$ 0/mês (vs US$ 500+ cloud)
- [ ] CDN cost: US$ 0/mês (vs US$ 200+ comercial)

### **Técnicas**

- [ ] OCR accuracy: >95% (validated by CausaGanha)
- [ ] Search latency: <2s para queries simples
- [ ] Dataset size: Parquet 50-80% menor que JSON equivalente

### **Operacionais**

- [ ] Uptime: >99% (sem SLA de servidor próprio)
- [ ] Processing throughput: >100 PDFs/dia automatizado
- [ ] Public availability: 100% dos dados acessíveis publicamente

## Plano de Implementação

### **Fase 1: Validação Técnica** (Q3/2025)

1. Setup básico de upload para IA
2. Teste de OCR com amostra de leis RO
3. Pipeline DuckDB local → IA sync
4. Validação de performance e qualidade

### **Fase 2: Pipeline Completo** (Q4/2025)

1. Crawler Playwright para fontes oficiais
2. ETL completo com normalização
3. Sistema de locks para shared database
4. GitHub Actions para automação

### **Fase 3: Frontend e Busca** (Q1/2026)

1. DuckDB-WASM integration
2. Frontend estático (HTML/CSS/JS)
3. SQL query interface
4. Parquet loading otimizado

## Considerações de Segurança

### **Dados Públicos por Design**

- **Transparência**: Todos dados são publicamente auditáveis
- **Privacy**: Apenas documentos já públicos são processados
- **Autenticidade**: Checksums e metadados preservam integridade

### **Acesso Distribuído**

- **Censorship Resistance**: Múltiplos canais (IA + Torrents + GitHub)
- **Availability**: P2P garante acesso mesmo com falhas centralizadas

## Referências Técnicas

- **CausaGanha**: Validação da arquitetura com 21+ anos de dados judiciais
- **Internet Archive OCR**: Serviço gratuito com tesseract + machine learning
- **DuckDB-WASM**: SQL analytics no navegador com performance nativa
- **BitTorrent**: Protocolo P2P resiliente para datasets grandes

---

**Esta decisão posiciona o Internet Archive como diferencial estratégico do Leizilla, validado pela experiência real do CausaGanha e otimizado para custo zero com transparência máxima.**
