# ADR 0002: Frontend Estático Vanilla em vez de SvelteKit

**Data:** 2025-06-27  
**Status:** Aceito  
**Responsáveis:** Franklin Baldo  
**Contexto:** Correção de inconsistência e realinhamento com filosofia do projeto  

## Contexto

### Problema Identificado

A documentação atual menciona SvelteKit como framework frontend, mas isso contradiz os princípios fundamentais do Leizilla:

1. **Filosofia 100% Estática**: Leizilla prioriza simplicidade máxima e zero infraestrutura
2. **Complexidade Desnecessária**: SvelteKit adiciona build process, bundling, e dependencies extras
3. **Inconsistência Arquitetural**: Framework contraria objetivo de infra mínima
4. **DuckDB-WASM Suficiente**: Funcionalidade principal não requer framework

### Análise de Uso Real

O frontend do Leizilla tem requisitos específicos:
- **Carregar DuckDB-WASM**: Biblioteca JavaScript standalone
- **Interface SQL**: Formulário simples para queries
- **Mostrar resultados**: Tabela básica de dados
- **Download datasets**: Links diretos para Parquet/JSONL

## Decisão

### Frontend Vanilla HTML/JavaScript

O Leizilla adotará **Vanilla HTML/CSS/JavaScript** em vez de qualquer framework:

#### **1. Zero Build Process**
- **HTML estático** servido diretamente
- **CSS vanilla** para estilização
- **JavaScript ES6+** para DuckDB-WASM integration
- **Sem bundling** ou transpilação

#### **2. DuckDB-WASM Integration Direta**
```html
<!DOCTYPE html>
<html>
<head>
    <title>Leizilla - Busca em Leis Brasileiras</title>
    <script src="https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@latest"></script>
</head>
<body>
    <main>
        <h1>🦖 Leizilla</h1>
        <textarea id="sql-query" placeholder="SELECT * FROM leis WHERE..."></textarea>
        <button onclick="executarQuery()">Buscar</button>
        <div id="resultados"></div>
    </main>
</body>
</html>
```

#### **3. Arquitetura Minimalista**
```
frontend/
├── index.html          # Página principal
├── style.css          # Estilos básicos
├── app.js             # DuckDB-WASM integration
└── datasets/          # Links para Parquet files
```

## Alternativas Consideradas e Rejeitadas

### 1. **SvelteKit** ❌
- **Prós**: Developer experience, reatividade
- **Contras**: Build complexity, bundling, SSR não necessário
- **Rejeitado**: Contradiz filosofia de simplicidade

### 2. **React/Vue** ❌
- **Prós**: Ecossistema maduro
- **Contras**: Runtime overhead, build process
- **Rejeitado**: Overkill para interface simples

### 3. **Static Site Generators (11ty, Hugo)** ❌
- **Prós**: Geração estática
- **Contras**: Build step ainda necessário
- **Rejeitado**: HTML direto é mais simples

### 4. **Vanilla com CDN** ✅
- **Prós**: Zero complexity, máxima compatibilidade
- **Contras**: Sem developer experience moderno
- **Aceito**: Alinha perfeitamente com objetivos

## Consequências

### **Positivas**
- **Zero Build**: Apenas HTML/CSS/JS - funciona em qualquer servidor
- **Performance**: Sem JavaScript framework overhead
- **Manutenibilidade**: Qualquer dev entende HTML/JS vanilla
- **Compatibilidade**: Funciona até em browsers antigos
- **Deploy**: Qualquer CDN, GitHub Pages, etc.

### **Negativas**
- **Developer Experience**: Sem hot reload, components, etc.
- **Escalabilidade**: Se interface crescer muito, pode ficar complexa
- **Estado**: Gerenciamento manual de estado da aplicação

### **Mitigações**
- **Simplicidade por Design**: Interface será minimalista por princípio
- **Web Components**: Se precisar de componentização, usar padrão nativo
- **Modern JavaScript**: ES6+ modules para organização

## Implementação

### **Estrutura de Arquivos**
```
src/frontend/           # Frontend estático
├── index.html         # Interface principal
├── css/
│   └── leizilla.css   # Estilos básicos
├── js/
│   ├── duckdb.js      # DuckDB-WASM wrapper
│   ├── query.js       # Query execution
│   └── ui.js          # Interface interactions
└── datasets/
    └── index.json     # Metadata dos datasets
```

### **Tecnologias**
- **HTML5**: Estrutura semântica
- **CSS Grid/Flexbox**: Layout responsivo
- **JavaScript ES6+**: Modules, async/await
- **DuckDB-WASM**: SQL queries no browser
- **Web Workers**: Processing pesado off-main-thread

### **Integração com Pipeline**
- **GitHub Actions**: Copia arquivos estáticos para release
- **Datasets**: Links diretos para Parquet no IA/GitHub
- **Versionamento**: Frontend versionado junto com datasets

## Métricas de Sucesso

- [ ] **Load Time**: <2s para carregar página inicial
- [ ] **Bundle Size**: <100KB total (sem DuckDB-WASM)
- [ ] **Compatibility**: Funciona em 95%+ browsers modernos
- [ ] **Maintenance**: Qualquer dev consegue modificar em <30min

## Roadmap de Implementação

### **Q3/2025 - MVP Frontend**
1. HTML básico com formulário SQL
2. DuckDB-WASM integration
3. Exibição tabular de resultados
4. Download links para datasets

### **Q4/2025 - Melhorias UX**
1. Syntax highlighting para SQL
2. Query examples e templates
3. Filtros básicos por estado/data
4. Responsive design

### **Q1/2026 - Features Avançadas**
1. Query builder visual (se necessário)
2. Export de resultados
3. Share URLs para queries
4. Métricas de uso (client-side)

---

**Esta decisão realinha o frontend com os princípios fundamentais do Leizilla: simplicidade máxima, zero infraestrutura, e transparência total.**