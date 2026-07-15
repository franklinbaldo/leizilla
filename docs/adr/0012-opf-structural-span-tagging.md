# ADR-0012 — OPF (token-classifier) como caminho de anotação estrutural das normas, complementar ao parser generativo

**Status**: Aprovada — **fine-tune reativado (2026-07-14, ver atualização abaixo)**
**Data**: 2026-06-05
**Contexto**: Anotação estrutural de normas — fine-tune do OpenAI Privacy Filter (OPF)
**Relaciona-se com**: [ADR-0010](0010-raw-content-addressed-parsed-urn.md) (raw OCR
content-addressed é o insumo), `parser.py` (parser generativo via Claude Haiku),
[SCHEMA.md](../SCHEMA.md) (modelo dispositivo-cêntrico, rótulo derivado do `path`).

## Atualização (2026-07-14) — fine-tune (Fase 3) REATIVADO como smoke test no gold v0

A atualização de 2026-06-06 (abaixo) condicionava reativar a Fase 3 a evidência de
OCR ruidoso/formatação irregular/outro ente. O mantenedor decidiu retomar o treino
agora mesmo assim, como **smoke test explícito sobre o gold v0** (leis federais do
Planalto, texto limpo, 251 spans, fonte única) — não porque o gatilho de evidência
foi atingido, mas por decisão direta de prosseguir. Registro isso para transparência:
a limitação conhecida do v0 segue valendo (`known_limitations` no
`manifest.json` — "lacks OCR noise the production OPF will see"), e o resultado deste
run deve ser lido como baseline/smoke test, não como modelo pronto para produção —
exatamente como o próprio notebook já documenta em sua célula final ("v0 is a smoke
test + baseline, not a deliverable model").

`notebooks/opf_train_colab.ipynb` já aponta para `main` e o gold v0 já está commitado
lá — nenhuma mudança de código foi necessária para destravar o run; falta só executá-lo
(GPU via Colab, fora do alcance de sessões sem acesso a GPU/Drive interativo).
Expandir o gold com OCR real de RO (multi-fonte, incluindo casos ruidosos como o de
`lei-00001-1983` encontrado na sessão de go-live desta mesma data) permanece o caminho
recomendado para um treino de produção — decisão explicitamente adiada para depois
deste smoke test, a critério do mantenedor.

## Atualização (2026-06-06) — fine-tune (Fase 3) ADIADO; ferramentas model-free mantidas

A ingestão da DITEL (PR #85, mergeada) confirmou empiricamente o pressuposto desta ADR:
as **leis de RO são born-digital** com estrutura **LC 95/1998 altamente regular**, e o
**segmentador regex** (`segmenter.py`) já atinge **exact micro-F1 0.95 / overlap 0.99** no
gold. Entre o baseline determinístico e o parse generativo do Claude (Etapa 2), a estrutura
está coberta **sem treinar modelo**. Portanto:

- **O fine-tune do OPF (Fase 3, GPU) está ADIADO** — não há evidência de que regex + Claude
  fiquem aquém no regime regular/born-digital. Revisitar **quando** houver dados que o
  justifiquem: fontes **OCR-ruidosas** (ex.: decretos antigos escaneados), formatação
  **irregular**, ou **outros entes** (SP etc.) — e medindo contra o baseline 0.95/0.99.
- **As partes model-free permanecem ativos e úteis** (não dependem do fine-tune): o
  `segmenter.py` (baseline + pré-filtro/cross-check), `evaluate_against_gold`/`find_errors`
  (harness de avaliação) e `validate_structure` (validação da norma inteira — "achamos todos
  os artigos?", usável como gate de completude da ingestão). O gold + esta ADR seguem como
  ativo versionado e decisão registrada.

O método e a ontologia abaixo seguem válidos; o que muda é o **gatilho de ativação** do
treino — passa a ser orientado por evidência, não pré-agendado.


## Contexto

A Etapa 2 do pipeline (princípio load-bearing #3) é **pluggable**: hoje o default é
o Claude Haiku transformando OCR/HTML em Leizilla XML (`parser.py`). É um parser
**generativo** — escreve a estrutura inteira (ementa, artigos, parágrafos, incisos)
e devolve XML validado contra o XSD. Funciona, mas tem custo por chamada de API e
depende de um modelo remoto.

Existe um segundo caminho, ortogonal e barato: **marcar regiões** do texto com um
classificador de tokens treinado, em vez de gerar texto. O `opf-finetune` skill
(franklinbaldo/skills) descreve fazer isso com o **OPF** (`openai/privacy-filter`,
Apache 2.0): um modelo bidirecional com cabeça de token-classification e decodificação
de spans BIOES via Viterbi. Propriedades relevantes:

- **Pequeno e local** (1.5B total / 50M ativos, MoE). Treina num GPU modesto, inferência
  viável em CPU para ETL em lote — alinhado ao princípio **custo-zero** do projeto.
- **Contexto longo** (128k tokens): uma norma inteira cabe sem chunking.
- **Data-efficient**: poucas milhares de anotações já movem F1.
- **Licença permissiva** (Apache 2.0).

O modelo dispositivo-cêntrico do Leizilla encaixa de forma natural: o **rótulo**
(`Art. 1º`, `§ 2º`, `I`, `a)`) é derivado de `(tipo, path)` em render-time
(SCHEMA.md §4.2). Os mesmos **marcadores estruturais** são exatamente os *short
anchors* que o OPF marca bem.

## Decisão

**Adotar o OPF como um caminho de anotação estrutural — Pattern B do skill (structural
tagging of statutes) — complementar ao parser generativo, não substituto dele.**

1. **Escopo: tagging de regiões, não geração.** O OPF marca *marcadores* curtos
   (`Art. 5º`, `§ 2º`, `III -`, `a)`) e cues curtos (ementa, vigência, revogação);
   o **corpo** de cada dispositivo é reconstruído em pós-processamento como o texto
   entre marcadores consecutivos. O OPF **não** escreve XML — para extração generativa
   (resumir um dispositivo, normalizar texto) o modelo certo continua sendo um chat LLM.

2. **Complementar, não competidor.** Claude Haiku continua sendo o default da Etapa 2.
   O OPF é um candidato a (a) **pré-passo** barato que segmenta antes do LLM, (b)
   **cross-check** da estrutura que o LLM produziu, (c) caminho **custo-zero** local
   para fontes de alto volume. Qual desses papéis vence é decisão de uma fase futura,
   após medir; esta ADR só fixa o *método* e a *ontologia*.

3. **Ontologia v1 (`leizilla_normas_v1`)** em `data/opf/label_space.json`:
   `["O", "ementa", "art_marcador", "par_marcador", "inc_marcador", "ali_marcador",
   "vigencia", "revogacao"]`. Definições são o ativo durável; volume é incremental.
   Categorias com pouco suporte podem ser *staged* (definidas mas fora do label space
   treinado) até cruzarem ~25 spans — o `manifest.json` registra `active` vs `staged`,
   e métricas são reportadas **por categoria com suporte**.

4. **O ouro mora no git.** `label_space.json` + splits revisados (`data/opf/gold/`) +
   `manifest.json` são versionados (whitelist no `.gitignore`); Drive/IA são caches de
   runtime. Cada melhoria de anotação vira um diff revisável; cada checkpoint rastreia
   o `category_version` + `source_commit` exatos.

## Duas advertências load-bearing (do skill — mudam orçamento e desenho)

1. **OPF é English-primary; nosso corpus é PT-BR.** Performance cai fora do inglês. A
   validação em PT-BR é **obrigatória** (nunca confiar em número de eval inglês), o
   orçamento de anotação é maior que o "few thousand" do benchmark inglês, e o eval
   mede **erro de fronteira**, não só presença. Por isso a amostragem estratifica por
   **fonte** (assembleia / casacivil / planalto) — cada uma é uma sub-distribuição com
   formatação, cues e qualidade de OCR próprios.

2. **Atenção em banda favorece âncoras curtas, não regiões gigantes.** Janela efetiva
   ~257 tokens: pedir ao modelo para rotular um dispositivo inteiro token-a-token
   fragmenta nas bordas. Por isso a ontologia é **marcador-cêntrica** e a reconstrução
   da região é pós-processamento, não tarefa do modelo.

## Consequências

- **Positivas**: caminho custo-zero/local para anotar estrutura; reaproveita o OCR raw
  já no IA (ADR-0010) como insumo; encaixa direto no `path`/token-map do SCHEMA;
  ouro versionado é auditável e expansível.
- **Custos/riscos**: risco PT-BR (mitigado por eval estratificado obrigatório);
  precisa construir o dataset de anotação (subagentes LLM + ensemble de avaliadores no
  slice de ouro, com erros decorrelacionados do anotador); treino precisa de GPU
  (notebook Colab, não CI). OPF é **auxílio de detecção, não garantia** — manter
  caminho de revisão para o que for consequente.
- **Reversível**: tudo novo (módulo `opf.py`, dir `data/opf/`, comando `opf-sample`,
  doc) e desligado do caminho de produção; abandonar é remover arquivos. Não altera
  o parser, o schema, nem o pipeline existente.

## Fora de escopo desta ADR

O papel final no pipeline de produção (pré-passo vs. cross-check vs. substituto por
fonte), o ponto de operação (precision/recall) e a integração de inferência ficam para
fases posteriores, decididas com métricas em mãos. Aqui fixamos método + ontologia +
a fundação de preparação de dados.
