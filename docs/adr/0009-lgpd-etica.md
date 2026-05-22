# ADR-0009 — LGPD, Ética e Política de Despublicação

**Status**: Aprovada  
**Data**: 2026-05-20  
**Contexto**: M1 — Foundation

## Posição

Leis estaduais e federais brasileiras são atos públicos por força constitucional:
- CF art. 5º LX: publicidade dos atos do Poder Público.
- CF art. 84 IV: leis sancionadas pelo Presidente são publicadas no DOU.
- CF art. 37 caput: administração pública obedece ao princípio da publicidade.

**A LGPD (Lei 13.709/2018) não autoriza despublicação de norma pública** e não
está hierarquicamente acima da Constituição (CF art. 102 III "b").

## Citação de pessoas físicas em leis antigas

Nomeações, aposentadorias, concessões individuais — comuns em leis estaduais
pré-2000 — fazem parte do ato administrativo público original. Indexar e
republicar é **continuidade do ato**, não tratamento novo de dados pessoais
sujeito a consentimento (LGPD art. 7º VI: cumprimento de obrigação legal ou
regulatória).

## Política

- **Não fazemos triagem/redação de nomes** em leis publicadas.
- **Não atendemos pedidos de "direito ao esquecimento"** para atos legislativos
  ou administrativos de caráter público.
- **Atendemos** erros factuais (ex: lei indexada com metadado errado) via issue
  no GitHub.

## Limite

Se algum `<dispositivo>` contiver dado que não fazia parte do ato original
publicado (ex: adicionado erroneamente pelo parser LLM), isso é **bug de parse**
e deve ser corrigido. Não é caso de LGPD — é qualidade de dados.

## Registro

Esta posição será revisada se e quando houver decisão judicial específica
aplicável a projetos de indexação legislativa. Mudanças documentadas com nova
entrada no IMPLEMENTATION.md.
