"""Fontes de leis federais (slug: 'federal').

Fontes mapeadas em 2026-05 para futura implementação:

- planalto: Portal da Legislação — Presidência da República / Casa Civil
  Portal: https://www.planalto.gov.br/ccivil_03/
  Acesso: leis em formato HTML por tipo/número. PDFs de publicação original
  via URL padrão (https://www.planalto.gov.br/ccivil_03/leis/LXXXX.htm).
  Compilados vigentes disponíveis inline — FONTE_CANONICA para federal.
  Obs: HTML, não PDF — scraping exige extração de texto via LLM a partir
  do HTML (não OCR). Ajuste no pipeline M3 (parser.fetch_html vs fetch_ocr).

- camara: Portal da Câmara dos Deputados
  Portal: https://www.camara.leg.br/legislacao/
  Acesso: API REST pública via https://dadosabertos.camara.leg.br/api/v2/
  Inclui PDFs de proposições, texto compilado, metadados estruturados.
  Útil para projetos de lei + texto consolidado.

- senado: Portal do Senado Federal / LegisWeb
  Portal: https://legis.senado.leg.br/norma/
  Acesso: API REST via https://legis.senado.leg.br/dadosabertos/
  Cobre legislação federal com metadados (autoria, situação, ementa).

- dou: Diário Oficial da União — Imprensa Nacional
  Portal: https://www.in.gov.br/
  Acesso: API pública (https://queridodiario.ok.org.br/ para histórico).
  Útil para publicação original e cross-verificação de data.

Notas para implementação:
- Planalto é o equivalente federal da casacivil RO (compilados vigentes).
- A API da Câmara é a melhor entrada para metadados estruturados (JSON).
- HTML no Planalto exige adaptação no pipeline: parse_law deve aceitar HTML
  além de OCR text. Decisão de M3.4 (future milestone).
- Camara API tem paginação e rate-limit explícito: 60 req/min.
- Legislação pré-1988 (anterior à CF) disponível mas com cobertura parcial.
- robots.txt do Planalto e Câmara: a auditar antes da implementação.
"""

FONTES = ["planalto", "camara", "senado", "dou"]
FONTE_CANONICA = "planalto"

URLS = {
    "planalto": "https://www.planalto.gov.br/ccivil_03/",
    "camara": "https://www.camara.leg.br/legislacao/",
    "senado": "https://legis.senado.leg.br/norma/",
    "dou": "https://www.in.gov.br/",
}

APIS = {
    "camara": "https://dadosabertos.camara.leg.br/api/v2/",
    "senado": "https://legis.senado.leg.br/dadosabertos/",
}
