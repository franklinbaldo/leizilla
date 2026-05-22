"""Fontes de leis para São Paulo (slug: 'sp').

Fontes mapeadas em 2026-05 para futura implementação:

- alesp: Assembleia Legislativa do Estado de São Paulo
  Portal: https://www.al.sp.gov.br/legislacao/
  Acesso: busca por tipo/ano/número. JavaScript pesado (Playwright necessário).
  Obs: inclui texto HTML das leis, PDFs nem sempre disponíveis diretamente.

- legisp: LeisSP — compilados oficiais da Secretaria da Casa Civil
  Portal: https://www.legislacao.sp.gov.br/
  Acesso: consulta via CGI antigo (dg280202.nsf). Retorna HTML; PDFs
  acessíveis em links individuais por lei.
  FONTE_CANONICA para vigente compilado.

- doe: Diário Oficial do Estado de São Paulo
  Portal: https://www.imprensaoficial.com.br/
  Acesso: busca por data/seção. Autenticação para download completo.
  Útil para cross-verificação de publicação original.

Notas para implementação:
- LeisSP é o equivalente SP da casacivil RO: melhor fonte de compilados.
- URL padrão LeisSP por número: ainda não auditada — requer discovery manual.
- ALESP pode ter PDFs avulsos; a estrutura de URL não é pública e muda.
- Prioridade: legisp > alesp > doe (consistente com princípio §0.2 SCHEMA.md).
- robots.txt dos três portais: a auditar antes da implementação.
"""

FONTES = ["legisp", "alesp", "doe"]
FONTE_CANONICA = "legisp"

URLS = {
    "legisp": "https://www.legislacao.sp.gov.br/",
    "alesp": "https://www.al.sp.gov.br/legislacao/",
    "doe": "https://www.imprensaoficial.com.br/",
}
