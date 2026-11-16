# ADR-0017 — Catálogo oficial como produto: ementas, situação e relações entre normas

**Status**: Proposta (direção do owner, 2026-11-16); implementada, primeira publicação pendente
**Data**: 2026-11-16
**Contexto**: frente `official-catalog-product` no DAG (`docs/okf/project-dag.md`)
**Relaciona-se com**: [ADR-0011](0011-raw-identity-keyed-range-items.md) (identidade),
[ADR-0014](0014-same-origin-dataset-mirror.md) (espelho same-origin),
[ADR-0015](0015-camada-de-texto-desacoplada.md) (camada de texto), `docs/SCHEMA.md` §3.6 e §3.7,
`src/leizilla/catalogo.py`, `src/leizilla/relacoes.py`

## Contexto

As listas anuais da Casa Civil de Rondônia trazem, para cada norma, número, data, **ementa** e os
arquivos com suas rendições (original, compilada, revogado, retificado). O Leizilla as lia só para
descobrir PDFs e medir completude. Resultado no portal: uma norma só-texto era achada apenas pelo
número e aparecia como "Lei Ordinária nº 80", sem ano nem descrição; nada dizia o que cada norma
altera ou o que a altera.

## Decisão

Tornar o índice oficial um produto público, **independente de OCR e de qualquer modelo**.

### 1. Tabela: o livro-razão estendido, não uma segunda tabela

O livro-razão `completude` (§3.6) já tem uma linha por norma oficial com título, data, ano, ementa,
`coddoc`, arquivos e flags de estágio. Uma tabela `catalogo` separada repetiria quase todas as
colunas e precisaria ser mantida em sincronia. Em vez disso o livro-razão ganha **colunas
aditivas** (versão 0.1 → 0.2): `identidade_incerta`, `rendicoes`, `situacao_norma`,
`situacao_evidencias`, `busca`, `url_oficial`, `url_ia`, `link_publico`. Quem lia 0.1 continua
lendo. A chave estável é `norma_id`.

Nome: `situacao` já existe no livro-razão com outro sentido (presença no índice: `listada`,
`fora-do-indice`…). O estado da norma segundo o índice chama-se `situacao_norma`. **Decisão a
confirmar pelo owner** (o pedido sugeria `situacao`).

O portal lê o mesmo arquivo, espelhado como `catalogo.parquet` (só linhas `listada` entram na
busca). A tabela de **relações** é nova de fato (grão diferente) — §3.7.

### 2. Situação da norma — só o que o índice mostra

`situacao_norma`, por prioridade:

- `revogada`: o índice lista um arquivo de rendição `revogado` **ou** a ementa traz a anotação
  editorial "REVOGADO PELO …" (total, não "parcialmente");
- `retificada`: o índice lista um arquivo `retificado`;
- `tem-compilada`: o índice lista versão compilada/consolidada;
- `sem-indicacao-de-revogacao`: nenhuma das marcas. **Não significa vigente**; só que o índice
  não marca revogação. O portal não mostra selo nesse caso.

`situacao_evidencias` lista todas as marcas encontradas. A situação nunca é uma conclusão de
vigência (fora de escopo).

### 3. Busca

`busca` = título + ementa normalizados (minúsculas, sem acento, não-alfanumérico vira espaço),
pelo mesmo algoritmo no pipeline (`normalizar_busca`) e no portal (`normalizarBusca`), com os
mesmos casos de teste nos dois lados. O portal materializa o catálogo em tabela do DuckDB-WASM e
procura cada termo como início de palavra; termo numérico casa o número exato ou a palavra
inteira. Relevância: número exato, frase, título exato ("lei 80" → Lei nº 80 antes da LC nº 80);
sem consulta, mais recentes primeiro.

### 4. Relações por regras (`relacoes`)

Gramática de expressões regulares sobre a ementa, sem modelo. Verbos canônicos: `altera`,
`revoga`, `acrescenta`, `da-nova-redacao`, `regulamenta`, `prorroga`, `outro` (retifica, suspende,
restabelece, convalida, ratifica, derroga, suprime, interpreta). `parcial` marca quando o alvo é
parte da norma (art., inciso, anexo…) — "revoga o art. 5º" não revoga a lei.

Regras de precisão (precisão antes de cobertura):

- só se lê número depois de uma palavra de tipo (arts. 3º e 4º nunca viram norma);
- o escopo do verbo termina em oração relativa ("que…") ou particípio passivo ("alterada
  pela…", "aprovado pelo…", "instituído pela…"), em verbo desconhecido coordenado ("e cria…") e
  em complemento de fundamento ("nos termos da…", "para…"); texto entre aspas é ignorado;
- listas ("Leis nºs 100, 200 e 300", "n° 121, de …, e n° 315"), datas por extenso, numéricas e
  só o ano, "LC 68/92", sufixo de letra ("9A");
- anotação do índice "REVOGADO PELO X" vira relação com origem X, **só se X resolve** no catálogo.

Resolução: tipo + número + data. `resolvida` (`alvo_id` preenchido), `nao-resolvida` (nota:
`federal`, `municipal`, `constituicao-*`, `tipo-sem-indice`, `ausente-do-indice`,
`data-diverge`, `data-ilegivel`, `cronologia`, `autorreferencia`) ou `ambigua`
(`sufixo-diverge`, `identidade-incerta`). Mesmo ano com dia/mês diferentes resolve, com nota
`data-diverge-mesmo-ano` (o índice tem erros de digitação de data); ano diferente não resolve.
Uma norma não altera outra posterior. Normas com `identidade_incerta` entram, marcadas.

### 5. Publicação

`leizilla completeness` grava `completeness.parquet`, `relacoes.parquet` e `completeness.json`
(`--sem-ia` dispensa o Internet Archive; flags de estágio ficam NULL). `leizilla release-catalogo`
valida o contrato (colunas, unicidade, domínios, integridade referencial, coerência
`confianca`/`alvo_id`) e o **piso** de normas listadas do `completeness.json` já publicado
(fail-closed se o piso não puder ser lido; `--allow-lower-count` só para queda verificada) e envia
ao item `-latest` do dataset. Workflow próprio, diário, `catalogo-oficial.yml` (não depende de
`parse-release.yml`): reaproveita o snapshot das listas e rebusca só os 2 anos recentes (~1 req/s,
robots.txt respeitado). `deploy-web.yml` espelha os arquivos same-origin, fail-open.

### 6. Portal

Busca da home sobre todo o catálogo (ementa/título/número, filtros de tipo, década e ano), selo de
estágio (só catálogo → preservada → legível → estruturada) e de situação. Página da norma: título,
data, ementa, situação, links oficial e IA, relações nos dois sentidos; relação não resolvida é
texto, sem link. Aviso fixo: títulos, ementas e situação vêm do índice; relações são extração
automática e podem estar incompletas.

## Fora de escopo

Busca no corpo das normas; relações lidas do corpo da norma; qualquer afirmação de vigência;
alterações de "Regulamento aprovado por Decreto" (RICMS etc.: o alvo é o regulamento, não o
decreto que o aprovou); referências por "de que trata", "prevista na", "autorizada pela".

## Medido × assumido

Medido em 2026-11-16 sobre o índice real (179 listas anuais, 157 requisições ao vivo, 39.501
normas: 31.558 decretos, 6.518 leis, 1.351 LC, 74 decretos-leis; ementa preenchida em 39.500):
situação `revogada` 2.118, `tem-compilada` 511, `retificada` 88; 8.309 relações (8.134 resolvidas,
171 não resolvidas, 4 ambíguas). Precisão lida à mão em amostras aleatórias de 60 relações:
58/60 antes das correções, 60/60 e 60/60 depois (três casos de leitura "alterar a composição de
órgão nomeado pelo Decreto X" contados como corretos). Cobertura: de 7.310 ementas com verbo e
4.604 que citam norma, 517 não geram relação (304 por "aprovado/instituído pelo…", por desenho).
Busca no Chromium headless: 50–120 ms por consulta; ~3–4 s até o primeiro resultado (init do
DuckDB-WASM + espelho de 2,6 MB). **Assumido**: estágio (preservada/legível/estruturada) só foi
verificado com flags simuladas; o upload, os workflows e o espelho não foram executados.
