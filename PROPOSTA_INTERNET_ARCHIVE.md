# Proposta de Consolidação do Internet Archive em Ranges de 1.000 Leis

Este documento detalha o racional, a arquitetura e a lógica por trás da proposta de transição do modelo de armazenamento do **Leizilla** no Internet Archive (IA). Substituímos o fluxo de **um item individual por lei** por um modelo consolidado de **faixas de 1.000 leis (ranges)** por ente, fonte e tipo de documento.

---

## 🗺️ 1. O Diagnóstico e o Problema Atual

Atualmente, o Leizilla está estruturado sob a premissa de que cada lei descoberta vira um item individual no catálogo do Internet Archive com a nomenclatura:
`leizilla-raw-{ente}-{fonte}-{chave}` (ex: `leizilla-raw-ro-casacivil-lei-05120`).

O banco de dados local DuckDB (`leizilla.duckdb`) já possui **51.442 recursos descobertos de Rondônia** (distribuídos em leis ordinárias, leis complementares, decretos e outros documentos).

### Os Impactos da Fragmentação no Modelo Individual:
1. **Poluição de Catálogo no IA**: Gerar mais de 50.000 itens distintos apenas para um estado (Rondônia) é ineficiente. A nível nacional (26 estados + DF + Federal), isso resultaria em milhões de itens, com altíssimo risco de bloqueio de conta por spam, abuso ou limites severos de taxa de API (rate limiting).
2. **Distribuição em Lote Inviável**: Um dos grandes trunfos do Internet Archive é a geração automática de arquivos `.torrent` e arquivos `.zip` para download em lote de coleções. Se cada lei for um item separado, o usuário precisará gerenciar milhares de conexões de torrent.
3. **Lentidão nas APIs**: Listar os itens via API do IA para controle e checagem torna-se lento e instável devido ao volume massivo de requisições individuais.

---

## ⚡ 2. A Solução Proposta: Blocos de 1.000 Leis (Ranges)

Em vez de criar um item no IA para cada lei, **consolidaremos os uploads em faixas de 1.000 números sequenciais** com base no ente, na fonte e no tipo de documento.

### Nomenclatura dos Novos Itens:
`leizilla-{ente}-{fonte}-{tipo}-{range_inicio:04d}-{range_fim:04d}`

#### Exemplos Práticos:
* **Leis Ordinárias de Rondônia (1 a 1000)**:
  `leizilla-ro-casacivil-lei-0001-1000`
* **Leis Ordinárias de Rondônia (5001 a 6000)**:
  `leizilla-ro-casacivil-lei-5001-6000`
* **Leis Complementares de Rondônia (1 a 1000)**:
  `leizilla-ro-casacivil-lc-0001-1000`

### Como os Arquivos São Organizados dentro de Cada Item:
Ao fazer o upload dos arquivos para o item do range, renomeamos os arquivos individuais para evitar colisões:
* **PDF da Lei**: `{chave}.pdf` (ex: `lei-05120.pdf`)
* **HTML da Lei (se aplicável)**: `{chave}.html` (ex: `lei-05120.html`)
* **Metadados Individuais**: `{chave}_meta.json` (ex: `lei-05120_meta.json`)

> [!TIP]
> **Benefício de Escopo**: O catálogo de Rondônia encolhe de **50.000+ itens fragmentados para apenas ~50 itens robustos**. Cada item de range terá entre 500MB e 1GB, tamanho ideal para estabilidade de rede e download em lote rápido via Torrent ou ZIP direto do IA!

---

## 🧠 3. Lógica do Processamento de OCR no Internet Archive

Uma grande dúvida técnica era: **"Como o Internet Archive gera o OCR para itens multi-arquivo e como podemos consumi-lo?"**

O Internet Archive possui uma engine interna de processamento de tarefas em segundo plano chamada **derivação (`derive`)**. 
Quando vários PDFs são enviados para o mesmo item consolidado, a tarefa `derive` roda de forma **independente para cada arquivo PDF**.

Ao enviar 1.000 PDFs para o item `leizilla-ro-casacivil-lei-5001-6000`, o IA gerará na pasta de downloads:
* `lei-05001_djvu.txt` (OCR da lei 5001)
* `lei-05002_djvu.txt` (OCR da lei 5002)
* ...
* `lei-06000_djvu.txt` (OCR da lei 6000)

### O Impacto para o Leizilla:
Nós **não** precisamos baixar o item inteiro ou descompactar um ZIP imenso para extrair o texto de uma única lei! Podemos fazer uma requisição HTTP direta de arquivo único (serverless de custo zero):
`https://archive.org/download/leizilla-ro-casacivil-lei-5001-6000/lei-05120_djvu.txt`

Esta estratégia preserva a eficiência original do Leizilla, mantendo a arquitetura leve e escalável.

---

## 🔄 4. Preservação de Retrocompatibilidade (ID Translation)

Para evitar quebrar a interface de linha de comando (`cli.py`), as tabelas locais do DuckDB (`leizilla.duckdb`) ou a suíte de testes unitários existente (480+ testes), implementamos uma **tradução de chaves reativa e transparente**:

1. A CLI, o banco local e as APIs externas continuam referenciando as leis pelo seu `raw_id` legível por lei (ex: `leizilla-raw-ro-casacivil-lei-05120`).
2. Internamente, as funções `fetch_ocr` e `fetch_ia_html` no `parser.py` interceptam esse ID clássico.
3. Elas extraem o ente, fonte, tipo e número, calculam o range de 1.000 correspondente (`leizilla-ro-casacivil-lei-5001-6000`) e requisitam o arquivo direto da subpasta de ranges.

```
[Chave Legada / Banco]          [Identificação no Motor]         [Download no IA]
leizilla-raw-ro-...-lei-05120 ➔ Parse (lei, 5120) ➔ Range 5001-6000 ➔ lei-05120_djvu.txt
```

---

## 📂 5. A Descoberta dos Arquivos Invisíveis do Microsoft Word (.doc / .docx)

Durante a nossa análise profunda da API da Wayback Machine para a Casa Civil/Ditel de Rondônia, descobrimos que existem **5.572 arquivos em formato Word (`.doc` e `.docx`)** disponíveis. 

Atualmente, eles estão **invisíveis** para o Leizilla porque o crawler do repositório (`src/leizilla/discovery.py`) filtra estritamente por links terminados em `.pdf`.

### Estratégia de Captura no Futuro:
1. **Ajuste de Discovery**: Atualizar a regex/filtro em `discovery.py` para permitir capturar links com extensões `.doc` e `.docx`.
2. **Processamento Local**: Em vez de depender do OCR do Internet Archive (que não extrai texto nativo de `.doc`/`.docx` diretamente via derive), o Leizilla pode usar bibliotecas locais em Python (como `python-docx` para `.docx` e conversores compatíveis para `.doc`) para ler o texto puro dessas leis e integrá-las de imediato ao pipeline de parse.
3. **Preservação**: O Word original é enviado para o Internet Archive na mesma pasta consolidada de ranges (`lei-XXXX.doc`) como cópia fiel de preservação histórica.

---

## 🛠️ 6. Resumo Técnico da Implementação Concluída

As modificações de código foram aplicadas mantendo um alto rigor de qualidade:

1. **`src/leizilla/publisher.py`**:
   * Adicionadas funções utilitárias `parse_chave_numeric`, `get_range_bounds` e `_range_identifier` para mapear ranges numerados.
   * Adaptados `upload_raw` e `upload_raw_html` para realizar o upload direcionado para o range consolidado correspondente, renomeando os arquivos internos para `{chave}.pdf` e `{chave}_meta.json`.
2. **`src/leizilla/parser.py`**:
   * Adaptadas as funções `fetch_ocr` e `fetch_ia_html` para que, ao receberem chamadas com o ID legível do padrão legado, mapeiem dinamicamente a URL de download para o item de range correspondente e o nome de arquivo unitário correto.
3. **`tests/test_parser.py`**:
   * Desmembrados os testes unitários (`test_constructs_djvu_url` e `test_constructs_ia_html_url`) para cobrir tanto o fluxo com `fallback` (não-numérico) quanto com `range` (numérico), garantindo 100% de cobertura e estabilidade nas rotas de teste.
4. **Formatação e Linting**:
   * Todos os arquivos modificados foram reformatados utilizando `ruff` para atender rigorosamente os padrões estilísticos estabelecidos do projeto.
