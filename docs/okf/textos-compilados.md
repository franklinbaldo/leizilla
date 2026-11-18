---
type: Avaliacao
title: Textos compilados da Casa Civil — o gênero, o corpus e a posição no modelo de dados
description: Como a Casa Civil/RO compila uma norma (redação superada impressa antes da nova, notas oficiais entre parênteses), o corpus local de 99 compilados, a escolha de extração de texto, e a proposta de modelo (versões de um dispositivo, estado "superado", notas como ref) que aguarda o ADR-0020.
tags: [compilada, leitor, documento-marcado, versoes, corpus, adr-0020]
timestamp: 2026-11-18T00:00:00Z
---

A camada de texto mostra a **versão compilada** ("COMPILADA.pdf" da lista oficial) como texto de
leitura quando ela existe (ADR-0015, adendo 2026-11-18). São as normas alteradas, as mais
consultadas (LC 68/1992, o estatuto dos servidores). Este documento descreve o gênero, o
corpus em que as regras do leitor foram desenhadas e a posição proposta no modelo de dados.
O estado vivo e a próxima ação ficam em `project-dag.md` (folha `reader-compiled-texts`).

## Corpus local

Todas as capturas com rendição `compilada` nos itens `leizilla_ro_casacivil_*` do IA em
2026-11-18 (nome do arquivo `COMPILAD*`/`COMP` via `rendicao_da_url`; as que chegam depois entram
com o mesmo comando de listagem): **99 arquivos, 99 normas** (62 leis, 29 LCs, 5 decretos, 3
decretos-leis); 32 têm também o original preservado.

- **Todos os 99 são "Text PDF" no IA** (camada de texto embutida, nascidos digitais). Nenhum tinha
  `_djvu.txt` no momento da coleta (a derivação é pendente), então a fonte do texto é o
  `pdftotext` do PDF preservado. As 30 linhas compiladas da camada publicada de 2026-11-18 não têm `texto_url`: são
  o texto próprio da fila `sem-texto` (OCR): o OCR de uma página que já tem texto embutido é trabalho
  desnecessário e pior (ver "Fila `sem-texto`" abaixo e ADR-0019).
- **Modo de extração**: `pdftotext` sem `-layout` (modo simples). O `-layout` reproduz colunas com
  corridas de espaços (1,77x os bytes; 221 mil corridas de 3+ espaços nos 99), não muda o fecho
  dos artigos (41 contra 40 de 99, a única diferença é uma lei com tabelas) e o texto que o IA
  guarda a partir de um "Text PDF" (`pdf-to-hocr`, uma linha por linha visual, sem colunas) se
  parece com o simples. O simples é o escolhido para o corpus e para o caminho `pdf-text` da fila
  própria.
- **Fecho do nível de artigos antes de qualquer mudança**: 40 de 99 (40%). Em 72 normas de
  DESENHO (semente `compiled-seed-1`, 70/30 por norma) 29; em 27 de TESTE (held-out) 11.
- Cada arquivo: norma, sha256, fonte do texto, linhas, fecho e a dica dos candidatos sem
  explicação (`duplicate` em quase todos).

## O gênero (~15 normas de desenho lidas, o vocabulário medido nas 72)

1. **Cabeçalho.** Epígrafe, às vezes `DOE Nº …`, e um bloco `Alterações:` com uma linha por norma
   alteradora ("Alterada pela Lei n° 5.813, de 3/7/2024."). Cabeçalho de página repetido
   ("GOVERNO DO ESTADO DE RONDÔNIA / GOVERNADORIA") e número de página sozinho numa linha.
2. **A redação superada é impressa de novo, sem marca, e a nova vem depois dela com a nota.** O PDF
   mostra a antiga riscada; o risco **se perde** na extração. O sinal que sobrevive é a **posição**
   e a **nota**: a versão atual é a última impressa e a que traz "(Redação dada pela Lei …)" **no
   fim do seu texto**; as anteriores não têm nota (ou têm a nota da alteração anterior). Até três
   versões seguidas (lei 5970, art. 1º: o original e quatro redações, de 18/2, 27/8, 2/9 e 1°/10/2025).
3. **Nunca a nota vem antes do texto que ela qualifica.** Ela fecha o texto próprio do
   dispositivo (antes do primeiro filho: "caput … (Redação dada …)" e só então os incisos).
   Notas em dispositivos filhos qualificam o filho, não o artigo.
4. **Repete-se só o que mudou.** Um artigo com um parágrafo novo repete só o caput e o parágrafo
   alterado ("Art. 2º … / Art. 2º … (Redação dada …)", os §§ 1º e 2º antigos, depois o § 3º
   "(Acrescido pela …)"). Em leis antigas (lei 995) imprime-se o bloco todo duas vezes: § 1º, § 2º
   antigos e depois § 1º … § 5º novos, não adjacentes. A nota de um inciso ou alínea qualifica o
   inciso ou a alínea.
5. **Vocabulário das notas** (frequência em 72 normas): "Redação dada pela/pelo" (1.269),
   "Revogado pela" (740), "Acrescido pela" (524), "Inciso/Alínea/Parágrafo/Dispositivo
   acrescido|incluído pela" (~250), "Suprimido pela" (41), "Dispositivo vetado pelo Governador … e
   mantido o texto pela Assembleia", "Vetado pelo Governador", "Matéria vetada" (~63), "Nomenclatura alterada pela" (40), "Alteração dada pela",
   "Primitivo parágrafo único alterado pela", "Primitivo artigo 6º renumerado pela", "Com efeitos
   financeiros a partir de", "(Republicado)", "Declarada a inconstitucionalidade …". `(NR)` quase
   só aparece dentro de blocos citados da norma alteradora.
6. **Revogado.** "(Revogado pela Lei …)" no fim do dispositivo; o texto revogado **continua
   impresso** (é a redação vigente até a revogação). Pode vir junto da nota de redação: "(Redação
   dada pela Lei A) (Revogado pela Lei B)". O dispositivo revogado é de uma só versão.
7. **Inseridos.** `Art. 6º-A`, `5º-A`, `114-A` aparecem no lugar com "(Acrescido pela …)" e nenhuma
   versão anterior; o sufixo vem colado ao número (e, em alguns, com um espaço: "Art. 114-A À
   Superintendência").
8. **Veto.** "(Dispositivo vetado pelo Governador … e mantido o texto pela Assembleia …)" é nota
   da versão restaurada; "(Vetado)" sozinho marca um vazio.
9. **Renumeração.** "(Primitivo artigo 139, renumerado pela Lei …)": dois artigos com o mesmo número
   que **não** são versões (decreto-lei 9, art. 140: o renumerado e o antigo dispositivo de vigência).
10. **Norma alteradora no corpo.** Uma lei que só altera outra aparece com os blocos citados
    entre aspas (a lógica de bloco citado do leitor cobre) e, em alguns arquivos (leis 5832 e
    6324, LDO e LOA), com **atos alteradores inteiros anexados depois do fecho e da assinatura**
    ("Faço saber …", "Art. 1° …" de novo): outro ato, não versão. Tabelas e anexos orçamentários
    são colunas de células sem estrutura de artigo.

## Posição no modelo de dados (proposta; decisão no ADR-0020)

**Em um texto compilado, várias versões impressas do mesmo dispositivo são VERSÕES de um
dispositivo**, não duplicatas e não texto citado. Representação mínima e reversível, sem
reescrever nada:

- **Leitor** (`hierarchy_sequence`): cada impressão é um nó do mesmo tipo e `number`; a última é o
  dispositivo `own` (a vigente); as anteriores têm `status="superseded"`, e toda a subárvore delas
  também. Quem filtra `status == "own"` (placar, gates, `own_articles`) vê cada dispositivo uma só
  vez; a sequência 1..N conta o artigo uma vez, quantas impressões houver. Um nó superado não é
  `quoted` (não é texto de outra norma).
- **Documento marcado** (`marcacao.py`, XSD): a versão anterior é o mesmo elemento com
  `estado="superado"` (o valor novo do atributo que já tinha `vetado` e `ausente`); a atual não
  leva `estado`. A nota oficial é `<ref rel="…">(Redação dada pela Lei …)</ref>` — o elemento
  `ref` (citação à norma alteradora; `alvo` fica vazio até a norma ser resolvida) com o atributo
  novo `rel` ∈ {`redacao`, `acrescimo`, `revogacao`, `veto`, `vide`, `outra`}. A nota é texto
  impresso e permanece no strip (invariante intocada; prova no corpus de 2970 textos: 100%).
- **`to_rows`**: a coluna `estado` já existe; `estado == "superado"` marca a linha **e todas as
  descendentes**. A visão "só o texto vigente" é `estado != "superado"`; o caminho (`art-2`)
  repete entre a vigente e as superadas (a vigente é a que não tem `estado`).
- **Sinal exigido para ler versões** (nunca uma duplicata crua): impressões do mesmo número (e
  sufixo) **dentro do mesmo escopo**, cada uma abrindo linha, e pelo menos uma impressão **posterior**
  com nota de alteração no texto próprio ("Redação dada", "Alteração dada", "alterado pela",
  "renumerado", "mantido o texto"). Acrescido/revogado sozinho não basta: não há texto anterior.
- **Ainda não coberto**: ver "O que fica de fora" no fim deste documento.

**Precisa do ADR-0020**: (a) o valor `superado` e o atributo `rel` entram em
`leizilla-doc-v0.xsd` (alteração da gramática pública do documento marcado); (b) o modelo de
vigência de `SCHEMA.md` (versões no tempo por `<versao>`) e as "versões impressas" de um
compilado são coisas diferentes: aqui são camadas de redação de um **mesmo documento**, e a
decisão é se entram em `versoes` (uma linha por redação, com a lei alteradora como fonte) ou se
ficam só na camada de leitura; (c) a **vigente é a última impressa** é uma convenção do gênero
da Casa Civil, a confirmar com o próprio documento oficial (a nota "(Redação dada …)" é do
dispositivo que ela qualifica). Nada em `docs/SCHEMA.md` ou nos ADRs foi alterado.

## Fila `sem-texto` e a rendição de leitura

A fila `sem-texto` do re-OCR (ADR-0019) olhava a norma: se **qualquer** captura tinha texto do IA,
a norma saía da fila. Com a camada preferindo a compilada, uma norma cuja compilada ainda não tem
texto (derivação pendente, ou PDF escaneado) tem o original com texto e **nunca entrava**. Agora a
fila considera a captura de leitura (`order_for_reading`, a primeira com PDF no item): entra se
essa captura não tem texto e nada de uma rendição igual ou melhor a cobre (nem `_djvu.txt` no
item, nem a linha publicada, cuja rendição vem do `sha256_fonte`: as linhas antigas não têm a
coluna `rendicao`). Na montagem de `textos` o texto próprio aceito da rendição de leitura vence o
`_djvu.txt` de uma rendição pior.

Para PDFs com camada de texto embutida (os "Text PDF" do IA) a fila lê o texto com `pdftotext`
(poppler, o mesmo que o re-OCR já exige; nenhuma dependência nova) antes de rasterizar: se passa
no portão de sempre (150 caracteres úteis por página) a linha tem `engine = pdftotext` e
`ocr_motor = pdftotext (camada de texto do PDF, sem OCR, ...)`; se não (escaneado), o PDF segue
para o Kreuzberg+PaddleOCR e a linha é a do OCR. Uma tentativa `pdftotext` aceita impede outra do
mesmo PDF.

Medido em 2026-11-18 sobre o acervo do IA e o `textos` publicado (06:16Z): a fila tinha 1292
normas (PDFs preservados sem texto nenhum); com a regra tem 1300 (8 a mais: 4 compiladas cujo
original tem texto e 4 de outras rendições melhores que a que tem texto). Das 1300, 83 são a
captura compilada, e 503 têm PDF "Text PDF" no IA (`pdftotext`, sem OCR) contra 797 "Image
Container PDF" (OCR).

## O que fica de fora

Atos alteradores anexados em arquivos que não têm o cabeçalho "Alterações:"; blocos citados com
reticências cuja cadeia levou um artigo citado como próprio (lei 5076); cópias de acórdão e anexos
orçamentários dentro do "compilado" (leis 5036 e 5584); o artigo renumerado cujo número colide
com o do dispositivo antigo (decreto-lei 9, art. 140); notas de dispositivos filhos que não
promovem o artigo quando o caput também foi reimpresso sem nota nenhuma.
