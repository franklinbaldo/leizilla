"""Fontes de leis para Rondônia (slug: 'ro').

Fontes declaradas após auditoria do portal em 2026-05:
- assembleia: Assembleia Legislativa do Estado de Rondônia
  Portal: https://www.al.ro.leg.br/legislacao
  Acesso via coddoc sequencial (1..N). Paginação simples.
- casacivil: Casa Civil do Estado de Rondônia
  Portal: https://www.casacivil.ro.gov.br/leis
  Compilados consolidados — fonte primária para vigente.

Notas:
- Diário Oficial (DOE-RO) disponível em https://diof.ro.gov.br mas acesso
  inconsistente; adicionar como terceira fonte em auditoria futura.
- robots.txt confirmado como permissivo nos dois portais (verificado 2026-05).
"""

FONTES = ["casacivil", "assembleia"]
FONTE_CANONICA = "casacivil"

URLS = {
    "casacivil": "https://www.casacivil.ro.gov.br/leis",
    "assembleia": "https://www.al.ro.leg.br/legislacao",
}
