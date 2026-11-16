"""Livro-razão de completude — o acervo contra o índice oficial da fonte.

``coverage.py`` mede o funil S1-S4 sobre o que o projeto **já descobriu**; não
enxerga o que nunca encontrou. Este módulo responde à outra pergunta: "quanto da
legislação existe no acervo, e exatamente o que falta?". O denominador é
autoritativo: as listas anuais oficiais do Consulegis (Casa Civil/RO), lidas por
``discovery.parse_casacivil_year_catalog`` a partir das estratégias
``casacivil-year-index`` do manifesto.

Três peças:

1. **Catálogo oficial** (``fetch_catalog``) — uma página por ``(tipo, ano)``.
   Listas de anos passados quase não mudam, então o catálogo é um *snapshot*
   reaproveitável (``load_catalog_snapshot``/``write_catalog_snapshot``): uma
   execução diária só rebusca os anos recentes. Um ano que não pôde ser lido
   fica ``failed``/``pending`` — **desconhecido**, nunca "zero normas".
2. **Acervo no IA** (``collect_holdings``) — mesma enumeração de
   ``coverage.compute_fonte_coverage`` (itens de range → ``index.csv`` →
   arquivos do item), mais S4 (``publisher.list_parsed_raw_ids_strict``) e a
   camada de texto publicada (tabela ``textos``, ADR-0015).
3. **Livro-razão** (``build_ledger``) — uma linha por norma listada, com as
   flags de estágio, mais uma linha por norma que o acervo guarda e o índice não
   lista (órfãs visíveis, não escondidas). ``summarize`` agrega por tipo, ano e
   década; ``write_ledger_parquet`` grava a tabela (docs/SCHEMA.md §3.6).

Toda flag e todo contador é opcional: ``None`` significa "não foi possível
medir", nunca um ``False``/0 silencioso (mesmo contrato de ``coverage.py``).
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from leizilla import catalogo, discovery, ia_utils, publisher, relacoes
from leizilla.coverage import _CHAVE_RE, _UNIDENTIFIED_SUFFIX, _has_text

logger = logging.getLogger(__name__)

LEDGER_VERSION = "0.2"
CATALOG_VERSION = "0.1"
YEAR_INDEX_STRATEGY = "casacivil-year-index"
_USER_AGENT = "leizilla-crawler/0.1"

SUMMARY_FILENAME = "completeness.json"
LEDGER_FILENAME = "completeness.parquet"
CATALOG_FILENAME = "completeness_catalog.json.gz"

# Estado de uma página (tipo, ano) do catálogo.
STATUS_OK = "ok"  # lida ao vivo nesta execução
STATUS_CACHED = "cached"  # reaproveitada do snapshot (ano passado, não rebuscado)
STATUS_STALE = "stale"  # a rebusca falhou; vale a cópia anterior do snapshot
STATUS_FAILED = "failed"  # tentada e não lida — ano desconhecido
STATUS_PENDING = "pending"  # não tentada (limite/recorte de busca) — desconhecido
KNOWN_STATUSES = frozenset({STATUS_OK, STATUS_CACHED, STATUS_STALE})

# Situação de uma linha do livro-razão frente ao índice oficial.
SITUACAO_LISTADA = "listada"
SITUACAO_FORA_DO_INDICE = "fora-do-indice"
SITUACAO_INDICE_INCOMPLETO = "indice-incompleto"
SITUACAO_TIPO_SEM_INDICE = "tipo-sem-indice"

TIPO_LABELS: dict[str, str] = {
    "lei": "Leis ordinárias",
    "lc": "Leis complementares",
    "decreto": "Decretos",
    "decreto-lei": "Decretos-leis",
}

# Ordem e tipos das colunas do Parquet do livro-razão (docs/SCHEMA.md §3.6).
LEDGER_SCHEMA: dict[str, str] = {
    "norma_id": "VARCHAR",
    "ente": "VARCHAR",
    "fonte": "VARCHAR",
    "tipo": "VARCHAR",
    "numero": "INTEGER",
    "sufixo": "VARCHAR",
    "situacao": "VARCHAR",
    "titulo": "VARCHAR",
    "data": "VARCHAR",
    "ano": "INTEGER",
    "decada": "INTEGER",
    "ementa": "VARCHAR",
    "coddoc": "INTEGER",
    "entradas": "INTEGER",
    "arquivos": "VARCHAR",
    "arquivos_listados": "INTEGER",
    "arquivos_preservados": "INTEGER",
    "preservada": "BOOLEAN",
    "com_texto": "BOOLEAN",
    "legivel": "BOOLEAN",
    "estruturada": "BOOLEAN",
    "ia_item": "VARCHAR",
    "texto_id": "VARCHAR",
    "catalogo_obtido_em": "VARCHAR",
    # Catálogo como produto (ADR-0017): derivados só do índice oficial.
    "identidade_incerta": "BOOLEAN",
    "rendicoes": "VARCHAR",
    "situacao_norma": "VARCHAR",
    "situacao_evidencias": "VARCHAR",
    "busca": "VARCHAR",
    "url_oficial": "VARCHAR",
    "url_ia": "VARCHAR",
    "link_publico": "VARCHAR",
}

Identity = tuple[str, int]


# ---------------------------------------------------------------------------
# Catálogo oficial
# ---------------------------------------------------------------------------


@dataclass
class YearPage:
    """Uma lista anual oficial ``(tipo, ano)`` e o que se sabe dela."""

    tipo: str
    ano: int
    url: str
    status: str
    fetched_at: Optional[str] = None
    declarados: Optional[int] = None
    records: list[dict[str, Any]] = field(default_factory=list)
    erro: Optional[str] = None
    # Entradas da lista sem número legível no título: ``[{"coddoc", "titulo"}]``.
    ilegiveis: list[dict[str, Any]] = field(default_factory=list)

    @property
    def known(self) -> bool:
        return self.status in KNOWN_STATUSES

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "tipo": self.tipo,
            "ano": self.ano,
            "url": self.url,
            "fetched_at": self.fetched_at,
            "declarados": self.declarados,
            "records": self.records,
            "ilegiveis": self.ilegiveis,
        }


@dataclass
class Catalog:
    """Catálogo oficial de uma fonte: todas as páginas ``(tipo, ano)`` do recorte."""

    ente: str
    fonte: str
    pages: list[YearPage] = field(default_factory=list)
    live_requests: int = 0

    @property
    def tipos(self) -> list[str]:
        return list(dict.fromkeys(p.tipo for p in self.pages))

    def pages_of(self, tipo: str) -> list[YearPage]:
        return sorted((p for p in self.pages if p.tipo == tipo), key=lambda p: p.ano)

    def complete(self, tipo: str) -> bool:
        pages = self.pages_of(tipo)
        return bool(pages) and all(p.known for p in pages)

    @property
    def known_pages(self) -> int:
        return sum(1 for p in self.pages if p.known)


def year_index_configs(ente: str, fonte: str) -> list[dict[str, Any]]:
    """Configurações ``casacivil-year-index`` da fonte no manifesto (uma por tipo)."""
    manifest = discovery.load_manifest(ente)
    cfgs = manifest.get("fontes", {}).get(fonte, {}).get("discovery", [])
    return [c for c in cfgs if c.get("strategy") == YEAR_INDEX_STRATEGY]


def fontes_with_official_index(ente: str) -> list[str]:
    """Fontes do manifesto que declaram um índice oficial anual."""
    manifest = discovery.load_manifest(ente)
    return [f for f in manifest.get("fontes", {}) if year_index_configs(ente, f)]


def page_from_html(
    tipo: str, ano: int, url: str, html_content: str, fetched_at: str
) -> YearPage:
    """Lê uma lista anual já baixada; ``failed`` se não for a página esperada.

    Uma resposta sem o cabeçalho da lista (página de erro, HTML truncado) ou de
    outro ano não é "ano sem normas": fica ``failed``, isto é, desconhecido. Um
    ano legitimamente vazio traz o cabeçalho do ano e o aviso explícito "Não foi
    encontrado nenhum registro" (``discovery.year_index_page_info``).
    """
    info = discovery.year_index_page_info(html_content)
    if info["declarados"] is None or info["ano"] is None:
        return YearPage(
            tipo, ano, url, STATUS_FAILED, erro="resposta não é uma lista anual"
        )
    if info["ano"] != ano:
        return YearPage(
            tipo,
            ano,
            url,
            STATUS_FAILED,
            erro=f"página devolvida é do ano {info['ano']}",
        )
    records = discovery.parse_casacivil_year_catalog(html_content, url, tipo, ano)
    return YearPage(
        tipo,
        ano,
        url,
        STATUS_OK,
        fetched_at=fetched_at,
        declarados=info["declarados"],
        records=records,
        ilegiveis=discovery.casacivil_year_unreadable(html_content),
    )


def parse_year_spec(spec: str) -> set[int]:
    """``"1981-1990,2026"`` → conjunto de anos. Levanta ``ValueError`` se malformado."""
    years: set[int] = set()
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        m = re.fullmatch(r"(\d{4})(?:\s*-\s*(\d{4}))?", part)
        if not m:
            raise ValueError(f"recorte de anos inválido: {part!r}")
        start, end = int(m.group(1)), int(m.group(2) or m.group(1))
        if end < start:
            raise ValueError(f"recorte de anos invertido: {part!r}")
        years.update(range(start, end + 1))
    return years


def load_catalog_snapshot(path: Path) -> dict[tuple[str, int], YearPage]:
    """Snapshot do catálogo como ``(tipo, ano) → página`` (status ``cached``).

    Aceita ``.json`` ou ``.json.gz``. Snapshot de outra versão do formato é
    ignorado (devolve vazio): o catálogo é rebuscado em vez de mal interpretado.
    """
    raw = path.read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    data = json.loads(raw.decode("utf-8"))
    if data.get("leizilla_catalog_version") != CATALOG_VERSION:
        logger.warning("Snapshot do catálogo em versão desconhecida — ignorado")
        return {}
    pages: dict[tuple[str, int], YearPage] = {}
    for p in data.get("pages", []):
        page = YearPage(
            tipo=str(p["tipo"]),
            ano=int(p["ano"]),
            url=str(p.get("url", "")),
            status=STATUS_CACHED,
            fetched_at=p.get("fetched_at"),
            declarados=p.get("declarados"),
            records=list(p.get("records", [])),
            ilegiveis=list(p.get("ilegiveis", [])),
        )
        pages[(page.tipo, page.ano)] = page
    return pages


def count_catalog_snapshot_years(path: Path) -> int:
    """Quantas listas anuais o snapshot traz (0 se a versão é desconhecida).

    Usa o mesmo leitor de ``load_catalog_snapshot``. Levanta ``OSError`` ou
    ``ValueError`` (inclui ``json.JSONDecodeError``/``gzip.BadGzipFile``) quando o
    arquivo não pode ser lido: quem chama decide se ignora o candidato.
    """
    return len(load_catalog_snapshot(path))


def write_catalog_snapshot(catalog: Catalog, path: Path) -> int:
    """Grava as páginas conhecidas do catálogo; devolve quantas foram gravadas.

    Páginas ``failed``/``pending`` não entram: a próxima execução tenta de novo.
    """
    pages = [p.to_snapshot() for p in catalog.pages if p.known]
    payload = json.dumps(
        {
            "leizilla_catalog_version": CATALOG_VERSION,
            "ente": catalog.ente,
            "fonte": catalog.fonte,
            "pages": pages,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".gz":
        # mtime=0: bytes determinísticos para o mesmo conteúdo.
        payload = gzip.compress(payload, mtime=0)
    path.write_bytes(payload)
    return len(pages)


def fetch_catalog(
    ente: str,
    fonte: str,
    *,
    snapshot: Optional[dict[tuple[str, int], YearPage]] = None,
    refresh_years: int = 2,
    max_fetch: Optional[int] = None,
    fetch_years: Optional[set[int]] = None,
    current_year: Optional[int] = None,
) -> Catalog:
    """Monta o catálogo oficial da fonte: snapshot + busca ao vivo do que falta.

    Para cada ``(tipo, ano)`` do manifesto (``start_year`` até ``end_year`` ou o
    ano corrente):

    - ano recente (os últimos ``refresh_years``) → sempre rebuscado; se a busca
      falhar e o snapshot tiver a página, ela vale como ``stale``;
    - ano passado presente no snapshot → reaproveitado (``cached``), sem rede;
    - ano ausente do snapshot → buscado.

    ``max_fetch`` limita o total de requisições ao vivo e ``fetch_years``
    restringe quais anos podem ser buscados; o que ficar de fora é ``pending``
    (desconhecido) e entra numa execução seguinte. A busca reusa
    ``CasacivilYearIndexDiscovery`` (robots.txt, User-Agent e ~1 req/s, ADR-0008),
    do ano mais recente para o mais antigo, alternando os tipos.
    """
    snapshot = snapshot or {}
    year_now = current_year or datetime.now(tz=timezone.utc).year
    catalog = Catalog(ente=ente, fonte=fonte)

    strategies: dict[str, discovery.CasacivilYearIndexDiscovery] = {}
    wanted: list[tuple[int, str]] = []
    for cfg in year_index_configs(ente, fonte):
        strategy = discovery.CasacivilYearIndexDiscovery(cfg, ente, fonte)
        strategies[strategy.tipo] = strategy
        end_year = strategy.end_year or year_now
        wanted.extend(
            (ano, strategy.tipo) for ano in range(strategy.start_year, end_year + 1)
        )
    # Mais recente primeiro; dentro do ano, na ordem do manifesto.
    order = {tipo: i for i, tipo in enumerate(strategies)}
    wanted.sort(key=lambda w: (-w[0], order[w[1]]))

    robots_blocked = False
    for ano, tipo in wanted:
        strategy = strategies[tipo]
        url = strategy.url_template.format(ano=ano)
        cached = snapshot.get((tipo, ano))
        recent = ano > year_now - refresh_years
        if cached is not None and not recent:
            catalog.pages.append(cached)
            continue

        missing = YearPage(tipo, ano, url, STATUS_PENDING)
        if fetch_years is not None and ano not in fetch_years:
            catalog.pages.append(
                _unread(missing, cached, STATUS_PENDING, "fora do recorte de busca")
            )
            continue
        if max_fetch is not None and catalog.live_requests >= max_fetch:
            catalog.pages.append(
                _unread(missing, cached, STATUS_PENDING, "limite de requisições")
            )
            continue
        if robots_blocked or not strategy._allowed(url):
            robots_blocked = True
            catalog.pages.append(
                _unread(missing, cached, STATUS_FAILED, "bloqueado por robots.txt")
            )
            continue

        time.sleep(discovery._YEAR_INDEX_RATE_LIMIT_S)
        catalog.live_requests += 1
        html_content = strategy._fetch(url)
        if html_content is None:
            catalog.pages.append(
                _unread(missing, cached, STATUS_FAILED, "falha de rede")
            )
            continue
        page = page_from_html(
            tipo, ano, url, html_content, datetime.now(tz=timezone.utc).isoformat()
        )
        if not page.known:
            page = _unread(
                missing, cached, STATUS_FAILED, page.erro or "página inesperada"
            )
        catalog.pages.append(page)

    catalog.pages.sort(key=lambda p: (order.get(p.tipo, 0), p.ano))
    return catalog


def _unread(
    page: YearPage, cached: Optional[YearPage], status: str, erro: str
) -> YearPage:
    """Página que não foi lida agora: a cópia do snapshot (``stale``), se houver,
    senão desconhecida com o ``status`` e o motivo dados."""
    if cached is not None:
        return YearPage(
            page.tipo,
            page.ano,
            cached.url or page.url,
            STATUS_STALE,
            fetched_at=cached.fetched_at,
            declarados=cached.declarados,
            records=cached.records,
            ilegiveis=cached.ilegiveis,
            erro=erro,
        )
    return YearPage(page.tipo, page.ano, page.url, status, erro=erro)


# ---------------------------------------------------------------------------
# Acervo no Internet Archive
# ---------------------------------------------------------------------------


def file_key(source: str) -> str:
    """Chave de comparação de um arquivo: nome-base em minúsculas, sem %-escapes.

    Casa a coluna ``source`` do ``index.csv`` (URL de origem, http ou https,
    ``COTEL`` ou ``cotel``) com o arquivo listado no índice oficial.
    """
    path = urllib.parse.urlsplit(source).path or source
    name = urllib.parse.unquote(path).rsplit("/", 1)[-1]
    return re.sub(r"\s+", " ", name).strip().lower()


@dataclass
class Capture:
    """Uma linha de ``index.csv``: um arquivo preservado de uma identidade."""

    key: str
    sha256: str
    has_text: Optional[bool]
    pdf_name: Optional[str] = None  # nome do PDF dentro do item de range


@dataclass
class Held:
    """O que o acervo guarda de uma identidade ``(tipo, numero)`` de range."""

    ia_item: str
    captures: list[Capture] = field(default_factory=list)

    def text(self, captures: Optional[Iterable[Capture]] = None) -> Optional[bool]:
        """True se alguma captura tem texto; None se alguma não pôde ser medida."""
        flags = [c.has_text for c in (self.captures if captures is None else captures)]
        if any(flags):
            return True
        return None if any(f is None for f in flags) else False


@dataclass
class Holdings:
    """Acervo de uma fonte no IA, por identidade, com o estado de cada medição."""

    held: dict[Identity, Held] = field(default_factory=dict)
    ok_s2_s3: bool = True
    parsed: Optional[set[Identity]] = None  # None: S4 não pôde ser medido
    textos: Optional[dict[Identity, str]] = None  # identidade → sha256_fonte


def collect_holdings(
    ente: str, fonte: str, textos: Optional[dict[Identity, str]] = None
) -> Holdings:
    """Lê do IA o que a fonte tem preservado (S2), com texto (S3) e estruturado (S4).

    Mesma enumeração de ``coverage.compute_fonte_coverage``, mas guardando a
    identidade de cada norma (e o arquivo de origem de cada captura) em vez de só
    contar. ``textos`` é o conjunto de normas legíveis na camada de texto
    publicada (``read_textos_keys``); ``None`` = não medido.
    """
    holdings = Holdings(textos=textos)

    item_ids = publisher.scrape_identifiers(f"leizilla_{ente.lower()}_{fonte.lower()}_")
    if item_ids is None:
        holdings.ok_s2_s3 = False
        item_ids = []

    for item_id in item_ids:
        if item_id.endswith(_UNIDENTIFIED_SUFFIX):
            continue  # área de espera: preservado, mas sem identidade (não é S2)
        try:
            index_csv = publisher.fetch_existing_index(item_id)
        except publisher.IndexFetchError:
            holdings.ok_s2_s3 = False
            continue
        if index_csv is None:
            continue
        files = publisher.fetch_item_filenames(item_id)
        if files is None:
            holdings.ok_s2_s3 = False
        for row in csv.DictReader(io.StringIO(index_csv)):
            tipo = row.get("tipo", "")
            numero_s = row.get("numero", "")
            if not tipo or not numero_s or not numero_s.isdigit():
                continue
            entry = holdings.held.setdefault(
                (tipo, int(numero_s)), Held(ia_item=item_id)
            )
            pdf_name: Optional[str] = None
            if row.get("formato") == "pdf" and row.get("uuid5"):
                pdf_name = ia_utils.raw_filename(
                    row["uuid5"], ".pdf", name_prefix=f"{tipo}-{int(numero_s):05d}"
                )
            entry.captures.append(
                Capture(
                    key=file_key(row.get("source", "")),
                    sha256=row.get("sha256", ""),
                    has_text=_has_text(
                        row.get("formato", ""), row.get("uuid5", ""), files
                    ),
                    pdf_name=pdf_name,
                )
            )

    parsed_raw_ids = publisher.list_parsed_raw_ids_strict(ente, fonte)
    if parsed_raw_ids is not None:
        prefix = f"leizilla-raw-{ente.lower()}-{fonte.lower()}-"
        holdings.parsed = set()
        for raw_id in parsed_raw_ids:
            m = (
                _CHAVE_RE.match(raw_id[len(prefix) :])
                if raw_id.startswith(prefix)
                else None
            )
            if m:
                holdings.parsed.add((m.group("tipo"), int(m.group("numero"))))
    return holdings


def read_textos_keys(path: Path, ente: str, fonte: str) -> dict[Identity, str]:
    """Normas legíveis de uma fonte num ``textos.parquet``: identidade → sha256_fonte.

    Só as colunas de chave são lidas — o texto em si nunca é carregado.
    """
    import duckdb

    conn = duckdb.connect()
    try:
        rows = conn.execute(
            "SELECT tipo, numero, sha256_fonte FROM read_parquet(?) "
            "WHERE lower(ente) = ? AND lower(fonte) = ?",
            [str(path), ente.lower(), fonte.lower()],
        ).fetchall()
    finally:
        conn.close()
    return {(str(t), int(n)): str(sha or "") for t, n, sha in rows}


def fetch_published_textos(ente: str, version: int, dest: Path) -> bool:
    """Baixa o ``textos.parquet`` publicado (ponteiro latest) para ``dest``.

    ``False`` se não foi possível (item ainda não publicado, rede): quem chama
    trata "legível" como não medido, nunca como zero.
    """
    item = publisher.textos_item_identifier(ente, version, "latest")
    url = f"https://archive.org/download/{item}/textos.parquet"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=120) as resp:
            dest.write_bytes(resp.read())
    except (urllib.error.URLError, OSError) as e:
        logger.warning(f"textos.parquet publicado indisponível ({url}): {e}")
        return False
    return True


# ---------------------------------------------------------------------------
# Livro-razão
# ---------------------------------------------------------------------------


def norma_id(ente: str, fonte: str, tipo: str, numero: int, sufixo: str = "") -> str:
    """Chave da linha: o raw_id legado da norma, mais o sufixo de letra se houver.

    Sem sufixo é exatamente o ``texto_id`` da tabela ``textos`` e o ``ia_id`` de
    ``versoes.fontes`` (``leizilla-raw-ro-casacivil-lei-05120``); com sufixo a
    letra é anexada em minúscula (``…-decreto-lei-00009a``).
    """
    base = f"leizilla-raw-{ente.lower()}-{fonte.lower()}-{tipo.lower()}-{numero:05d}"
    return base + sufixo.lower()


def _merge_official(catalog: Catalog) -> dict[tuple[str, int, str], dict[str, Any]]:
    """Uma norma por ``(tipo, numero, sufixo)``, unindo entradas repetidas.

    O índice oficial às vezes lista a mesma norma duas vezes (dois ``coddoc``,
    mesmo título e arquivo). Vira uma linha só, com ``entradas`` > 1, o menor
    ``coddoc`` e a união dos arquivos.
    """
    norms: dict[tuple[str, int, str], dict[str, Any]] = {}
    for page in catalog.pages:
        if not page.known:
            continue
        for rec in page.records:
            key = (page.tipo, int(rec["numero"]), str(rec.get("sufixo") or ""))
            norm = norms.get(key)
            if norm is None:
                norms[key] = {
                    **rec,
                    "tipo": page.tipo,
                    "ano": rec.get("ano") or page.ano,
                    "arquivos": list(rec.get("arquivos", [])),
                    "entradas": 1,
                    "fetched_at": page.fetched_at,
                }
                continue
            norm["entradas"] += 1
            norm["coddoc"] = min(int(norm["coddoc"]), int(rec["coddoc"]))
            seen = {a["url"] for a in norm["arquivos"]}
            norm["arquivos"].extend(
                a for a in rec.get("arquivos", []) if a["url"] not in seen
            )
            if not norm.get("ementa"):
                norm["ementa"] = rec.get("ementa", "")
            if not norm.get("data"):
                norm["data"] = rec.get("data")
    return norms


def build_ledger(catalog: Catalog, holdings: Holdings) -> list[dict[str, Any]]:
    """Junta o catálogo oficial com o acervo: as linhas do livro-razão.

    Uma linha por norma listada (``situacao = listada``) e uma por identidade
    que o acervo guarda e o índice não lista:

    - ``fora-do-indice`` — o tipo tem índice, todos os anos foram lidos e a
      norma não está em nenhum (órfã de fato: número errado, ato de outro tipo);
    - ``indice-incompleto`` — o tipo tem índice mas algum ano está desconhecido;
      a norma pode estar justamente nesse ano;
    - ``tipo-sem-indice`` — a fonte não publica lista anual desse tipo.

    Identidade: o acervo é chaveado por ``(tipo, numero)``. Quando o índice traz
    mais de uma norma para o mesmo número (``9`` e ``9A``), cada uma é casada
    pelo **arquivo** (``index.csv.source`` × arquivo listado); o que não for
    reivindicado por uma norma com sufixo fica com a norma sem sufixo. S4 e a
    camada de texto só conhecem ``(tipo, numero)``: ``estruturada`` de uma norma
    com sufixo é ``None``, e ``legivel`` segue o arquivo de origem do texto.
    """
    ente, fonte = catalog.ente, catalog.fonte
    norms = _merge_official(catalog)
    siblings: dict[Identity, list[tuple[str, int, str]]] = {}
    for key in norms:
        siblings.setdefault((key[0], key[1]), []).append(key)

    absent: Optional[bool] = False if holdings.ok_s2_s3 else None
    rows: list[dict[str, Any]] = []

    for key in sorted(norms):
        tipo, numero, sufixo = key
        norm = norms[key]
        identity = (tipo, numero)
        held = holdings.held.get(identity)
        listed_keys = {file_key(a["url"]) for a in norm["arquivos"]}
        ambiguous = len(siblings[identity]) > 1

        mine: list[Capture] = []
        if held is not None:
            if not ambiguous:
                mine = held.captures
            else:
                claimed_by_others = {
                    file_key(a["url"])
                    for other in siblings[identity]
                    if other != key
                    for a in norms[other]["arquivos"]
                }
                mine = [
                    c
                    for c in held.captures
                    if c.key in listed_keys
                    or (not sufixo and c.key not in claimed_by_others)
                ]

        preservada: Optional[bool] = True if mine else absent
        com_texto: Optional[bool] = (
            held.text(mine) if held is not None and mine else absent
        )

        legivel: Optional[bool] = None
        if holdings.textos is not None:
            sha = holdings.textos.get(identity)
            if sha is None:
                legivel = False
            elif not ambiguous:
                legivel = True
            else:
                source = next(
                    (c for c in (held.captures if held else []) if c.sha256 == sha),
                    None,
                )
                legivel = (
                    any(c.sha256 == sha for c in mine)
                    if source is not None
                    else not sufixo
                )

        estruturada: Optional[bool] = None
        if holdings.parsed is not None and not sufixo:
            estruturada = identity in holdings.parsed

        ano = int(norm["ano"]) if norm.get("ano") is not None else None
        situacao_norma, evidencias = catalogo.situacao_da_norma(
            (a.get("rendicao") or "outra" for a in norm["arquivos"]),
            norm.get("ementa") or "",
        )
        oficial = catalogo.url_oficial(norm["arquivos"])
        ia_pdf = next((c.pdf_name for c in mine if c.pdf_name), None)
        url_ia = (
            ia_utils.download_url(held.ia_item, ia_pdf)
            if held is not None and ia_pdf
            else None
        )
        rows.append(
            {
                "norma_id": norma_id(ente, fonte, tipo, numero, sufixo),
                "ente": ente,
                "fonte": fonte,
                "tipo": tipo,
                "numero": numero,
                "sufixo": sufixo,
                "situacao": SITUACAO_LISTADA,
                "titulo": norm.get("titulo") or "",
                "data": norm.get("data"),
                "ano": ano,
                "decada": (ano // 10) * 10 if ano is not None else None,
                "ementa": norm.get("ementa") or "",
                "coddoc": norm.get("coddoc"),
                "entradas": norm["entradas"],
                "arquivos": json.dumps(norm["arquivos"], ensure_ascii=False),
                "arquivos_listados": len(norm["arquivos"]),
                "arquivos_preservados": (
                    None
                    if not holdings.ok_s2_s3 and held is None
                    else len(listed_keys & {c.key for c in mine})
                ),
                "preservada": preservada,
                "com_texto": com_texto,
                "legivel": legivel,
                "estruturada": estruturada,
                "ia_item": held.ia_item if held is not None and mine else None,
                "texto_id": norma_id(ente, fonte, tipo, numero),
                "catalogo_obtido_em": norm.get("fetched_at"),
                "identidade_incerta": bool(norm.get("identidade_incerta")),
                "rendicoes": catalogo.rendicoes_distintas(norm["arquivos"]),
                "situacao_norma": situacao_norma,
                "situacao_evidencias": ",".join(evidencias),
                "busca": catalogo.campo_busca(
                    norm.get("titulo") or "", norm.get("ementa") or ""
                ),
                "url_oficial": oficial,
                "url_ia": url_ia,
                "link_publico": url_ia or oficial,
            }
        )

    # Identidades que o acervo guarda e o índice oficial não lista.
    listed_identities = set(siblings)
    extra: set[Identity] = set(holdings.held)
    extra |= holdings.parsed or set()
    extra |= set(holdings.textos or {})
    indexed_tipos = set(catalog.tipos)
    for identity in sorted(extra - listed_identities):
        tipo, numero = identity
        held = holdings.held.get(identity)
        if tipo not in indexed_tipos:
            situacao = SITUACAO_TIPO_SEM_INDICE
        elif catalog.complete(tipo):
            situacao = SITUACAO_FORA_DO_INDICE
        else:
            situacao = SITUACAO_INDICE_INCOMPLETO
        rows.append(
            {
                "norma_id": norma_id(ente, fonte, tipo, numero),
                "ente": ente,
                "fonte": fonte,
                "tipo": tipo,
                "numero": numero,
                "sufixo": "",
                "situacao": situacao,
                "titulo": "",
                "data": None,
                "ano": None,
                "decada": None,
                "ementa": "",
                "coddoc": None,
                "entradas": 0,
                "arquivos": "[]",
                "arquivos_listados": 0,
                "arquivos_preservados": 0,
                "preservada": True if held is not None else absent,
                "com_texto": held.text() if held is not None else absent,
                "legivel": (
                    None if holdings.textos is None else identity in holdings.textos
                ),
                "estruturada": (
                    None if holdings.parsed is None else identity in holdings.parsed
                ),
                "ia_item": held.ia_item if held is not None else None,
                "texto_id": norma_id(ente, fonte, tipo, numero),
                "catalogo_obtido_em": None,
                "identidade_incerta": None,
                "rendicoes": "",
                "situacao_norma": None,
                "situacao_evidencias": "",
                "busca": catalogo.normalizar_busca(f"{tipo} {numero}"),
                "url_oficial": None,
                "url_ia": None,
                "link_publico": None,
            }
        )
    return rows


def write_ledger_parquet(rows: list[dict[str, Any]], output_path: Path) -> None:
    """Grava o livro-razão em Parquet (ZSTD), ordenado por tipo, número e sufixo."""
    if not rows:
        raise ValueError("rows is empty — nothing to write")
    relacoes.rows_to_parquet(
        rows, LEDGER_SCHEMA, output_path, "tipo, numero, sufixo, situacao"
    )


# ---------------------------------------------------------------------------
# Resumo
# ---------------------------------------------------------------------------

_STAGES: tuple[tuple[str, str], ...] = (
    ("preservadas", "preservada"),
    ("com_texto", "com_texto"),
    ("legiveis", "legivel"),
    ("estruturadas", "estruturada"),
)


def _pct(part: Optional[int], total: int) -> Optional[float]:
    if part is None or total <= 0:
        return None
    return round(100.0 * part / total, 1)


def _stage_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Contadores de estágio de um grupo de linhas listadas.

    Um contador é ``None`` se alguma linha do grupo não pôde ser medida naquele
    estágio — exceto ``estruturadas``, em que a norma com sufixo (nunca medível
    por identidade) simplesmente não conta.
    """
    listadas = len(rows)
    out: dict[str, Any] = {"listadas": listadas}
    for name, flag in _STAGES:
        values = [r[flag] for r in rows if not (flag == "estruturada" and r["sufixo"])]
        count: Optional[int] = (
            None if any(v is None for v in values) else sum(1 for v in values if v)
        )
        out[name] = count
        out[f"pct_{name}"] = _pct(count, listadas)
    out["faltantes"] = (
        None if out["preservadas"] is None else listadas - out["preservadas"]
    )
    return out


def _unknown_counts() -> dict[str, Any]:
    out: dict[str, Any] = {"listadas": None, "faltantes": None}
    for name, _ in _STAGES:
        out[name] = None
        out[f"pct_{name}"] = None
    return out


def number_ranges(numbers: Iterable[int]) -> list[list[int]]:
    """``[1, 2, 3, 7]`` → ``[[1, 3], [7, 7]]`` — forma compacta para o resumo."""
    ranges: list[list[int]] = []
    for n in sorted(set(numbers)):
        if ranges and n == ranges[-1][1] + 1:
            ranges[-1][1] = n
        else:
            ranges.append([n, n])
    return ranges


def summarize(
    catalog: Catalog,
    holdings: Holdings,
    rows: list[dict[str, Any]],
    *,
    generated_at: Optional[str] = None,
    git_sha: Optional[str] = None,
) -> dict[str, Any]:
    """Resumo publicável do livro-razão: por tipo, por década e por ano.

    Só as normas ``listada`` entram nos contadores e percentuais. Ano
    desconhecido (``failed``/``pending``) aparece com contadores ``None`` e é
    listado em ``catalogo.anos_desconhecidos``; a década que o contém soma só os
    anos lidos e fica marcada ``completa: false``.

    Duas checagens da própria leitura ficam em ``catalogo``:
    ``entradas_ilegiveis`` (entradas oficiais cujo título não tem número — existem,
    mas não viram linha) e ``divergencias`` (o total declarado no cabeçalho da
    lista difere das entradas lidas: o parser perdeu algo).
    """
    tipos_out: list[dict[str, Any]] = []
    unknown_years: list[dict[str, Any]] = []
    stale_years: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    unreadable: list[dict[str, Any]] = []

    for tipo in catalog.tipos:
        pages = catalog.pages_of(tipo)
        listed = [
            r for r in rows if r["tipo"] == tipo and r["situacao"] == SITUACAO_LISTADA
        ]
        by_year: dict[int, list[dict[str, Any]]] = {}
        for r in listed:
            by_year.setdefault(int(r["ano"]), []).append(r)

        por_ano: list[dict[str, Any]] = []
        decades: dict[int, dict[str, Any]] = {}
        for page in pages:
            decada = (page.ano // 10) * 10
            dec = decades.setdefault(
                decada, {"rows": [], "anos": 0, "anos_desconhecidos": 0}
            )
            dec["anos"] += 1
            if not page.known:
                dec["anos_desconhecidos"] += 1
                unknown_years.append(
                    {
                        "tipo": tipo,
                        "ano": page.ano,
                        "status": page.status,
                        "erro": page.erro,
                    }
                )
                por_ano.append(
                    {"ano": page.ano, "status": page.status, **_unknown_counts()}
                )
                continue
            if page.status == STATUS_STALE:
                stale_years.append(
                    {"tipo": tipo, "ano": page.ano, "obtido_em": page.fetched_at}
                )
            unreadable.extend(
                {"tipo": tipo, "ano": page.ano, **entry} for entry in page.ilegiveis
            )
            lidos = len(page.records) + len(page.ilegiveis)
            if page.declarados is not None and page.declarados != lidos:
                mismatches.append(
                    {
                        "tipo": tipo,
                        "ano": page.ano,
                        "declarados": page.declarados,
                        "lidos": lidos,
                    }
                )
            year_rows = by_year.get(page.ano, [])
            dec["rows"].extend(year_rows)
            por_ano.append(
                {"ano": page.ano, "status": page.status, **_stage_counts(year_rows)}
            )

        por_decada = [
            {
                "decada": decada,
                "anos": dec["anos"],
                "anos_desconhecidos": dec["anos_desconhecidos"],
                "completa": dec["anos_desconhecidos"] == 0,
                **(
                    _stage_counts(dec["rows"])
                    if dec["anos_desconhecidos"] < dec["anos"]
                    else _unknown_counts()
                ),
            }
            for decada, dec in sorted(decades.items())
        ]

        missing = [r for r in listed if r["preservada"] is False]
        extras = [
            r for r in rows if r["tipo"] == tipo and r["situacao"] != SITUACAO_LISTADA
        ]
        totals = _stage_counts(listed) if any(p.known for p in pages) else None
        tipos_out.append(
            {
                "tipo": tipo,
                "rotulo": TIPO_LABELS.get(tipo, tipo),
                "ano_inicial": pages[0].ano if pages else None,
                "ano_final": pages[-1].ano if pages else None,
                "anos": len(pages),
                "anos_lidos": sum(1 for p in pages if p.known),
                "catalogo_completo": catalog.complete(tipo),
                **(totals if totals is not None else _unknown_counts()),
                "entradas_repetidas": sum(r["entradas"] - 1 for r in listed),
                "fora_do_indice": sum(
                    1 for r in extras if r["situacao"] == SITUACAO_FORA_DO_INDICE
                ),
                "indice_incompleto": sum(
                    1 for r in extras if r["situacao"] == SITUACAO_INDICE_INCOMPLETO
                ),
                "faltantes_intervalos": number_ranges(
                    r["numero"] for r in missing if not r["sufixo"]
                ),
                "faltantes_com_sufixo": [
                    f"{r['numero']}{r['sufixo']}" for r in missing if r["sufixo"]
                ],
                "por_decada": por_decada,
                "por_ano": por_ano,
            }
        )

    sem_indice: dict[str, int] = {}
    for r in rows:
        if r["situacao"] == SITUACAO_TIPO_SEM_INDICE:
            sem_indice[r["tipo"]] = sem_indice.get(r["tipo"], 0) + 1

    return {
        "leizilla_completeness_version": LEDGER_VERSION,
        "ente": catalog.ente,
        "fonte": catalog.fonte,
        "generated_at": generated_at or datetime.now(tz=timezone.utc).isoformat(),
        "git_sha": git_sha,
        "catalogo": {
            "completo": all(catalog.complete(t) for t in catalog.tipos)
            and bool(catalog.tipos),
            "paginas": len(catalog.pages),
            "paginas_lidas": catalog.known_pages,
            "requisicoes_ao_vivo": catalog.live_requests,
            "anos_desconhecidos": unknown_years,
            "anos_desatualizados": stale_years,
            "divergencias": mismatches,
            "entradas_ilegiveis": unreadable,
        },
        "medicao": {
            "ok_s2_s3": holdings.ok_s2_s3,
            "ok_s4": holdings.parsed is not None,
            "ok_legivel": holdings.textos is not None,
        },
        "linhas": len(rows),
        "normas_listadas": sum(1 for r in rows if r["situacao"] == SITUACAO_LISTADA),
        "tipos": tipos_out,
        "tipos_sem_indice": [
            {"tipo": t, "preservadas": n} for t, n in sorted(sem_indice.items())
        ],
        "arquivos": {"parquet": LEDGER_FILENAME, "catalogo": CATALOG_FILENAME},
    }
