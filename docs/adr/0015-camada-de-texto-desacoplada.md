# ADR-0015 — Camada de texto: tabela `textos` desacoplada de `versoes`

**Status**: Aprovada (decisão do owner, 2026-11-14); implementada, primeira publicação pendente
**Data**: 2026-11-14
**Contexto**: `text-layer-publication` no DAG do projeto (`docs/okf/project-dag.md`);
relaciona-se com `boundary-decision-parser`
**Relaciona-se com**: [ADR-0001](0001-projeto-estatico-duckdb-torrent.md) (IA como pilar
central), [ADR-0011](0011-raw-identity-keyed-range-items.md) (identidade raw),
[ADR-0014](0014-same-origin-dataset-mirror.md) (espelho same-origin), `docs/SCHEMA.md` §3.5,
`src/leizilla/textlayer.py`, `src/leizilla/article_sequence.py`

## Contexto

O portal só mostra o que está na tabela `versoes`, e só entra em `versoes` a norma que
passou pelo parse estruturado (S4). "Ler a lei sem abrir um PDF" — a primeira promessa do
projeto — ficou acoplada a "estruturar a lei", que é a etapa mais cara e mais instável do
pipeline.

Medição de 2026-11-14 (somente leitura, Internet Archive, Rondônia/casacivil):

| Estágio | Normas |
|---|---|
| Identidades preservadas (S2) | 2361 |
| Com `_djvu.txt` derivado pelo IA (S3) | 2115 |
| Estruturadas e publicadas (S4) | ~30 |

Cerca de 2 mil normas têm texto pronto no IA e são invisíveis no portal.

## Decisão

**Publicar o texto de S3 numa tabela própria, `textos`, separada de `versoes`.** Estrutura
passa a ser um aprimoramento progressivo, não uma catraca de publicação.

- **Grão e chave**: uma linha por norma, chave = identidade raw `(ente, fonte, tipo,
  numero)`, materializada em `texto_id` (o raw_id legado, `leizilla-raw-{ente}-{fonte}-{tipo}-{numero:05d}`).
  A linha carrega o hash do arquivo de origem (`sha256_fonte`, do `index.csv`), que diz de
  qual captura o texto veio. Havendo várias capturas, vence a mais recente **que já tem
  `_djvu.txt`** (uma captura nova ainda sem OCR não tira a norma do ar).
- **Texto verbatim**: a coluna `texto` é o `_djvu.txt` do IA decodificado, sem limpeza,
  normalização ou correção. `sha256_texto` é o hash dos bytes baixados; `sha1_texto_ia` é o
  hash que o IA declara para o arquivo, conferido no download.
- **Proveniência do OCR**: motor e versão (`ocr_motor`, ex. `tesseract 5.3.0-6-g76ae`),
  versão do módulo e parâmetros, lidos do metadata do IA por arquivo, mais a data da
  derivação. `capturado_em` é a data de captura do PDF de origem.
- **Elo com o original**: `ia_item`, `pdf_url` (PDF preservado no IA) e `texto_url`.
- **Marca de qualidade explícita**: `qualidade = 'texto-nao-estruturado'` em toda linha.
- **Escopo desta versão**: só OCR derivado de PDF. Fonte HTML nativa fica para quando
  houver uma (exigiria extrair texto de HTML, que não é verbatim).

O elo com `versoes` não precisa de coluna nova: `versoes.fontes[].ia_id` já registra o
raw_id. Uma norma é "só texto" quando seu `texto_id` não aparece em nenhuma `fontes`.

Construção: `leizilla build-textos` (enumeração de itens de range → `index.csv` →
metadata do item → download sequencial com pausa e retry; `--previous` reaproveita linhas
cujo arquivo de origem e OCR não mudaram). Publicação: `leizilla release-textos`.

## Âncoras de artigo

Os offsets dos marcadores de artigo são calculados por
`leizilla.article_sequence.read_articles` e gravados como **dado derivado**:

- `ancoras`: JSON com `{n, sufixo, ini, fim}` por artigo próprio da norma; offsets em code
  points Unicode sobre o `texto` verbatim.
- `artigos_fecham`: `true` quando a sequência fecha (cadeia completa 1..N e nenhum
  candidato sem explicação). `artigos_total` e `artigos_ultimo` resumem a leitura.

O texto **nunca é reescrito**: quando o leitor decide que `Art. 42` é o art. 4º, isso vira
uma âncora com `n = 4` sobre o trecho original, não uma correção do texto. As âncoras são
recalculadas a cada construção, então melhorar o leitor melhora a navegação sem mexer no
texto. Com a leitura atual, a sequência fecha em 1689 das 2115 normas (79,9%).

## Portal

- Rota de leitura: a mesma `/lei/?id=…`; um `id` que é raw_id (`leizilla-raw-…`) abre a
  leitura da camada de texto.
- Selo visível **"texto não estruturado"** na página e nos cartões da listagem, com a
  explicação de que é OCR sem revisão.
- Link para o PDF preservado no IA sempre presente, junto com item, hash e motor de OCR.
- Âncoras viram navegação por artigo **somente quando `artigos_fecham`**; caso contrário o
  texto aparece corrido.
- A listagem da home inclui as normas só-texto depois das estruturadas. Norma com versão
  estruturada aparece uma vez só, pela versão estruturada; a página de texto dela aponta
  para a estruturada.
- Leitura pelo DuckDB-WASM do espelho same-origin `data/{ente}/textos.parquet`
  (ADR-0014), sincronizado no deploy a partir do ponteiro `-latest`. Sem o arquivo, o
  portal segue funcionando só com `versoes`.

## Gates

- **Os gates de `versoes` ficam intactos**: XSD, identidade, piso de linhas e
  `release-dataset` não mudam, e os itens `leizilla-dataset-*` não são tocados.
- **`textos` tem gates próprios**, em itens próprios
  (`leizilla-textos-{ente}-v{N}-{revision}` imutável + `-latest`):
  - piso de linhas próprio, lido do `dataset_meta.json` do `-latest` de `textos`,
    fail-closed, com `--allow-lower-count` como escape deliberado;
  - contrato de colunas, `texto_id` único e coerente com a identidade, texto não vazio,
    marca de qualidade, e toda âncora dentro do texto e em ordem;
  - construção com qualquer falha de leitura é parcial e não grava o Parquet por padrão.

## Consequências

- Mais de 2 mil normas de RO passam a ser legíveis no portal sem PDF, com a qualidade
  declarada. O texto traz os erros do OCR; isso é assumido e sinalizado, não escondido.
- O arquivo tem ~3 MB (ZSTD) para 2115 normas e é lido inteiro na primeira leitura de um
  texto. Revisitar o particionamento se passar de ~20 MB.
- Duas tabelas em vez de uma: o portal faz a união na listagem. O schema de `versoes` e o
  XML não mudam.
- Uma norma promovida a S4 continua em `textos`; some só da listagem de "só texto".

## Fora de escopo

- **Busca full-text** no texto não estruturado. A busca textual continua sobre `versoes`;
  normas só-texto são encontradas pela listagem, pelos filtros e pelo número.
- **Trocar o motor de OCR** ou reprocessar PDFs. A tabela registra o motor justamente para
  que uma troca futura seja rastreável.
- Extrair ano, data ou ementa do texto não estruturado, e estender âncoras a parágrafos,
  incisos e alíneas (frente `boundary-decision-parser`).

## Adendo 2026-11-17 — fecha e âncoras vêm do leitor de hierarquia

`artigos_fecham`, `artigos_total`, `artigos_ultimo` e `ancoras` deixam de derivar de
`article_sequence.read_articles` e passam a derivar de `hierarchy_sequence.read_hierarchy`
(nível dos artigos). `artigos_fecham` é `hierarchy_sequence.article_closes`, a mesma função
que o placar do ratchet (`scripts/compare_teacher_reader.py`) e os portões do re-OCR
(`textlayer.read_closure`) usam: uma só noção de "fecha" no código. `ancoras` mantém o
formato e o significado (`ini`/`fim` = marcador do artigo, code points); um artigo recuperado
de uma frase de encerramento sem marcador ganha âncora que começa na frase, com `fim` na
primeira palavra. O contrato do Parquet (`TEXTOS_SCHEMA`) não muda; `read_articles` continua
no código, usado internamente pelo leitor de hierarquia, mas nenhuma coluna publicada depende
dele diretamente.

Motivo, medido: com o marcador do último artigo apagado, `read_articles` ainda declarava a
norma fechada em 358 de 364 casos; `read_hierarchy` tem checagens de fim de norma e é o leitor
guardado pelo ratchet.

Números sobre a camada publicada de 2026-11-17 (2192 normas), com o código atual: ambos
fecham 1821; só a hierarquia fecha 240; só o leitor antigo fecha 7; nenhum fecha 124. Das 7
que perdem a bandeira, 5 o leitor antigo fechava lendo um artigo citado como se fosse da norma
ou um texto sem a parte final (lei 392, 595, 748, 1315, 1417), 1 é recusa por cautela do
leitor novo (lei 1698: anexo orçamentário faz a cauda parecer ter um artigo não lido) e 1 é
incerta (lei 529). Nas 15 normas amostradas (semente 3) das que só a hierarquia fecha, 14 estão
certas e 1 é incerta (lei 1691, "Art. 3º" impresso duas vezes). Custo: mediana 1,1 ms por texto
(p95 9 ms, máx. 373 ms) contra 0,28 ms do leitor antigo; 6,8 s para os 2086 textos em cache.
