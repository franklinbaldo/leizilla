---
type: Medicao
title: Medições de novembro de 2026 que sustentam decisões
description: Registro datado do custo medido da API do professor, rodada por rodada, e índice de onde estão as outras medições da frente de leitura (etiquetador aprendido, âncoras, revisão do Sonnet, compilados), com o que ficou só no scratch.
tags: [medicao, custo, teacher-batch]
timestamp: 2026-11-18T00:00:00Z
---

Registro das medições que uma decisão cita e que, até aqui, existiam só no scratch das sessões.
Cada entrada diz o que foi rodado, os números, onde está o detalhe e se o material bruto foi
preservado. "Scratch, não preservado" quer dizer: os números abaixo foram conferidos contra os
arquivos da sessão em 2026-11-18, mas os arquivos não estão no repositório nem no IA e **não se
reproduzem a partir dele**.

## Custo medido da API, rodada por rodada

Origem: as linhas `measured US$...` dos logs do passo `collect` do workflow `teacher-batch.yml`
(`gh api repos/franklinbaldo/leizilla/actions/workflows/teacher-batch.yml/runs` e os logs dos
jobs), execuções desde 2026-11-17 17:00 UTC; o modo, o modelo e os insumos vêm das variáveis
`IN_*` do passo `submit` e a estimativa é a do `plan` impresso nele. O `measured` é o que o `collect` calcula dos tokens que a API devolve; os pares
submit/collect foram conferidos por `IN_RUN`. Material bruto: os logs ficam no GitHub Actions (expiram com a retenção do
repositório); as respostas do modelo ficaram só no scratch, **não preservadas**, salvo quando a
coleta enviou o artifact de rótulos (citado nas notas de cada rodada nos outros documentos).

| coleta (run) | submit (run) | modo | modelo, effort | seleção | normas | estimativa | **medido (US$)** |
|---|---|---|---|---|---|---|---|
| 44139324387 | 44139172540 | review | haiku-5-5, medium | `eval-2026-11` (+100 canários); 144 de 200 revisadas | 200 | 0,26 | **0,2384** |
| 44146515643 | 44146379684 | review | haiku-5-5, medium | `eval-2026-11`, de novo com o prompt corrigido; 199 de 200 | 200 | 0,29 | **0,2787** |
| 44183783864 | 44183644296 | mark | haiku-5-5, medium | `mark-pilot-2026-11`, prompt v1 | 60 | 0,06 | **0,0724** |
| 44191043135 | 44190934758 | mark | haiku-5-5, medium | `mark-pilot-2026-11`, prompt v2 | 60 | 0,07 | **0,0748** |
| 44192207303 | 44191036715 | mark | haiku-5-5, medium | `mark-stress-reflow-2026-11` (40 de 40 truncadas) | 40 | 0,02 | **0,0553** |
| 44195307522 | 44194666799 | mark | haiku-5-5, low | estresse, `limit=8` (8 de 8 truncadas) | 8 | 0,00 | **0,0080** |
| 44200532103 | 44200418475 | mark | haiku-5-5, medium, `col+snippet` | `mark-reference-2026-11` | 300 | 0,25 | **0,2931** |
| 44201705985 | 44200537081 | mark | haiku-5-5, medium, `snippet` | estresse, `limit=8` (sonda) | 8 | 0,00 | **0,0081** |
| 44228356004 | 44227166187 | mark | haiku-5-5, medium, `col+snippet` | `mark-full-2026-11-a` | 1 431 | 1,38 | **1,5814** |
| 44227337585 | 44227239366 | mark | haiku-5-5, medium, `col+snippet` | `mark-full-2026-11-b` | 1 430 | 1,37 | **1,5530** |
| 44228441792 | 44227324650 | mark | haiku-5-5, medium, `snippet` | `mark-full-longlines-2026-11` | 10 | 0,02 | **0,0242** |
| 44288579553 | 44288243796 | review | **sonnet-5-5**, medium | `residue-review-2026-11` (79 + 16 canários) | 79 | 2,03 | **0,7994** |
| 44289315841 | 44288322098 | mark | haiku-5-5, medium, `col+snippet` | `mark-full-giants-2026-11` (49 de 50 marcadas) | 50 | 0,81 | **0,7075** |
| 44290030110 | 44288433856 | mark | haiku-5-5, medium, `snippet` | `mark-full-giants-longlines-2026-11` | 3 | 0,07 | **0,0618** |
| | | | | **Total (14 rodadas)** | | | **US$ 5,7561** |

Notas. (1) O total soma só as coletas que imprimem `measured`; a execução `44227328852`
(cancelada) e a `44225542341` (`plan`, sem custo) não entram. Uma rodada que falha antes da coleta não imprime custo, então
o total é um piso do gasto: lotes enviados e nunca coletados (se houve) não aparecem. (2) Nas rodadas Haiku `mark` o medido ficou 13% a 17% acima da
estimativa do `plan` (piloto 0,0631 contra 0,0724; referência 0,25 contra 0,293; a e b 1,38 e 1,37
contra 1,58 e 1,55), exceto nos gigantes (0,81 estimado, 0,71 medido); no Sonnet ficou muito
abaixo (2,03 contra 0,80: em `medium` o Sonnet quase não pensa, ver `reader-ratchet.md`). (3) A
camada inteira em Haiku `mark` (a, b, linhas longas, gigantes e gigantes de linha longa: 2 924
normas) somou US$ 3,93; a referência de 300 e os pilotos v1/v2, US$ 0,44. (4) Fora da janela, sem log aberto (valores do `summary.json` do scratch): rótulos `label`
da camada de 2 088 normas, 2026-11-16, US$ 1,3062; conjunto held-out de 500, 2026-11-17 14:36 UTC,
US$ 0,3259; amostra de 60, 2026-11-16, US$ 0,0330.

## Onde estão as outras medições

| medição | onde está o registro | material bruto |
|---|---|---|
| etiquetador aprendido por linha contra o leitor por regras (418 normas retidas): F1 por nível, próprio contra citado, híbrido, bisseção, curva de aprendizado, o que o modelo acha | [reader-ratchet.md](reader-ratchet.md), "Etiquetador aprendido por linha" | scratch, não preservado; scripts de treino não commitados |
| coluna contra trecho: piloto v1 e v2, estresse de 40 e de 8 truncadas, sonda de trecho (84 de 113 marcas usadas, 29 conflitos não investigados) | [teacher-mark.md](teacher-mark.md), "Medições: coluna contra trecho" | scratch, não preservado |
| revisão do resíduo com o Sonnet: classificação dos 319 pontos e leitura a olho | [reader-ratchet.md](reader-ratchet.md), "Revisão do resíduo com o Sonnet" e [teacher-review.md](teacher-review.md) | scratch, não preservado; as 90 errata resultantes estão em `mark-reference-errata.json` |
| compilados: corpus de 99, 72 de desenho e 27 retidas, fecho antes e depois | [textos-compilados.md](textos-compilados.md) e [reader-ratchet.md](reader-ratchet.md), "Torneio nos textos compilados" | scratch, não preservado; os PDFs estão nos itens do IA |

## O que não consegui fonte para registrar

- A rodada de efeito `low` (8 de 8 truncadas) tem log de coleta (`44195307522`), mas nenhum
  `summary.json` no scratch além do custo e das contagens do log; o que se registra é o que o log
  imprime.
- A lista dos 29 conflitos da sonda de trecho não foi gerada (nem existe análise dela).
