# Consolidação do Internet Archive — Camada Raw

> **Status**: a nomenclatura ancorada em `coddoc` descrita nas versões anteriores
> deste documento foi **substituída** por [ADR-0010](../adr/0010-raw-content-addressed-parsed-urn.md).
> Este arquivo mantém apenas o **diagnóstico** (ainda válido); o desenho vigente
> está na ADR.

---

## 🗺️ O Problema: Fragmentação do Catálogo

O modelo original criava **um item IA por lei**
(`leizilla-raw-{ente}-{fonte}-{chave}`). Com **51.442 recursos só de Rondônia** e,
em escala nacional (26 estados + DF + Federal), milhões de itens, isso traz:

1. **Poluição de catálogo / rate-limiting**: risco de bloqueio de conta por volume.
2. **Distribuição em lote inviável**: torrents/ZIPs do IA por coleção ficam
   ingerenciáveis com milhares de itens.
3. **Lentidão de API**: listar itens para controle torna-se instável.

A consolidação em poucos itens robustos por `(ente, fonte)` resolve os três.

---

## ⚡ A Solução Vigente (ADR-0010)

O **como** consolidar mudou. A versão inicial bucketizava por número de `coddoc`
— a chave primária do CMS da Ditel, idiossincrasia de **uma fonte**. ADR-0010
corrige isso:

- **Raw → content-addressed**: o arquivo é nomeado pelo **SHA-256** do conteúdo;
  o item de range bucketiza por **prefixo de hash**
  (`leizilla-raw-ro-casacivil-3f`). Agnóstico de fonte; dedup e imutabilidade de
  graça.
- **Índice por `(ente, fonte)`**: `index.csv`
  (`source_key, content_hash, content_type, source_url, captured_at`) é a ponte
  entre a chave de colheita da fonte (coddoc, caminho do Planalto, ...) e o hash.
  `fetch_ocr` resolve via lookup no índice — um fetch por `(ente, fonte)`,
  cacheável.
- **Parsed → URN-LEX**: a camada parsed é keyed por URN
  (`urn:lex:br;...`), independente de como o documento foi colhido (ADR-0005 +
  ADR-0010).

A chave de colheita da fonte é **metadado** no índice — nunca path nem fronteira
de range.

### OCR no Internet Archive (inalterado)
A engine `derive` do IA gera OCR independente por PDF. Para um arquivo
content-addressed `3f8a…d21c.pdf`, o OCR fica em `3f8a…d21c_djvu.txt` no mesmo
item, acessível por HTTP direto (serverless, custo zero) uma vez resolvido o hash
pelo índice.

---

## 📚 Referências

- [ADR-0010 — Raw content-addressed, Parsed URN-keyed](../adr/0010-raw-content-addressed-parsed-urn.md) (desenho vigente)
- [ADR-0005 — Internet Archive Identifiers](../adr/0005-ia-identifiers.md) (camada parsed)
