"""Fontes de leis para Rondônia (slug: 'ro').

Fontes declaradas após auditoria do portal em 2026-05:
- assembleia: Assembleia Legislativa do Estado de Rondônia
  Portal: https://www.al.ro.leg.br/legislacao
  Acesso via coddoc sequencial (1..N). Paginação simples.
- casacivil: Casa Civil do Estado de Rondônia
  Portal: https://www.casacivil.ro.gov.br/leis
  Compilados consolidados — fonte primária para vigente.

Identidade dos arquivos DITEL/Consulegis (verificada em 2026-08-29):
- o índice oficial associa explicitamente o número jurídico ao prefixo numérico
  do arquivo de download; por exemplo, "Lei Complementar n. 432" aponta para
  ``LC432 COMPILADA REVOGADA.pdf``;
- anos e números adjacentes repetem a correspondência (p.ex. LC1, LC2,
  LC67, LC292, LC1056, LC1064, LC1076), distinguindo esse número do ``cód.``
  interno exibido separadamente pelo próprio Consulegis;
- portanto ``L<n>``/``LC<n>`` podem servir como evidência de (tipo, número),
  enquanto o ``cód.`` do portal não deve ser usado como número da norma.
  Fonte de verificação: https://ditel.casacivil.ro.gov.br/COTEL/Livros/
  (listas anuais de leis ordinárias e complementares).

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
