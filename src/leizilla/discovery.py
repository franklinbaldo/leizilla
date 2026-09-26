"""Módulo de descobrimento de recursos legislativos (Discovery).

Lê manifestos declarativos por ente e popula a tabela de discovered_resources.
"""

import json
import logging
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Callable

from leizilla.storage import DuckDBStorage

logger = logging.getLogger(__name__)


class DiscoveryStrategyProtocol(Protocol):
    """Protocolo para estratégias de descoberta de recursos."""

    def __init__(self, config: Dict[str, Any], ente: str, fonte: str) -> None: ...

    def run(self, storage: Optional[DuckDBStorage] = None) -> List[Dict[str, Any]]: ...


def _ditel_editorial_number(value: str) -> Optional[str]:
    """Return the leading number when the suffix is verified DITEL editorial text."""
    match = re.fullmatch(
        r"(\d+)(?:\s*-\s*|\s+)(?:COMPILAD[AO]|REVOGAD[AO])"
        r"(?:(?:\s*-\s*|\s+)(?:COMPILAD[AO]|REVOGAD[AO]))*",
        value,
    )
    return match.group(1) if match else None


def parse_filename(filename: str) -> tuple[Optional[str], Optional[str]]:
    """Extrai tipo_documento e chave formatada do nome do arquivo.

    Exemplos:
      L5120.pdf    -> ("lei", "lei-05120")
      LC312.pdf    -> ("lc", "lc-00312")
      D1234.pdf    -> ("decreto", "decreto-01234")
      EC10.pdf     -> ("ec", "ec-00010")
      Res50.pdf    -> ("resolucao", "resolucao-00050")
      Port100.pdf  -> ("portaria", "portaria-00100")
      DEC1026.pdf  -> ("decreto", "decreto-01026")
      DL11.pdf     -> ("decreto-lei", "decreto-lei-00011")
    """
    # Remove extensão e limpa espaços
    name = filename.rsplit(".", 1)[0].strip().upper()
    # Ordered from longest prefix to shortest to avoid partial matches
    if name.startswith("PORT"):
        num_part = name[4:]
        if num_part.isdigit():
            return "portaria", f"portaria-{int(num_part):05d}"
    elif name.startswith("RES"):
        num_part = name[3:]
        if num_part.isdigit():
            return "resolucao", f"resolucao-{int(num_part):05d}"
    elif name.startswith("DEC"):
        num_part = name[3:]
        if num_part.isdigit():
            return "decreto", f"decreto-{int(num_part):05d}"
    elif name.startswith("LC"):
        num_part = name[2:]
        number = num_part if num_part.isdigit() else _ditel_editorial_number(num_part)
        if number is not None:
            return "lc", f"lc-{int(number):05d}"
    elif name.startswith("EC"):
        num_part = name[2:]
        if num_part.isdigit():
            return "ec", f"ec-{int(num_part):05d}"
    elif name.startswith("DL"):
        num_part = name[2:]
        if num_part.isdigit():
            return "decreto-lei", f"decreto-lei-{int(num_part):05d}"
    elif name.startswith("L"):
        num_part = name[1:]
        number = num_part if num_part.isdigit() else _ditel_editorial_number(num_part)
        if number is not None:
            return "lei", f"lei-{int(number):05d}"
    elif name.startswith("D"):
        num_part = name[1:]
        if num_part.isdigit():
            return "decreto", f"decreto-{int(num_part):05d}"
    return None, None


def _fetch_cdx_pdf_records(prefix: str) -> List[Dict[str, str]]:
    """Consulta a API CDX da Wayback Machine para `prefix`.

    Retorna as capturas `.pdf`/HTTP 200 casadas, cada uma como
    ``{"orig_url": ..., "timestamp": ...}``. Fail-safe (ADR: fail-open):
    erro de rede, timeout e resposta vazia/malformada retornam ``[]`` em vez
    de propagar a exceção — quem chama decide o fallback.
    """
    # Consulta sem esquema (urlkey é SURT, scheme-agnóstico): casa capturas http E
    # https — as históricas da DITEL são http-keyed, o download ao vivo é https
    # (Codex P1). Sem isto, um prefixo só-https perderia os snapshots antigos.
    prefix_key = re.sub(r"^https?://", "", prefix)
    url = f"https://web.archive.org/cdx/search/cdx?url={urllib.parse.quote(prefix_key)}&matchType=prefix&output=json"
    req = urllib.request.Request(url, headers={"User-Agent": "leizilla-crawler/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Erro ao consultar a API CDX para {prefix}: {e}")
        return []

    if not data or len(data) <= 1:
        return []

    records = []
    for row in data[1:]:
        try:
            orig_url, timestamp, status = row[2], row[1], row[4]
        except (IndexError, TypeError):
            continue
        if orig_url.lower().endswith(".pdf") and status == "200":
            records.append({"orig_url": orig_url, "timestamp": timestamp})
    return records


def resolve_cdx_max_by_tipo(prefix: str) -> Dict[str, int]:
    """Maior número de identificador já arquivado, por `tipo_documento`.

    Consulta a CDX API uma única vez para `prefix` e classifica cada PDF
    casado via `parse_filename` (mesma identidade usada pelo catálogo,
    ADR-0011 §1). Fail-safe: qualquer falha ou resposta vazia resulta em
    `{}` — quem chama decide o fallback (nunca propaga exceção, nunca aborta
    o batch de descoberta).
    """
    cdx_max: Dict[str, int] = {}
    for record in _fetch_cdx_pdf_records(prefix):
        filename = record["orig_url"].split("/")[-1]
        tipo, chave = parse_filename(filename)
        if not tipo or not chave:
            continue
        try:
            num = int(chave.rsplit("-", 1)[-1])
        except ValueError:
            continue
        cdx_max[tipo] = max(cdx_max.get(tipo, 0), num)
    return cdx_max


class WaybackCdxDiscovery:
    """Estratégia de descobrimento que consulta a API CDX da Wayback Machine."""

    def __init__(self, config: Dict[str, Any], ente: str, fonte: str) -> None:
        self.prefix = config["prefix"]
        # Esquema canônico (do manifesto): normalizamos as URLs descobertas para ele de
        # modo que casem com as da estratégia sequencial — discovered_resources é keyed
        # pela URL literal, então http://…/L1.pdf e https://…/L1.pdf seriam duas linhas
        # (mesma norma colhida duas vezes). O snapshot http real fica em wayback_snapshot.
        self.canonical_scheme = "https" if self.prefix.startswith("https") else "http"
        self.ente = ente
        self.fonte = fonte

    def run(self, storage: Optional[DuckDBStorage] = None) -> List[Dict[str, Any]]:
        logger.info(f"Rodando Wayback CDX Discovery para {self.ente}/{self.fonte}...")
        resources = []

        for record in _fetch_cdx_pdf_records(self.prefix):
            orig_url = record["orig_url"]
            timestamp = record["timestamp"]
            filename = orig_url.split("/")[-1]
            tipo, chave = parse_filename(filename)
            if not tipo or not chave:
                # Identidade é evidência, não catraca (ADR-0011 §1): capturamos
                # mesmo sem (tipo, número) no nome. Prefixo NÃO-identificante
                # "documento-" garante que parse_identity devolva None — senão um
                # stem com forma "{palavra}-{dígitos}" (ex.: "oficio-123") seria
                # promovido a um range navegável espúrio em vez da área de espera
                # _unidentified. O harvest key (nome do arquivo) fica preservado.
                tipo, chave = "", f"documento-{filename.rsplit('.', 1)[0]}"

            # snapshot real (preserva o esquema arquivado, p.ex. http); a chave de
            # dedup (url) é normalizada para o esquema canônico do manifesto.
            wayback_url = f"https://web.archive.org/web/{timestamp}/{orig_url}"
            dedup_url = re.sub(r"^https?://", f"{self.canonical_scheme}://", orig_url)
            resources.append(
                {
                    "url": dedup_url,
                    "ente": self.ente,
                    "fonte": self.fonte,
                    "tipo_documento": tipo,
                    "chave": chave,
                    "status": "pending",
                    "wayback_snapshot": wayback_url,
                }
            )
        return resources


_HEAD_RATE_LIMIT_S = 0.5


def _head_check_status(url: str, timeout: float = 10.0) -> Optional[bool]:
    """Checagem HEAD de 3 estados: True (existe), False (404 confirmado), None (ambíguo).

    Distinto de um booleano simples porque só um 404 CONFIRMADO é seguro para
    cache permanente (ver `SequentialDiscovery.run`'s marcação de
    "checked_not_found") — um 403/429/500/503 ou uma exceção de rede (timeout,
    WAF derrubando a conexão) é o mesmo sinal de infraestrutura transiente de
    sempre, não uma prova de que o recurso não existe. Cachear isso como
    "não existe" seria uma perda de dados silenciosa e *permanente*, pior que
    o problema que a cache resolve (issue #319: sem cache, cada rodada
    refazia HEAD request para toda a faixa numérica desde sempre).
    """
    try:
        req = urllib.request.Request(
            url,
            method="HEAD",
            headers={"User-Agent": "leizilla-crawler/0.1"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status in (200, 302):
                return True
            return None
    except urllib.error.HTTPError as exc:
        # 404 é resposta normal — a URL candidata simplesmente não existe.
        # Qualquer OUTRO código de erro (403, 429, 500, 503, ...) chega aqui
        # também (urllib levanta HTTPError para toda resposta não-2xx/3xx),
        # mas não é "não existe": é o mesmo sinal de infraestrutura (WAF,
        # rate-limit, servidor fora do ar) que o ramo `except Exception`
        # abaixo já trata com um warning — sem isto, um bloqueio via HTTP
        # (em vez de conexão recusada/timeout) ficava tão silencioso quanto
        # a ambiguidade original do issue #262.
        if exc.code == 404:
            return False
        logger.warning(f"HEAD check retornou {exc.code} (não 404) para {url}")
        return None
    except Exception as exc:
        # Qualquer coisa além de um HTTPError normal (conexão recusada,
        # timeout, TLS/WAF derrubando a conexão) é indistinguível de um 404
        # para quem chama, mas é um sinal de infraestrutura genuíno — sem
        # isto, um bloqueio silencioso (ex.: WAF anti-bot) produz o mesmo
        # "recurso não existe" que um 404 real, tornando uma perda
        # sistemática de descoberta indistinguível de "não há nada aqui".
        logger.warning(f"HEAD check falhou (não é 404) para {url}: {exc!r}")
        return None


def _head_exists(url: str, timeout: float = 10.0) -> bool:
    """Retorna True se HEAD request retornar 200 ou 302 (arquivo existe no servidor)."""
    return bool(_head_check_status(url, timeout=timeout))


def _wayback_snapshot_if_exists(url: str) -> Optional[str]:
    """Retorna a URL do snapshot Wayback existente para ``url``, ou ``None``.

    Existe para substituir `_head_exists` como verificação de existência do
    Planalto (issue #262): uma verificação HEAD direta ao domínio de origem
    falha sistematicamente a partir de runners do GitHub Actions — a
    investigação ao vivo (run 36192448284, após a instrumentação de logging
    de `logger.warning` em `_head_exists`) mostrou 348/348 candidatos
    retornando `RemoteDisconnected`/`TimeoutError`, nunca um 404 real,
    confirmando bloqueio de rede/WAF no runner, não ausência do recurso.
    `wayback.closest_snapshot` consulta a API de disponibilidade do Internet
    Archive (que busca o snapshot já capturado por ela, sem nova requisição
    ao domínio de origem) — imune a esse bloqueio específico. Fail-open:
    qualquer falha na API do IA devolve ``None`` (mesmo tratamento que um
    404 real receberia).
    """
    from leizilla import wayback

    try:
        found = wayback.closest_snapshot(url)
    except Exception as exc:
        logger.warning(f"Wayback existence check falhou para {url}: {exc!r}")
        return None
    return found[0] if found is not None else None


#: Status persistido para uma URL candidata com 404 CONFIRMADO (não um erro
#: ambíguo) — distinto de `status='pending'`/`'downloaded'` para que
#: `get_pending_resources`/`get_downloaded_resources` (filtrados por status
#: exato) nunca a enxerguem como um recurso a processar.
_STATUS_CHECKED_NOT_FOUND = "checked_not_found"


def _mark_checked_not_found(
    storage: Optional[DuckDBStorage], url: str, ente: str, fonte: str
) -> None:
    """Persiste um 404 confirmado para que rodadas futuras pulem o HEAD request.

    `SequentialDiscovery`'s range cresce (`end`) e sua faixa geralmente tem
    lacunas permanentes (números retratados/nunca emitidos) — sem isto, cada
    rodada agendada refazia HEAD request, com rate-limit (~1 req/s, ADR-0008),
    para TODA a faixa desde `start`, não só os candidatos novos desde a
    última rodada, inflando o Discover step para horas e crescendo a cada
    semana (issue #319/#149). Só chamar com um 404 confirmado
    (`_head_check_status(url) is False`) — nunca com um erro ambíguo, o que
    cachearia permanentemente um bloqueio transiente (WAF/rate-limit) como
    "não existe", uma perda de dados silenciosa pior que o problema original.
    """
    if storage is None:
        return
    try:
        storage.insert_resource(
            {
                "url": url,
                "ente": ente,
                "fonte": fonte,
                "tipo_documento": None,
                "chave": None,
                "status": _STATUS_CHECKED_NOT_FOUND,
            }
        )
    except Exception as exc:
        logger.warning(
            f"Erro ao persistir marcador checked_not_found para {url}: {exc!r}"
        )


#: Fallback quando "end": "cdx-auto" não consegue resolver um limite (CDX vazia,
#: com erro/timeout, ou sem capturas para o tipo). Mesmo valor que o antigo
#: default hardcoded em `cmd_scrape`/casacivil (ADR: fail-open, nunca aborta).
DEFAULT_CDX_AUTO_FALLBACK_END = 10


class SequentialDiscovery:
    """Estratégia de descobrimento baseada em templates de URLs sequenciais.

    `end` aceita um inteiro fixo ou a string `"cdx-auto"`: nesse caso o limite
    é resolvido em `run()` consultando a CDX API para o prefixo do template
    (diretório do primeiro template) e tomando o maior número já arquivado
    para o `tipo_documento` desse template (via `resolve_cdx_max_by_tipo`).
    Fail-safe: se a CDX não resolver nada, usa `end_fallback`
    (default `DEFAULT_CDX_AUTO_FALLBACK_END`, configurável no manifesto).
    """

    def __init__(self, config: Dict[str, Any], ente: str, fonte: str) -> None:
        self.templates = config["templates"]
        self.start = int(config["start"])

        end_cfg = config["end"]
        if isinstance(end_cfg, str):
            if end_cfg != "cdx-auto":
                raise ValueError(
                    f"'end' inválido para sequential: {end_cfg!r}. "
                    "Use um inteiro ou a string 'cdx-auto'."
                )
            self.end: Optional[int] = None
            self.cdx_auto = True
        else:
            self.end = int(end_cfg)
            self.cdx_auto = False
        self.end_fallback = int(
            config.get("end_fallback", DEFAULT_CDX_AUTO_FALLBACK_END)
        )

        self.ente = ente
        self.fonte = fonte
        self.head_check: bool = bool(config.get("head_check", False))

    def _resolve_end(self) -> int:
        """Retorna o limite superior do range, resolvendo 'cdx-auto' se preciso."""
        if not self.cdx_auto:
            assert self.end is not None
            return self.end

        tmpl = self.templates[0]
        cdx_prefix = tmpl.rsplit("/", 1)[0] + "/"
        sample_filename = tmpl.format(num=1).split("/")[-1]
        tipo, _ = parse_filename(sample_filename)

        resolved = resolve_cdx_max_by_tipo(cdx_prefix).get(tipo, 0) if tipo else 0
        if resolved <= 0:
            logger.warning(
                f"cdx-auto: não foi possível resolver o limite via CDX para "
                f"{tmpl!r} (tipo={tipo!r}); usando fallback end={self.end_fallback}."
            )
            return self.end_fallback
        return resolved

    def run(self, storage: Optional[DuckDBStorage] = None) -> List[Dict[str, Any]]:
        end = self._resolve_end()
        logger.info(
            f"Rodando Sequential Discovery para {self.ente}/{self.fonte} "
            f"(de {self.start} a {end}, head_check={self.head_check})..."
        )
        import time

        resources = []
        last_head_time = 0.0
        for num in range(self.start, end + 1):
            for tmpl in self.templates:
                url = tmpl.format(num=num)

                if storage:
                    try:
                        conn = storage.connect()
                        res = conn.execute(
                            "SELECT 1 FROM discovered_resources WHERE url = ?", [url]
                        ).fetchone()
                        if res:
                            continue
                    except Exception as e:
                        logger.warning(f"Error checking DB for URL {url}: {e}")

                if self.head_check:
                    # Rate-limit HEAD requests to avoid hammering the server
                    elapsed = time.monotonic() - last_head_time
                    if elapsed < _HEAD_RATE_LIMIT_S:
                        time.sleep(_HEAD_RATE_LIMIT_S - elapsed)
                    head_status = _head_check_status(url)
                    last_head_time = time.monotonic()
                    if head_status is not True:
                        logger.debug(f"HEAD 404/error — skipping {url}")
                        if head_status is False:
                            # 404 confirmado (não um erro ambíguo): seguro
                            # cachear para nunca mais refazer este HEAD.
                            _mark_checked_not_found(storage, url, self.ente, self.fonte)
                        continue

                filename = url.split("/")[-1]
                tipo, chave = parse_filename(filename)
                if not tipo or not chave:
                    # Captura mesmo sem identidade (ADR-0011 §1): vai à área de
                    # espera _unidentified. Prefixo NÃO-identificante "documento-"
                    # garante parse_identity → None mesmo para stems "{palavra}-{díg}".
                    tipo, chave = "", f"documento-{filename.rsplit('.', 1)[0]}"
                resources.append(
                    {
                        "url": url,
                        "ente": self.ente,
                        "fonte": self.fonte,
                        "tipo_documento": tipo,
                        "chave": chave,
                        "status": "pending",
                        "wayback_snapshot": None,
                    }
                )
        logger.info(
            f"Sequential Discovery concluído: {len(resources)} recursos encontrados "
            f"(head_check={self.head_check})"
        )
        return resources


class CasacivilIndexDiscovery:
    """Estratégia de descobrimento que lê a página de índice da Casa Civil."""

    def __init__(self, config: Dict[str, Any], ente: str, fonte: str) -> None:
        self.url = config["url"]
        self.ente = ente
        self.fonte = fonte

    def run(self, storage: Optional[DuckDBStorage] = None) -> List[Dict[str, Any]]:
        # storage não é usado aqui (uma única chamada HTTP, não custa repetir);
        # o parâmetro só existe para uniformizar a assinatura com as demais
        # estratégias (DiscoveryStrategyProtocol.run).
        # ADR-0004 continua Wayback-first, mas uma enumeração autoritativa precisa ser
        # atual. Um snapshot histórico serve à proveniência, não à descoberta de
        # novidades: só reutilizamos capturas dentro da janela de frescor padrão (24 h).
        from leizilla import wayback

        logger.info(
            f"Rodando CasacivilIndex Discovery para {self.ente}/{self.fonte} na URL {self.url}..."
        )
        resources = []

        wb_url = wayback.check_available(self.url)
        html_content = None

        if wb_url:
            html_bytes = wayback.fetch_bytes(wb_url)
            if html_bytes is not None:
                html_content = html_bytes.decode("utf-8", errors="ignore")

        if html_content is None:
            # Note: ADR-0008 says we need to obey robots + ~1 req/s rate limit
            from leizilla.scraper import robots

            if not robots.is_allowed(self.url):
                logger.error(f"robots.txt blocked fetch for {self.url}")
                return []

            # Fetch using standard Python library directly, avoiding
            # "wayback.fetch_bytes" abstraction for live domains.
            import time

            time.sleep(1.0)  # rate limit
            try:
                req = urllib.request.Request(
                    self.url, headers={"User-Agent": "leizilla-crawler/0.1"}
                )
                with urllib.request.urlopen(req, timeout=30.0) as r:
                    html_content = r.read().decode("utf-8", errors="ignore")
            except Exception as e:
                logger.error(f"Falha ao buscar índice ao vivo {self.url}: {e}")

        if html_content is None:
            logger.error(f"Falha ao buscar índice {self.url}")
            return []

        # Find all hrefs to .pdf files
        pattern = re.compile(
            r"""href=['"]?([^'" >]+\.pdf)['"]?""",
            re.IGNORECASE,
        )
        matches = pattern.finditer(html_content)
        for match in matches:
            href = match.group(1)
            filename = href.split("/")[-1]
            tipo, chave = parse_filename(filename)

            if not tipo or not chave:
                tipo, chave = "", f"documento-{filename.rsplit('.', 1)[0]}"

            absolute_url = urllib.parse.urljoin(self.url, href)

            resources.append(
                {
                    "url": absolute_url,
                    "ente": self.ente,
                    "fonte": self.fonte,
                    "tipo_documento": tipo,
                    "chave": chave,
                    "status": "pending",
                    "wayback_snapshot": None,
                }
            )

        logger.info(
            f"CasacivilIndex Discovery concluído: {len(resources)} recursos encontrados"
        )
        return resources


class PlaywrightCrawlerDiscovery:
    """Estratégia de descobrimento que usa o LeisCrawler (Playwright) para o portal ALRO."""

    def __init__(self, config: Dict[str, Any], ente: str, fonte: str) -> None:
        self.start = int(config["start"])
        self.end = int(config["end"])
        self.ente = ente
        self.fonte = fonte

    def run(self, storage: Optional[DuckDBStorage] = None) -> List[Dict[str, Any]]:
        logger.info(
            f"Rodando Playwright Discovery para {self.ente}/{self.fonte} (de {self.start} a {self.end})..."
        )
        # Como o LeisCrawler é assíncrono, rodamos no event loop
        import asyncio

        from leizilla.crawler import LeisCrawler

        crawler = LeisCrawler(crawler_type="playwright")

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            # Caso especial em ambientes assíncronos
            import nest_asyncio

            nest_asyncio.apply()

        laws = loop.run_until_complete(
            crawler.discover_rondonia_laws(start_coddoc=self.start, end_coddoc=self.end)
        )

        resources = []
        for law in laws:
            pdf_url = law.get("url_pdf_original")
            # Captura por contexto (ADR-0011 §1): o título da página rende
            # (tipo, número) em >90% (parse_titulo_identity) → vai ao catálogo;
            # o resíduo (coddoc puro) é preservado na área de espera _unidentified.
            if pdf_url:
                resources.append(
                    {
                        "url": pdf_url,
                        "ente": self.ente,
                        "fonte": self.fonte,
                        # tipo/chave da identidade extraída do título (ADR-0011);
                        # fallback para coddoc quando não identificável (adiado).
                        "tipo_documento": law.get("tipo", "documento"),
                        "chave": law.get("chave", f"coddoc-{law.get('coddoc'):05d}"),
                        "status": "pending",
                        "wayback_snapshot": None,
                    }
                )
        return resources


class PlanaltoDiscovery:
    """Estratégia de descobrimento para o Portal da Legislação (Planalto, federal).

    Diferente de `SequentialDiscovery` (templates PDF fixos), o Planalto serve
    HTML year-scoped (`/_ato{range}/{ano}/{tipo}/{prefix}{num}.htm`) cujo ano
    de publicação não é derivável do número sozinho — delega a
    `fontes.federal.discover_planalto_laws` (lookup de ano via API da Câmara,
    cache + circuit breaker, fail-open para o padrão legado pré-2003).

    `head_check` (default True, diferente de `SequentialDiscovery`) importa
    mais aqui: numeração federal não tem a densidade quase-contígua da RO, e
    sem verificação um range grande (milhares) geraria majoritariamente 404s.
    Apesar do nome (mantido por compatibilidade com o manifesto), a verificação
    é feita via `_wayback_snapshot_if_exists` (API de disponibilidade do
    Internet Archive), não por HEAD direto ao domínio de origem — planalto.gov.br
    bloqueia/derruba requisições HTTP diretas de runners do GitHub Actions
    (confirmado issue #262, 348/348 candidatos com RemoteDisconnected/
    TimeoutError, nunca um 404 real), tornando o antigo `_head_exists`
    indistinguível de "nada existe" nesse ambiente.
    """

    def __init__(self, config: Dict[str, Any], ente: str, fonte: str) -> None:
        self.tipo = config["tipo"]
        self.start = int(config["start"])
        self.end = int(config["end"])
        self.ente = ente
        self.fonte = fonte
        self.head_check: bool = bool(config.get("head_check", True))

    def run(self, storage: Optional[DuckDBStorage] = None) -> List[Dict[str, Any]]:
        from leizilla.fontes.federal import discover_planalto_laws

        logger.info(
            f"Rodando Planalto Discovery para {self.ente}/{self.fonte} "
            f"tipo={self.tipo} (de {self.start} a {self.end}, "
            f"head_check={self.head_check})..."
        )
        import time

        candidates = discover_planalto_laws(self.tipo, self.start, self.end)

        resources = []
        last_check_time = 0.0
        for law in candidates:
            url = law["url_original"]

            if storage:
                try:
                    conn = storage.connect()
                    res = conn.execute(
                        "SELECT 1 FROM discovered_resources WHERE url = ?", [url]
                    ).fetchone()
                    if res:
                        continue
                except Exception as e:
                    logger.warning(f"Error checking DB for URL {url}: {e}")

            wayback_snapshot = None
            if self.head_check:
                elapsed = time.monotonic() - last_check_time
                if elapsed < _HEAD_RATE_LIMIT_S:
                    time.sleep(_HEAD_RATE_LIMIT_S - elapsed)
                wayback_snapshot = _wayback_snapshot_if_exists(url)
                last_check_time = time.monotonic()
                if wayback_snapshot is None:
                    logger.debug(f"Sem captura Wayback — skipping {url}")
                    continue

            resources.append(
                {
                    "url": url,
                    "ente": self.ente,
                    "fonte": self.fonte,
                    "tipo_documento": law["tipo"],
                    "chave": law["chave"],
                    "status": "pending",
                    "wayback_snapshot": wayback_snapshot,
                }
            )
        logger.info(
            f"Planalto Discovery concluído: {len(resources)} recursos encontrados "
            f"(head_check={self.head_check})"
        )
        return resources


STRATEGIES: Dict[
    str, Callable[[Dict[str, Any], str, str], DiscoveryStrategyProtocol]
] = {
    "wayback-cdx": WaybackCdxDiscovery,
    "sequential": SequentialDiscovery,
    "casacivil-index": CasacivilIndexDiscovery,
    "playwright-crawler": PlaywrightCrawlerDiscovery,
    "planalto": PlanaltoDiscovery,
}


def load_manifest(ente: str) -> Dict[str, Any]:
    """Carrega o arquivo de manifesto de um ente federativo."""
    manifest_path = Path(__file__).parent / "manifests" / f"{ente}.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifesto não encontrado para o ente: {ente}")
    with open(manifest_path, "r", encoding="utf-8") as f:
        data: Dict[str, Any] = json.load(f)
    return data


def _discovery_cfg_tipo(discovery_cfg: Dict[str, Any]) -> Optional[str]:
    """Deriva o `tipo_documento` alvo de um discovery_cfg, quando determinável.

    Segue o mesmo padrão já usado por `cmd_scrape`/`cmd_discover_probe` em
    cli.py: para estratégias "sequential", infere o tipo a partir do nome de
    arquivo de amostra do primeiro template (`parse_filename`); "planalto"
    já declara `tipo` explicitamente no manifesto. Estratégias que descobrem
    múltiplos tipos numa única chamada barata (casacivil-index, wayback-cdx)
    ou que não têm noção de tipo (playwright-crawler) retornam None — quem
    chama trata None como "sempre roda, não é filtrável por tipo".
    """
    strategy = discovery_cfg.get("strategy")
    if strategy == "planalto":
        tipo = discovery_cfg.get("tipo")
        return str(tipo) if tipo else None
    if strategy == "sequential":
        templates = discovery_cfg.get("templates") or []
        if not templates:
            return None
        sample_filename = templates[0].format(num=1).split("/")[-1]
        tipo, _ = parse_filename(sample_filename)
        return tipo
    return None


def discover_resources(
    ente: str,
    fonte: Optional[str] = None,
    storage: Optional[DuckDBStorage] = None,
    tipo: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Roda as estratégias do manifesto e **retorna** os resources (sem inserir).

    Diferente de ``run_discovery`` (que persiste), serve à reconciliação: re-deriva
    identidades com os extratores *atuais* (possivelmente melhorados), independente
    das linhas já gravadas em ``discovered_resources``. ``fonte`` filtra para uma
    fonte específica.

    ``tipo``, quando passado, pula estratégias "sequential"/"planalto" cujo
    tipo-alvo (derivado do template/manifesto, ver ``_discovery_cfg_tipo``) não
    bate — é o que permite escopar a descoberta por tipo (ex.: um job de CI
    dedicado a "decreto"), em vez de sempre varrer todos os tipos de uma fonte
    de uma vez (achado de produção 2026-09-25: um único job de descoberta não
    escopada para casacivil/head_check excedeu o timeout de 360min do job).
    Estratégias sem tipo determinável (índice HTML, CDX amplo, Playwright)
    sempre rodam, filtradas ou não — são baratas (uma chamada), o custo caro é
    o `head_check` sequencial por número, que este filtro de fato limita.

    ``storage``, quando passado, é repassado para cada estratégia (só
    ``SequentialDiscovery``/``PlanaltoDiscovery`` o usam hoje, para pular URLs
    já conhecidas sem refazer o HEAD request — ver ``run_discovery``). Deixe
    ``None`` para a re-derivação completa que a reconciliação precisa.
    """
    manifest = load_manifest(ente)
    out: List[Dict[str, Any]] = []
    for f, fonte_cfg in manifest.get("fontes", {}).items():
        if fonte is not None and f != fonte:
            continue
        for discovery_cfg in fonte_cfg.get("discovery", []):
            strategy_cls = STRATEGIES.get(discovery_cfg.get("strategy"))
            if not strategy_cls:
                logger.warning(
                    f"Estratégia '{discovery_cfg.get('strategy')}' não suportada."
                )
                continue
            if tipo is not None:
                cfg_tipo = _discovery_cfg_tipo(discovery_cfg)
                if cfg_tipo is not None and cfg_tipo != tipo:
                    continue
            try:
                out.extend(strategy_cls(discovery_cfg, ente, f).run(storage))
            except Exception as e:
                logger.error(
                    f"Falha na estratégia '{discovery_cfg.get('strategy')}' "
                    f"para {ente}/{f}: {e}"
                )
    return out


def run_discovery(
    ente: str,
    storage: DuckDBStorage,
    fonte: Optional[str] = None,
    tipo: Optional[str] = None,
) -> int:
    """Lê o manifesto do ente, executa as estratégias e salva os resources.

    ``fonte`` restringe a uma única fonte do manifesto (None = todas). Útil
    para isolar fontes lentas (ex.: PlaywrightCrawlerDiscovery de milhares de
    páginas) de fontes rápidas (ex.: wayback-cdx) sem esperar a mais lenta.
    ``tipo`` restringe ainda mais, dentro de uma fonte, às estratégias cujo
    tipo-alvo bate (ver ``discover_resources``).

    Passa ``storage`` para as estratégias (achado de produção 2026-09-25:
    antes disso, ``SequentialDiscovery``'s dedup-por-DB nunca era exercitado
    em produção — o parâmetro existia mas ninguém o repassava — então toda
    semana o `head_check` refazia HEAD request para TODOS os números já
    conhecidos desde `start=1`, não só os novos; para os 6/8 tipos de
    casacivil com `head_check: true` isso inflava o Discover step para
    horas e crescia a cada semana conforme o catálogo aumentava).
    """
    resources = discover_resources(ente, fonte=fonte, storage=storage, tipo=tipo)
    for res in resources:
        storage.insert_resource(res)
    return len(resources)
