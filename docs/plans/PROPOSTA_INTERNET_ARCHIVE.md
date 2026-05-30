# Proposta de Consolidação do Internet Archive em Ranges de 1.000 Leis

Este documento detalha o racional, a arquitetura e a lógica por trás da proposta de transição do modelo de armazenamento do **Leizilla** no Internet Archive (IA). Substituímos o fluxo de **um item individual por lei** por um modelo consolidado de **faixas de 1.000 chaves sequenciais (ranges)** por ente e fonte.

---

## 🗺️ 1. O Diagnóstico e o Problema Atual

Atualmente, o Leizilla está estruturado sob a premissa de que cada lei descoberta vira um item individual no catálogo do Internet Archive com a nomenclatura:
`leizilla-raw-{ente}-{fonte}-{chave}` (ex: `leizilla-raw-ro-casacivil-coddoc-05120`).

O banco de dados local DuckDB (`leizilla.duckdb`) já possui **51.442 recursos descobertos de Rondônia** (distribuídos em leis ordinárias, leis complementares, decretos e outros documentos).

### Os Impactos da Fragmentação no Modelo Individual:
1. **Poluição de Catálogo no IA**: Gerar mais de 50.000 itens distintos apenas para um estado (Rondônia) é ineficiente. A nível nacional (26 estados + DF + Federal), isso resultaria em milhões de itens, com altíssimo risco de bloqueio de conta por spam, abuso ou limites severos de taxa de API (rate limiting).
2. **Distribuição em Lote Inviável**: Um dos grandes trunfos do Internet Archive é a geração automática de arquivos `.torrent` e arquivos `.zip` para download em lote de coleções. Se cada lei for um item separado, o usuário precisará gerenciar milhares de conexões de torrent.
3. **Lentidão nas APIs**: Listar os itens via API do IA para controle e checagem torna-se lento e instável devido ao volume massivo de requisições individuais.

---

## ⚡ 2. A Solução Proposta: Ranges Genéricos de 1.000

Em vez de criar um item no IA para cada lei, **consolidaremos os uploads em faixas de 1.000 chaves sequenciais da fonte de dados**, independente do tipo de norma.

### 🧠 O Desafio Arquitetural do "Timing de Tipagem" e a Chave "coddoc"
Em fontes como Rondônia (Casa Civil e Assembleia), o crawler do Leizilla descobre as leis através de chaves sequenciais da fonte, chamadas no sistema de **`coddoc`** (ex: `coddoc-05120`). O tipo jurídico exato da norma (se é uma lei ordinária, complementar, ou decreto) é **desconhecido** no momento do discovery e do download bruto — ele só é determinado *após* o parse de OCR processado pela LLM.

Como o upload bruto precisa acontecer *antes* de sabermos o tipo da norma para que o IA possa gerar o OCR, **o agrupamento nos ranges deve ser estritamente genérico e baseado na chave sequencial de colheita**.

### Nomenclatura Unificada e Genérica dos Itens de Ranges:
`leizilla-{ente}-{fonte}-{range_inicio:04d}-{range_fim:04d}`

#### Exemplos Práticos (Rondônia):
* **Chaves de Colheita 1 a 1000**:
  `leizilla-ro-casacivil-0001-1000`
* **Chaves de Colheita 5001 a 6000**:
  `leizilla-ro-casacivil-5001-6000`

> [!NOTE]
> Essa abordagem é a mais correta e honesta: ela assume que os ranges são heterogêneos (guardam leis e decretos misturados na sequência da fonte), eliminando nomenclaturas opacas ou termos técnicos de crawler (como `coddoc`) do catálogo público do IA. A tipagem jurídica de alta fidelidade semântica é salva no DuckDB e nos datasets exportados (Parquet/JSON) após a fase de parse.

### Como os Arquivos São Organizados dentro de Cada Item:
Ao fazer o upload dos arquivos para o item do range, renomeamos os arquivos individuais usando sua chave de discovery para evitar colisões:
* **PDF da Lei**: `{chave}.pdf` (ex: `coddoc-05120.pdf`)
* **HTML da Lei (se aplicável)**: `{chave}.html` (ex: `coddoc-05120.html`)
* **Metadados Individuais**: `{chave}_meta.json` (ex: `coddoc-05120_meta.json`)

---

## 🧠 3. Lógica do Processamento de OCR no Internet Archive

O Internet Archive possui uma engine interna de processamento de tarefas em segundo plano chamada **derivação (`derive`)**. Quando vários PDFs são enviados para o mesmo item consolidado, a tarefa `derive` roda de forma **independente para cada arquivo PDF**.

Ao enviar 1.000 PDFs para o item `leizilla-ro-casacivil-5001-6000`, o IA gerará na pasta de downloads:
* `coddoc-05001_djvu.txt` (OCR do arquivo 5001)
* `coddoc-05002_djvu.txt` (OCR do arquivo 5002)
* ...
* `coddoc-06000_djvu.txt` (OCR do arquivo 6000)

### O Impacto para o Leizilla:
Nós **não** precisamos baixar o item inteiro ou descompactar um ZIP imenso para extrair o texto de uma única lei! Podemos fazer uma requisição HTTP direta de arquivo único (serverless de custo zero):
`https://archive.org/download/leizilla-ro-casacivil-5001-6000/coddoc-05120_djvu.txt`

---

## 🔄 4. Preservação de Retrocompatibilidade e Resolvedor Determinístico

Para evitar quebrar a CLI, as tabelas locais do DuckDB ou a suíte de testes unitários existente (480+ testes), as chamadas e consultas no banco local continuam referenciando as leis pelo seu `raw_id` clássico por lei (ex: `leizilla-raw-ro-casacivil-coddoc-05120`).

O motor do Leizilla traduz de forma transparente as chaves:

1. O ID é recebido pelo motor (`fetch_ocr` ou `fetch_ia_html`).
2. Uma função utilitária em `ia_utils.py` baseada em **entes suportados conhecidos do catálogo** (`list_slugs()`) mapeia dinamicamente onde termina o ente, onde está a fonte e onde está a chave.
3. Se a chave for numérica sequencial, ela é mapeada para o range correspondente.
4. **Resolução de Fallback**: Se a chave da lei for não-numérica, o resolvedor mapeia a URL para o item consolidado de fallback (`leizilla-raw-{ente}-{fonte}-fallback`), prevenindo falhas silenciosas de leitura.

---

## 🛠️ 5. Resumo Técnico da Refatoração Concluída

As modificações de código foram aplicadas mantendo um alto rigor de qualidade:

1. **`src/leizilla/ia_utils.py` [NEW]**: Centraliza `parse_chave_numeric`, `get_range_bounds`, `get_range_identifier` e `resolve_ia_id_to_url`, eliminando importações circulares e duplicações.
2. **`src/leizilla/publisher.py`**: Limpado e refatorado para importar e usar o `get_range_identifier` de `ia_utils.py`, operando sob a nomenclatura de ranges genéricos.
3. **`src/leizilla/parser.py`**: Limpado de toda a duplicação em `fetch_ocr` e `fetch_ia_html`, que agora delegam a montagem de URLs para o resolvedor centralizado e limpo no topo do módulo.
4. **`tests/test_ia_utils.py` [NEW]**: Adicionada cobertura unitária estrita e direta para testar todas as bordas dos utilitários de ranges e resolvedor unificado.
5. **`tests/test_parser.py`**: Refatorado para utilizar o `resolve_ia_id_to_url` na montagem e validação dos mocks de requisição, eliminando strings hardcoded estáticas.
6. **Integração Contínua (CI)**: O workflow `.github/workflows/lint.yml` foi otimizado adicionando cache inteligente de dependências de Python (`setup-uv`) e checagem rígida de lockfile (`uv lock --locked`) para garantir builds limpas.
