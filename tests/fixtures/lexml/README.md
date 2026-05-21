# LexML brasileiro — XSD oficial (bundle)

Schemas oficiais do LexML brasileiro v1.0, bundled aqui para validação
CI offline e reprodutibilidade (decisão em `docs/SCHEMA.md` §9 / §8.2).

## Arquivos

| Arquivo | Origem | Notas |
|---|---|---|
| `lexml-br-rigido.xsd` | https://projeto.lexml.gov.br/esquemas/lexml-br-rigido.xsd | Restrições rigidas (versão preferida para validação). Redefine `lexml-base.xsd`. |
| `lexml-base.xsd` | https://projeto.lexml.gov.br/esquemas/lexml-base.xsd | Schema core (~43KB). Define tipos, attribute groups, elementos. |
| `xml.xsd` | https://www.w3.org/2001/xml.xsd | Standard W3C (atributos `xml:lang`, `xml:base`). |
| `xlink-href.xsd` | https://www.w3.org/Math/XMLSchema/mathml2/common/xlink-href.xsd | Standard W3C (atributo `xlink:href`). |
| `mathml2.xsd` | **stub local** | Schema oficial MathML2 tem ~50 arquivos; leis brasileiras quase nunca usam MathML estruturado. Stub aceita qualquer conteúdo no elemento `<math>`. Substituir por MathML2 oficial completo apenas se validação rigorosa de fórmulas matemáticas em leis virar requisito. |

## Patches aplicados aos XSDs originais

Os `schemaLocation` em `lexml-base.xsd` e `lexml-br-rigido.xsd` foram
alterados para apontar pros arquivos locais (sem rewrite de conteúdo
estrutural):

| Original | Local |
|---|---|
| `http://www.w3.org/2001/xml.xsd` | `xml.xsd` |
| `http://www.w3.org/Math/XMLSchema/mathml2/common/xlink-href.xsd` | `xlink-href.xsd` |
| `http://www.w3.org/Math/XMLSchema/mathml2/mathml2.xsd` | `mathml2.xsd` |

Aplicado via `sed` (idempotente). Sem essas mudanças, `xmllint` falha
quando offline.

## Histórico do LexML

LexML brasileiro está **parado desde ~2010** (ver `docs/SCHEMA.md`
§0.3). A pasta oficial https://projeto.lexml.gov.br/esquemas atualmente
retorna "Atualmente não existem itens nessa pasta" no índice — mas os
arquivos individuais ainda respondem 200 quando você sabe os nomes.

Mantemos o bundle aqui para:
1. **Reprodutibilidade**: CI não depende de servidor LexML gov estar
   no ar. Repo é self-contained.
2. **Defesa contra link rot**: se o servidor sair do ar, o teste
   continua funcionando.
3. **Auditoria**: pin explícito da versão do schema usada.

Se o projeto LexML reviver, atualizar via `curl` desses URLs.

## Por que validamos contra LexML

Ver `docs/SCHEMA.md` §6 inteiro. Resumo:
- Leizilla XML é o formato canônico (dispositivo-cêntrico, vigência
  herda, fonte unificada).
- LexML é representação reduzida para gov interop (Senado/Câmara).
- XSLT `scripts/leizilla-to-lexml.xsl` faz a conversão sob demanda.
- Perdas conhecidas documentadas: divergências multi-fonte, timeline
  histórica, `<inicio tipo>`, anexos. Ver §6.2.
- CI gate: a cada PR, garantir que TODOS os fixtures Leizilla XML
  produzem LexML válido (`pytest tests/test_lexml_export.py`).

CI **não** valida round-trip (LexML → Leizilla XML não é objetivo).
