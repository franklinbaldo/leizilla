# RFC-0008: HTML original do SEI para leis e decretos assinados no SEI

**Status**: proposto — para decisão do proprietário; a opção (i) foi aprovada e implementada em 2026-11-18 (colunas `sei_*` de `textos`, ADR-0015, adendo 2026-11-18); o resto segue proposto
**Data**: 2026-11-18
**Relacionados**: ADR-0001, ADR-0008, ADR-0009, ADR-0010, ADR-0011, `docs/okf/textos-compilados.md`, `docs/okf/documento-marcado.md`, RFC-0007; DAG `sei-original-html`

## Problema

Desde 2018 as leis e os decretos do Poder Executivo de Rondônia nascem no SEI e são assinados eletronicamente. O PDF da Casa Civil é uma impressão do navegador desse documento (produtor "Skia/PDF", cabeçalho `SEI/ABC - NNNNNNN - Lei`, rodapé `documento_imprimir_web`). O HTML original traria parágrafos reais, sem cabeçalho de página nem OCR, com proveniência verificável. A decisão do proprietário é que o **acesso externo não nasce no Leizilla**: nasce no `ies` (CLI Rust do SEI), e o Leizilla o consome.

## Achados

Texto publicado (`textos.parquet`, 3640 textos) e amostra de PDFs preservados:

- **1105 textos (30%) têm código verificador e CRC** (lei 517, decreto 316, lc 272); 1102 são de 2018-08-06 em diante (primeiro: LC 989); os 3 anteriores são ofícios impressos dentro de PDFs antigos. Por ano: 2018 16, 2019 45, 2020 69, 2021 89, 2022 50, 2023 40, 2024 128, 2025 212, 2026 453.
- O extrator acha o par verificador+CRC em 95% dos textos com número de processo no OCR; no texto embutido de 57 PDFs (45 preservados sem texto publicado mais 12 de controle) acha em 42 de 42 que são SEI; os outros 15 são Word, digitalizações ou compilações sem rodapé do SEI. `SEI nº` coincide com o verificador em 1087 de 1105.
- O catálogo lista 12 433 normas de 2018+, das quais só 1572 estão preservadas: o gargalo para o HTML é a preservação, não a identificação.
- Rodapé típico: `A autenticidade deste documento pode ser conferida no site portal do SEI, informando o código verificador 27366482 e o código CRC BEF99C54.` seguido de `Referência: ... Processo nº 0035.067835/2022-66` e `SEI nº 27366482`. O PDF traz um QR code (não decodificado: sem decodificador instalado) e um link estático `https://sei.sistemas.ro.gov.br/sei/controlador_externo.php?acao=documento_conferir&id_orgao_acesso_externo=0`, sem os códigos. Em 16 de 57 PDFs o texto também traz `id_documento=N` (id interno).

Instância de Rondônia, quatro GETs em 2026-11-18, com intervalo de 5 s (`robots.txt`: `User-agent: *`, `Disallow:` vazio):

| Rota | Resultado |
|---|---|
| `controlador_externo.php?acao=documento_conferir` | existe; formulário `txtCodigoVerificador` + `txtCrc` **com captcha de imagem** |
| `modulos/pesquisa/md_pesq_processo_pesquisar.php` | Pesquisa Pública instalada, **com captcha** |
| `publicacoes/controlador_publicacoes.php?acao=publicacao_pesquisar` | Publicações Eletrônicas habilitada, veículo "Diário Oficial do Estado de Rondônia", séries Lei, Lei Complementar, Decreto; **página do formulário sem captcha** (a busca é POST e não foi feita); `publicacao_visualizar` abre por `id_documento` |
| SOAP `SeiWS` / REST `mod-wssei` | exigem sistema e chave concedidos pelo órgão; não sondados |

Versão do SEI: não declarada nas páginas (os recursos indicam série 4.x ou 5.x). Fontes: manuais e guias de conferência de órgãos públicos, manual SEI Publicação v3.1 (gov.br), cartilha da Pesquisa Pública (gov.br), manual SEI WebServices v4.0. O que o HTML de `publicacao_visualizar` devolve e se as leis/decretos são realmente publicados nesse veículo é **inferido**, não observado.

## Enquadramento jurídico

Leis e decretos são atos normativos públicos por natureza (Lei 12.527/2011, art. 3º, I; publicidade, art. 37 da CF); os nomes nas assinaturas são de agentes públicos em exercício (ADR-0009). Nada disso autoriza contornar um controle técnico: o captcha da conferência é um controle de acesso deliberado do órgão, e resolvê-lo ou contorná-lo por máquina está descartado. A rota legítima é a que o próprio órgão abre sem captcha ou a que ele concede por pedido formal.

O pedido seria dirigido ao órgão gestor do SEI de Rondônia, que **não foi determinado** (o Decreto 21.794/2017, que regula o uso, não está preservado; a Casa Civil/DITEL publica os PDFs mas não é necessariamente o gestor). Pede-se, com fundamento na LAI: (a) confirmação de que o veículo de Publicações Eletrônicas cobre leis e decretos e de que a leitura automatizada com intervalo de 3 s é aceita; ou (b) chave de serviço restrita à leitura de atos normativos publicados; ou (c) exportação periódica.

## Opções, em ordem de valor, legitimidade e esforço

1. **(i) Leizilla extrai e guarda identificadores agora.** Zero requisições. `src/leizilla/sei.py` (`extract_sei_ids`: verificador, CRC, `SEI nº`, processo, `id_documento`, assinantes), ainda não ligado à camada de texto. Precisa do proprietário: nada; depois, aprovar colunas anuláveis `sei_verificador`, `sei_crc`, `sei_numero`, `sei_processo`.
2. **(ii) O `ies` ganha um comando que lê documento público sem autenticação**: entrada = base da instalação + verificador + CRC (ou `id_documento`); saída = bytes do HTML, metadados e como a autenticidade foi estabelecida; erros tipados, inclusive `captcha_exigido`. Proposta em issue no `ies`, com contrato, decisão e cassette; o captcha nunca é resolvido. Precisa do proprietário: abrir a issue, decidir a rota (Publicações Eletrônicas é a única sem captcha) e autorizar a produção de Rondônia, que não é uma das sete instalações de treinamento do `ies`.
3. **(iii) O Leizilla consome o `ies`** (`uvx --from ies-sei ies ...` quando houver wheel; binário fixado no CI) e preserva o HTML endereçado por conteúdo (ADR-0010) como `rendicao = "sei-html"`; a camada de texto o prefere para leitura e o documento marcado parte dele, mantendo os bytes originais como preservado. Depende de (i) e (ii).
4. **(iv) Pedido institucional** ao gestor do SEI-RO, se a rota pública exigir captcha ou não cobrir os atos. Precisa do proprietário: identificar o gestor e assinar o pedido.
5. **(v) DOE como fallback** nascido digital (`diof.ro.gov.br`), na frente `ro-diario-oficial-preservation`.

Nota de medida: 1105 de 3640 é o que o extrator encontra nos textos; 1074 de 3616 é o que ficou gravado em `textos` depois da guarda (medidas diferentes, de universos de linhas diferentes).

**Decisões do proprietário, 2026-11-18**: o acesso ao HTML do SEI mora no `ies` (issue aberta lá, a pedido); o proprietário mesmo levantará a limitação do `ies` ao host de produção para leituras públicas sem autenticação.

Primeira fatia de um dia: rodar `extract_sei_ids` sobre as 3640 linhas, publicar as colunas de proveniência na próxima versão de `textos.parquet` e abrir a issue do `ies`.

## Riscos

Verificador lido errado pelo OCR (só vale com CRC); `id_documento` interno não ser aceito pela rota pública; a busca ser POST, que o `ies` exige analisar por efeito.
