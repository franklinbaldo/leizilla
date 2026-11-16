"""Pipeline de scraping: robots → fetch → upload ao IA (ADR-0004, ADR-0008, ADR-0016).

``scrape_one``/``scrape_one_html`` (scrape por range, fontes HTML) seguem o ADR-0004:
Wayback como caminho primário, fallback direto se o Wayback falhar.

``harvest_pending_resources`` (a colheita da fila, usada no backfill) segue o
ADR-0016: fetch direto da fonte no limite por host do ADR-0008, Save Page Now pedido
em segundo plano sem bloquear, e upload em lotes por item do IA com um único derive.

Princípio #10: robots.txt é permanente (sem retry em URL bloqueada); rate-limit
               por host (não global) em toda batida direta na fonte.
"""

import logging
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from leizilla import config, robots, wayback
from leizilla.discovery import load_manifest
from leizilla.ia_utils import parse_identity, range_bounds, range_item_identifier
from leizilla.parser import fetch_html
from leizilla.publisher import (
    InternetArchivePublisher,
    RawCapture,
    make_raw_capture,
    preserved_identity_token,
)
from leizilla.ratelimit import make_rate_limiter
from leizilla.storage import DuckDBStorage

logger = logging.getLogger(__name__)


def scrape_one(
    fonte_url: str,
    pdf_url: str,
    lei_data: Dict[str, Any],
    publisher: InternetArchivePublisher,
    rate_limiter: Optional[Callable[[str], None]] = None,
    index_cache: Optional[Dict[str, str]] = None,
    wayback_snapshot: Optional[str] = None,
) -> Dict[str, Any]:
    """Scrape um PDF: robots check → wayback save → fetch → upload_raw.

    Retorna dict com 'success' + ('ia_id', 'ia_url') ou ('reason') em falha.
    Robots bloqueado é permanente — caller NÃO deve re-tentar a mesma URL.
    rate_limiter recebe a URL do fallback para tracking por host.
    ``index_cache`` (acumulador por item do lote) repassa-se ao ``upload_raw``
    para evitar lost-update do index.csv entre uploads ao mesmo item de range.
    ``wayback_snapshot`` é um snapshot pré-descoberto (ex.: CDX) usado preferencialmente
    — preserva capturas http-keyed que ``check_available`` (scheme-sensitive) perderia
    na URL normalizada https; o timestamp da captura serve de chave de versão (ADR-0004).
    """
    if not robots.is_allowed(fonte_url):
        return {"success": False, "reason": "robots-blocked", "url": fonte_url}
    if not robots.is_allowed(pdf_url):
        return {"success": False, "reason": "robots-blocked", "url": pdf_url}

    # Wayback save do índice/fonte — fire-and-forget; exceções swallowadas para que
    # falhas de rede não abortem fetch+upload. A captura do PDF em si é feita por
    # ensure_archived abaixo (que lê o snapshot da resposta do save).
    try:
        wayback.save_page(fonte_url)
    except Exception:
        pass

    # Resolução do snapshot com proveniência: um snapshot pré-descoberto (CDX) tem
    # prioridade; senão ensure_archived (SPN-first, dual-scheme, lê a resposta do save —
    # não a re-consulta imediata que o SPN assíncrono não satisfaz). Vale também para o
    # caminho sequencial/não-arquivado da CLI, não só para itens já no CDX.
    wb_url: Optional[str]
    if wayback_snapshot:
        wb_url = wayback_snapshot
    else:
        snap = wayback.ensure_archived(pdf_url)
        wb_url = snap[0] if snap is not None else None
    fetched_from: str
    pdf_bytes: Optional[bytes]

    if wb_url:
        pdf_bytes = wayback.fetch_bytes(wb_url)
        fetched_from = "wayback"
        # Wayback pode retornar HTML de erro para snapshots de redirect — fallback direto.
        if pdf_bytes is not None and pdf_bytes[:4] != b"%PDF":
            pdf_bytes = None
    else:
        pdf_bytes = None
        wb_url = None

    if pdf_bytes is None:
        # Fallback direto com rate-limit por host (princípio #10)
        if rate_limiter is not None:
            rate_limiter(pdf_url)
        pdf_bytes = wayback.fetch_bytes(pdf_url)
        fetched_from = "source-fallback"
        wb_url = None

    if pdf_bytes is None:
        return {"success": False, "reason": "fetch-failed", "url": pdf_url}

    if pdf_bytes[:4] != b"%PDF":
        print(
            f"[WARN] not a valid PDF for {lei_data.get('chave')} ({pdf_url}): header={pdf_bytes[:32]!r}",
            file=sys.stderr,
        )
        return {"success": False, "reason": "not-pdf", "url": pdf_url}

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_bytes)
        tmp_path = Path(f.name)

    try:
        return publisher.upload_raw(
            tmp_path,
            lei_data,
            pdf_bytes,
            fetched_from=fetched_from,
            wayback_url=wb_url,
            index_cache=index_cache,
        )
    except Exception as exc:
        return {"success": False, "reason": "upload-failed", "error": str(exc)}
    finally:
        tmp_path.unlink(missing_ok=True)


def scrape_one_html(
    fonte_url: str,
    lei_data: dict,
    publisher: InternetArchivePublisher,
    rate_limiter: Optional[Callable[[str], None]] = None,
    index_cache: Optional[Dict[str, str]] = None,
    wayback_snapshot: Optional[str] = None,
) -> dict:
    """Scrape de uma página HTML: robots → wayback save → fetch → upload_raw_html.

    Para fontes sem PDF (ex: Planalto federal) que servem HTML compilado vigente.
    Retorna dict com 'success' + ('ia_id', 'ia_url') ou ('reason') em falha.
    Robots bloqueado é permanente — caller NÃO deve re-tentar a mesma URL.
    ``index_cache`` (acumulador por item do lote) repassa-se ao ``upload_raw_html``.
    ``wayback_snapshot`` é um snapshot pré-descoberto (ex.: PlanaltoDiscovery via
    ``closest_snapshot``, sem limite de idade) usado preferencialmente — sem ele,
    esta função caía em ``check_available`` (exige captura < 24h), quase sempre
    ``None`` para páginas arquivadas há mais tempo, forçando um fallback direto
    a hosts que bloqueiam requisições de runners do GitHub Actions (issue #262).
    """
    if not robots.is_allowed(fonte_url):
        return {"success": False, "reason": "robots-blocked", "url": fonte_url}

    try:
        wayback.save_page(fonte_url)
    except Exception:
        pass

    # Snapshot pré-descoberto (qualquer idade) tem prioridade; senão, tenta um
    # snapshot recente via check_available (exige < 24h).
    wb_url = wayback_snapshot or wayback.check_available(fonte_url)
    wayback_attempted = wb_url is not None
    fetched_from: str
    html_content: Optional[str]

    if wb_url:
        html_content = fetch_html(wb_url)
        fetched_from = "wayback"
    else:
        html_content = None
        wb_url = None

    if html_content is None:
        # Fallback direto com rate-limit por host (princípio #10)
        if rate_limiter is not None:
            rate_limiter(fonte_url)
        html_content = fetch_html(fonte_url)
        fetched_from = "source-fallback"
        wb_url = None

    if html_content is None:
        # Diagnóstico (issue #262): distingue "sem snapshot Wayback disponível"
        # de "snapshot existia mas fetch_html falhou" — ambos acabam em
        # fetch-failed, mas só o log revela qual ramo foi de fato tentado.
        # Issue #297: um run real de CI produziu Falhas=10 sem NENHUMA destas
        # linhas aparecer no job log, apesar de basicConfig estar configurado
        # (confirmado) e a chamada logger.warning estar presente no commit
        # executado (confirmado) — não reproduzido localmente. print(...,
        # file=sys.stderr) já é o padrão comprovado nesta base para o caminho
        # PDF (scrape_one, harvest_pending_resources) e aparece de forma
        # confiável nesses mesmos runs de CI; duplicar aqui como
        # belt-and-suspenders em vez de confiar só no logging.
        msg = (
            f"[WARN] scrape_one_html: fetch-failed para {fonte_url} "
            f"(wayback_attempted={wayback_attempted})"
        )
        print(msg, file=sys.stderr)
        logger.warning(
            "scrape_one_html: fetch-failed para %s (wayback_attempted=%s)",
            fonte_url,
            wayback_attempted,
        )
        return {"success": False, "reason": "fetch-failed", "url": fonte_url}

    try:
        return publisher.upload_raw_html(
            html_content,
            lei_data,
            fetched_from=fetched_from,
            wayback_url=wb_url,
            index_cache=index_cache,
        )
    except Exception as exc:
        print(
            f"[WARN] scrape_one_html: upload-failed para {fonte_url}: {exc}",
            file=sys.stderr,
        )
        logger.warning("scrape_one_html: upload-failed para %s: %s", fonte_url, exc)
        return {"success": False, "reason": "upload-failed", "error": str(exc)}


def _resolve_tipo_ingestion(
    ente: str, fonte: str, manifest_cache: Dict[str, Dict[str, Any]]
) -> str:
    """Lê `tipo_ingestion` do manifesto de `ente`/`fonte` (default "pdf").

    Issue #248: `discovered_resources` não carrega `tipo_ingestion` (é metadado
    do manifesto, não do recurso descoberto), então `harvest_pending_resources`
    precisa reconsultar o manifesto por linha. `manifest_cache` evita reler o
    JSON do disco a cada recurso do mesmo ente dentro do mesmo batch.
    Fail-open: manifesto ausente/malformado ou fonte não declarada nele
    preserva o comportamento pré-existente (caminho PDF).
    """
    if ente not in manifest_cache:
        try:
            manifest_cache[ente] = load_manifest(ente)
        except (FileNotFoundError, ValueError):
            manifest_cache[ente] = {}
    fontes_cfg = manifest_cache[ente].get("fontes", {})
    fonte_cfg = fontes_cfg.get(fonte, {})
    tipo_ingestion = fonte_cfg.get("tipo_ingestion", "pdf")
    return str(tipo_ingestion)


# make_rate_limiter moved to leizilla.ratelimit (re-imported above) so
# publisher.py can reuse it for IA upload pacing without an import cycle
# (this module already imports InternetArchivePublisher from publisher.py).


_CANONICAL_GUESS = re.compile(r"[A-Za-z]+\d+\.pdf")


def _schemeless(url: str) -> str:
    """URL sem esquema: http://… e https://… são a mesma origem de colheita."""
    return url.split("://", 1)[-1]


def _already_preserved(
    publisher: InternetArchivePublisher,
    ente: str,
    fonte: str,
    chave: str,
    url: str,
    cache: Dict[str, Optional[set[str]]],
) -> bool:
    """True se esta URL de origem já tem captura no item de range do IA.

    O ``index.csv`` do item é a memória durável do que já foi capturado
    (ADR-0010); o DuckDB local é efêmero em CI. Índice ilegível agora conta como
    "não sei": o recurso segue o caminho normal (o próprio ``upload_raw`` aborta
    se o índice continuar ilegível), nunca é presumido preservado.
    """
    identity = parse_identity(chave)
    if identity is None:
        return False
    item_id = range_item_identifier(ente, fonte, identity[0], identity[1])
    if item_id not in cache:
        cache[item_id] = publisher.preserved_sources(item_id)
    sources = cache[item_id]
    if sources is None:
        return False
    if _schemeless(url).lower() in sources:
        return True
    # A mesma norma aparece sob grafias diferentes do nome canônico ("L6.pdf",
    # "L006.pdf", "/cotel/" vs "/COTEL/"). Se a identidade já tem captura e esta
    # URL é só mais uma grafia canônica, não é documento novo — sem isto a
    # colheita gastava o limite inteiro em 404 de nomes adivinhados. Um arquivo
    # com sufixo ("L6324 - COMPILADA.pdf") é outra rendição e não entra aqui.
    filename = url.rsplit("/", 1)[-1]
    return bool(_CANONICAL_GUESS.fullmatch(filename)) and (
        preserved_identity_token(identity[0], identity[1]) in sources
    )


def _iter_pending(
    storage: DuckDBStorage, limit: int, ente: Optional[str], tipo: Optional[str]
) -> Iterator[Dict[str, Any]]:
    """Itera a fila de pendentes em páginas, sem repetir URL dentro da execução.

    Recursos pulados por já estarem preservados deixam de ser 'pending', então a
    página seguinte traz os próximos; uma falha transitória continua 'pending' e
    é filtrada aqui para não ser reprocessada no mesmo lote.

    Uma captura à espera do flush do seu lote também continua 'pending' — e, por
    nunca ter sido tentada, no topo da ordenação. A página cresce com o que já foi
    visto para que essas linhas não ocupem a página inteira e encerrem a iteração
    antes da hora.
    """
    seen: set[str] = set()
    while True:
        page = [
            res
            for res in storage.get_pending_resources(
                limit=limit + len(seen), ente=ente, tipo=tipo
            )
            if res["url"] not in seen
        ]
        if not page:
            return
        for res in page:
            seen.add(res["url"])
            yield res


# Disjuntores da colheita (ADR-0016): parar cedo é a forma de recuar.
# Falhas transitórias seguidas no fetch direto = a fonte caiu ou está nos barrando;
# continuar seria martelar um portal frágil só para colecionar timeouts.
_MAX_CONSECUTIVE_TRANSIENT_FETCH = 10
# Flushes seguidos falhando por motivo não classificado: o problema é do lote/IA,
# não de um PDF — baixar mais da fonte só para perder no upload é desperdício dela.
_MAX_CONSECUTIVE_FLUSH_FAILURES = 2
# Motivos de flush que encerram a colheita na hora (repetir agora não ajuda).
_FATAL_FLUSH_REASONS = frozenset({"ia-throttled", "ia-unavailable"})
# Sequência de 404/410 confirmados, sem nenhuma captura na execução: a fila traz
# chutes obsoletos (ex.: números além do último existente). Cada 404 já vira
# terminal, então a próxima execução segue adiante — isto só limita o desperdício
# do limite a N por execução.
_MAX_CONSECUTIVE_ABSENT = 50
_ABSENT_STREAK_REASON = "sequência de documentos inexistentes"


def ia_throttle_scope(message: Optional[str]) -> str:
    """Classifica uma recusa por taxa do IA: ``"item"`` ou ``"account"``.

    ``bucket_tasks_queued exceeds rationed amount`` é a ração **por item**: só
    aquele item está com a fila cheia. ``total_tasks_queued`` é o limite da conta
    inteira. Mensagem sem nenhum dos dois marcadores (ou com os dois) é tratada
    como da conta — o caso conservador, que encerra a colheita.
    """
    text = message or ""
    if "total_tasks_queued" in text:
        return "account"
    if "bucket_tasks_queued" in text:
        return "item"
    return "account"


# Save Page Now em segundo plano: no máximo 1 pedido a cada 5 s (12/min), fila
# limitada, e até 30 s de espera ao fim para os pedidos em voo.
_WAYBACK_SAVE_INTERVAL_S = 5.0
_WAYBACK_SAVE_MAX_PENDING = 200
_WAYBACK_SAVE_GRACE_S = 30.0


@dataclass
class _Staged:
    """Uma captura no buffer do seu item, com o que o ledger precisa após o flush."""

    capture: RawCapture
    url: str
    chave: str
    ente: str
    tipo: str
    wayback_snapshot: Optional[str]


class _RawBatcher:
    """Acumula capturas por item do IA e as sobe em lotes (ADR-0016).

    O status no DuckDB só muda **depois** do flush que contém o arquivo: sucesso
    → ``downloaded``; PDF recusado pelo IA → ``ia-rejected`` (terminal); qualquer
    outra falha → ``pending`` (nova tentativa numa próxima execução).
    """

    def __init__(
        self,
        storage: DuckDBStorage,
        publisher: InternetArchivePublisher,
        stats: Dict[str, Any],
        batch_size: int,
    ) -> None:
        self.storage = storage
        self.publisher = publisher
        self.stats = stats
        self.batch_size = max(1, batch_size)
        # Índice acumulado por item nesta execução: flushes sucessivos ao mesmo
        # item partem do índice do flush anterior em vez de reler do IA (sem
        # read-after-write) e sobrescrever as linhas recém-gravadas.
        self.index_cache: Dict[str, str] = {}
        self.buffers: Dict[str, List[_Staged]] = {}
        self.derive_items: List[str] = []
        self.consecutive_failures = 0
        self.abort_reason: Optional[str] = None
        # Itens cuja fila no IA está cheia (ração por item): nada mais sobe a eles
        # nesta execução e o derive deles fica para depois.
        self.throttled_items: set[str] = set()
        # Itens de range que esta execução tocou (subiu, pulou por já preservado,
        # ou falha permanente) → (ente, fonte, tipo, número), para checar se ainda
        # há pendências antes de pedir o derive.
        self.item_meta: Dict[str, tuple[str, str, str, int]] = {}

    def register_item(self, item_id: str, key: tuple[str, str, str, int]) -> None:
        self.item_meta.setdefault(item_id, key)

    def add(self, staged: _Staged) -> None:
        item_id = staged.capture.target.item_id
        buffer = self.buffers.setdefault(item_id, [])
        buffer.append(staged)
        if len(buffer) >= self.batch_size:
            self.flush(item_id)

    def flush(self, item_id: str) -> None:
        staged = self.buffers.pop(item_id, [])
        if not staged:
            return
        results: List[Dict[str, Any]]
        try:
            results = self.publisher.upload_raw_batch(
                item_id, [s.capture for s in staged], index_cache=self.index_cache
            )
        except Exception as exc:
            print(f"[ERROR] flush de {item_id} levantou: {exc}", file=sys.stderr)
            results = []
        if not isinstance(results, list) or len(results) != len(staged):
            results = [
                {"success": False, "reason": "upload-failed", "error": "exception"}
            ] * len(staged)
        self.stats["flushes"] += 1

        batch_failure: Optional[str] = None
        throttle_error = ""
        any_success = False
        for entry, result in zip(staged, results):
            if result.get("success"):
                any_success = True
                self._record_success(entry, result)
                continue
            reason = str(result.get("reason") or "upload-failed")
            if reason == "ia-rejected":
                self._record_rejected(entry, str(result.get("rejection") or ""))
                continue
            batch_failure = reason
            if reason == "ia-throttled":
                throttle_error = str(result.get("error", ""))
            self._record_failure(entry, reason, str(result.get("error", "?")))

        if any_success and item_id not in self.derive_items:
            self.derive_items.append(item_id)
        if batch_failure is None:
            self.consecutive_failures = 0
            return
        if (
            batch_failure == "ia-throttled"
            and ia_throttle_scope(throttle_error) == "item"
        ):
            # Ração por item: só este item recua; os demais seguem. Não conta como
            # flush falho seguido (o problema não é do lote nem da conta).
            self.throttled_items.add(item_id)
            return
        self.consecutive_failures += 1
        if batch_failure in _FATAL_FLUSH_REASONS:
            self.abort_reason = batch_failure
        elif self.consecutive_failures >= _MAX_CONSECUTIVE_FLUSH_FAILURES:
            self.abort_reason = "ia-upload-failing"

    def _record_success(self, entry: _Staged, result: Dict[str, Any]) -> None:
        self.storage.update_resource_status(
            entry.url, "downloaded", wayback_snapshot=entry.wayback_snapshot
        )
        lei_data = entry.capture.lei_data
        chave = entry.chave
        self.storage.insert_lei(
            {
                "id": lei_data["id"],
                "titulo": lei_data["titulo"],
                "numero": chave.split("-")[-1] if "-" in chave else chave,
                "ente": entry.ente,
                "tipo_lei": entry.tipo,
                "url_original": entry.url,
                "url_pdf_ia": result.get("ia_url"),
            }
        )
        self.stats["success"] += 1
        self.stats["items"].append(
            {
                "status": "ok",
                "chave": chave,
                "ia_id": result.get("ia_id"),
                "ia_url": result.get("ia_url"),
            }
        )

    def _record_rejected(self, entry: _Staged, rejection: str = "") -> None:
        # Terminal e distinto de 'failed': o IA recusou o conteúdo deste PDF
        # ("error checking pdf file" ou "pdf file looks like spam");
        # get_pending_resources() não o re-seleciona. URL e motivo ficam no banco
        # (coluna ``motivo``) para uma estratégia especial futura (ADR-0011); nada
        # é apagado do IA. Não conta para _MAX_CONSECUTIVE_FLUSH_FAILURES.
        kind = rejection or "pdf-check"
        reason = f"ia-rejected: {kind}"
        print(
            f"[WARN] IA recusou o PDF de {entry.chave} ({entry.url}): "
            f"{kind} — marcado ia-rejected",
            file=sys.stderr,
        )
        self.storage.update_resource_status(entry.url, "ia-rejected", motivo=kind)
        self.stats["ia-rejected"] += 1
        if kind == "spam":
            self.stats["ia-rejected-spam"] += 1
        self.stats["items"].append(
            {"status": "ia-rejected", "chave": entry.chave, "reason": reason}
        )

    def _record_failure(self, entry: _Staged, reason: str, error: str) -> None:
        print(
            f"[WARN] upload failed for {entry.chave} [{reason}]: {error[-300:]}",
            file=sys.stderr,
        )
        # 'pending', nunca 'downloaded' nem 'failed': os bytes não estão no
        # índice do IA, e o motivo (limite de taxa, índice ilegível, rede) passa.
        self.storage.update_resource_status(entry.url, "pending")
        self.stats["failed"] += 1
        self.stats["items"].append(
            {"status": "failed", "chave": entry.chave, "reason": reason}
        )

    def finish(self) -> None:
        """Sobe o que restou nos buffers e pede um derive por item tocado."""
        for item_id in list(self.buffers):
            if self.abort_reason is None:
                self.flush(item_id)
                continue
            # Colheita abortada (ex.: IA limitando a taxa): não insiste. O que
            # ficou no buffer volta para a fila como falha transitória.
            for entry in self.buffers.pop(item_id):
                self._record_failure(entry, self.abort_reason, "colheita abortada")
        self._request_derives()

    def _pending_in_item(self, item_id: str) -> Optional[int]:
        """Pendências na fila que mapeiam para este item, ou ``None`` se incalculável."""
        key = self.item_meta.get(item_id)
        if key is None:
            return None
        ente, fonte, tipo, numero = key
        start, end = range_bounds(numero)
        return self.storage.count_pending_in_range(
            ente, fonte, tipo, 0 if start == 1 else start, end
        )

    def _request_derives(self) -> None:
        """Um derive por item **terminado** (ADR-0016, regra do dia 2).

        Um derive pedido enquanto o item ainda recebe uploads fica na fila do IA
        e os uploads seguintes se empilham atrás dele. Por isso só se pede o
        derive quando nenhum recurso da fila mapeia mais para o item. Também
        entram itens que esta execução tocou sem subir nada (pulados por já
        preservados, 404 confirmado) e que ficaram sem pendências.
        """
        uploaded = list(self.derive_items)
        touched_only = [i for i in self.item_meta if i not in uploaded]
        for item_id in [*uploaded, *touched_only]:
            received_files = item_id in uploaded
            if item_id in self.throttled_items:
                self.stats["derive-postponed"].append(item_id)
                continue
            pending = self._pending_in_item(item_id)
            if pending:
                if received_files:
                    self.stats["derive-postponed"].append(item_id)
                continue
            if not config.HARVEST_DERIVE:
                if received_files:
                    self.stats["derive-failed"].append(item_id)
                continue
            try:
                accepted = bool(self.publisher.request_derive(item_id))
            except Exception as exc:
                print(f"[ERROR] derive de {item_id} levantou: {exc}", file=sys.stderr)
                accepted = False
            if accepted:
                self.stats["derive-requested"] += 1
            else:
                print(
                    f"[WARN] derive NÃO aceito para {item_id} — os PDFs estão no "
                    f"item, mas sem OCR até um derive: ia tasks {item_id} "
                    "--cmd derive.php",
                    file=sys.stderr,
                )
                self.stats["derive-failed"].append(item_id)


def harvest_pending_resources(
    storage: DuckDBStorage,
    publisher: InternetArchivePublisher,
    limit: int = 100,
    ente: Optional[str] = None,
    tipo: Optional[str] = None,
    batch_size: Optional[int] = None,
    wayback_saver: Optional[wayback.BackgroundSaver] = None,
) -> Dict[str, Any]:
    """Processa recursos pendentes da tabela discovered_resources (ADR-0016).

    Para cada recurso PDF: robots → fetch (do snapshot Wayback que a descoberta já
    conhecia, senão direto da fonte no limite por host) → buffer do item do IA.
    Cada buffer sobe em lotes de ``batch_size`` capturas (default
    ``config.HARVEST_BATCH_SIZE``) num único ``ia upload`` sem derive; ao fim, um
    derive por item tocado. O status de um recurso só muda depois do flush que o
    contém. Save Page Now é pedido em segundo plano (``wayback_saver``; criado
    aqui se ``config.HARVEST_WAYBACK_SAVE``) e nunca segura a captura.

    Se `ente` for fornecido, processa apenas recursos desse ente.
    Se `tipo` for fornecido, processa apenas recursos desse tipo de documento.
    """
    stats: Dict[str, Any] = {
        "success": 0,
        "failed": 0,
        "robots-blocked": 0,
        "already-preserved": 0,
        "ia-rejected": 0,
        "ia-rejected-spam": 0,
        "flushes": 0,
        "derive-requested": 0,
        "derive-failed": [],
        "derive-postponed": [],
        "deferred": 0,
        "deferred-items": [],
        "aborted": None,
        "wayback-save": None,
        "items": [],
    }
    # ``limit`` conta tentativas reais (rede/upload). Recurso que o index.csv do
    # IA mostra já preservado é só marcado e não consome o limite — senão um
    # banco local recém-criado gastaria a execução inteira revendo o que já existe.
    attempts = 0
    preserved_cache: Dict[str, Optional[set[str]]] = {}
    rate_limiter = make_rate_limiter(config.HARVEST_HOST_INTERVAL_S)
    # Índice acumulado por item de range neste lote (caminho HTML, upload unitário);
    # o caminho PDF usa o cache do batcher, com a mesma finalidade.
    index_cache: Dict[str, str] = {}
    manifest_cache: Dict[str, Dict[str, Any]] = {}
    batcher = _RawBatcher(
        storage,
        publisher,
        stats,
        batch_size if batch_size is not None else config.HARVEST_BATCH_SIZE,
    )
    if wayback_saver is None and config.HARVEST_WAYBACK_SAVE:
        wayback_saver = wayback.BackgroundSaver(
            config.IA_ACCESS_KEY,
            config.IA_SECRET_KEY,
            min_interval=_WAYBACK_SAVE_INTERVAL_S,
            max_pending=_WAYBACK_SAVE_MAX_PENDING,
            # O robô do Wayback bate na fonte a cada pedido: os pedidos consomem
            # o MESMO orçamento por host do fetch direto (ADR-0008).
            source_limiter=rate_limiter,
        )
    consecutive_transient = 0
    consecutive_absent = 0
    fetched_any = False
    deadline = (
        time.monotonic() + config.HARVEST_MAX_SECONDS
        if config.HARVEST_MAX_SECONDS > 0
        else None
    )

    try:
        for res in _iter_pending(storage, limit, ente, tipo):
            if batcher.abort_reason is not None:
                break
            if deadline is not None and time.monotonic() >= deadline:
                # Orçamento de tempo esgotado: para de baixar e encerra direito
                # (flush + derive) em vez de ser morta pelo teto do job.
                stats["aborted"] = "time-budget"
                break
            url = res["url"]
            ente = res["ente"]
            fonte = res["fonte"]
            tipo = res["tipo_documento"]
            chave = res["chave"]
            wb_url = res["wayback_snapshot"]

            identity = parse_identity(chave)
            item_id = (
                range_item_identifier(ente, fonte, identity[0], identity[1])
                if identity
                else None
            )
            item_key = (ente, fonte, identity[0], identity[1]) if identity else None

            if _already_preserved(publisher, ente, fonte, chave, url, preserved_cache):
                storage.update_resource_status(url, "downloaded")
                stats["already-preserved"] += 1
                if item_id and item_key:
                    batcher.register_item(item_id, item_key)
                continue
            if item_id is not None and item_id in batcher.throttled_items:
                # Fila cheia no IA para este item: nem baixamos da fonte um
                # arquivo que não conseguimos subir agora. Continua 'pending'.
                stats["deferred"] += 1
                if item_id not in stats["deferred-items"]:
                    stats["deferred-items"].append(item_id)
                continue
            if attempts >= limit:
                break
            attempts += 1

            # Fontes HTML (ex.: federal/planalto) não têm bytes %PDF para validar —
            # despacham para scrape_one_html em vez do caminho PDF abaixo (#248).
            if _resolve_tipo_ingestion(ente, fonte, manifest_cache) == "html":
                lei_data_html = {
                    "id": f"{ente}-{fonte}-{chave}",
                    "ente": ente,
                    "fonte": fonte,
                    "chave": chave,
                    "titulo": f"{tipo.upper()} {chave} ({ente.upper()})",
                    "url_original": url,
                }
                html_result = scrape_one_html(
                    url,
                    lei_data_html,
                    publisher,
                    rate_limiter=rate_limiter,
                    index_cache=index_cache,
                    wayback_snapshot=wb_url,
                )
                # Issue #297: scrape_one_html's OWN internal prints/logs (PR #290/#300)
                # produced zero output in a live CI run for 10/10 failures, even after
                # duplicating logger.warning through an unconditional stderr print —
                # ruling out both "no handler configured" and "no print call present".
                # This call-site dump is the issue's own next suggested step: it sits
                # in the exact same loop position as the PDF path's prints (line 382
                # below), which ARE proven to show up reliably in these same CI runs —
                # if this line is also silent, the HTML branch itself isn't being
                # reached the way the code above assumes.
                print(
                    f"[DEBUG] html_result for {chave} ({url}): {html_result!r}",
                    file=sys.stderr,
                )
                if not html_result.get("success"):
                    reason = html_result.get("reason", "fetch-failed")
                    if reason == "robots-blocked":
                        # Permanente (princípio #10): nunca re-selecionado por
                        # get_pending_resources() já que seu status deixa de ser
                        # 'pending'.
                        storage.update_resource_status(url, "robots-blocked")
                        stats["robots-blocked"] += 1
                        item_status = "robots-blocked"
                    else:
                        # scrape_one_html não distingue falha permanente de
                        # transiente (diferente de fetch_bytes_detailed no caminho
                        # PDF) — fica 'pending' para ser re-tentado (#121).
                        storage.update_resource_status(url, "pending")
                        stats["failed"] += 1
                        item_status = "failed"
                    stats["items"].append(
                        {"status": item_status, "chave": chave, "reason": reason}
                    )
                    continue

                storage.update_resource_status(url, "downloaded")
                storage.insert_lei(
                    {
                        "id": lei_data_html["id"],
                        "titulo": lei_data_html["titulo"],
                        "numero": chave.split("-")[-1] if "-" in chave else chave,
                        "ente": ente,
                        "tipo_lei": tipo,
                        "url_original": url,
                        "url_pdf_ia": html_result.get("ia_url"),
                    }
                )
                stats["success"] += 1
                stats["items"].append(
                    {
                        "status": "ok",
                        "chave": chave,
                        "ia_id": html_result.get("ia_id"),
                        "ia_url": html_result.get("ia_url"),
                    }
                )
                continue

            # Robots check
            if not robots.is_allowed(url):
                storage.update_resource_status(url, "robots-blocked")
                stats["robots-blocked"] += 1
                stats["items"].append(
                    {
                        "status": "robots-blocked",
                        "chave": chave,
                        "reason": "robots-blocked",
                    }
                )
                continue

            # Fetch (ADR-0016). Um snapshot Wayback que a descoberta já conhecia
            # continua sendo a origem preferida — poupa a fonte e o seu timestamp é
            # a chave de versão (ADR-0004). Sem snapshot conhecido NÃO esperamos o
            # Save Page Now: baixamos direto, no limite por host, e pedimos o
            # arquivamento em segundo plano.
            wb_ts: Optional[str] = (
                wayback.snapshot_timestamp(wb_url) if wb_url else None
            )
            pdf_bytes: Optional[bytes] = None
            fetched_from = "source-direct"
            # Só uma falha CONFIRMADA (404/410 no fetch direto) é permanente;
            # qualquer outra (429/5xx esgotado, timeout, erro de rede) é transitória
            # e não deve virar 'failed' terminal — get_pending_resources() só
            # re-seleciona status='pending' (#121).
            permanent_failure = False

            if wb_url:
                pdf_bytes = wayback.fetch_bytes(wb_url)
                fetched_from = "wayback"
                # Wayback pode retornar uma página HTML de erro para snapshots que
                # capturaram um redirect/erro (status 200 no CDX mas conteúdo HTML).
                # Trata como fetch falho para acionar o fetch direto.
                if pdf_bytes is not None and pdf_bytes[:4] != b"%PDF":
                    pdf_bytes = None

            if pdf_bytes is None:
                # "source-fallback" = havia snapshot e ele falhou; "source-direct"
                # = nenhum snapshot era conhecido. Nos dois casos a proveniência
                # NÃO cita snapshot: os bytes não vieram de um.
                fetched_from = "source-fallback" if wb_url else "source-direct"
                wb_url = None
                wb_ts = None
                # Rate-limit por host; retry/backoff em 429/5xx já acontece dentro
                # de fetch_bytes_detailed.
                rate_limiter(url)
                pdf_bytes, permanent_failure = wayback.fetch_bytes_detailed(url)

            if pdf_bytes is None:
                print(
                    f"[WARN] fetch returned None for {chave} ({url})", file=sys.stderr
                )
                storage.update_resource_status(
                    url, "failed" if permanent_failure else "pending"
                )
                stats["failed"] += 1
                stats["items"].append(
                    {
                        "status": "failed",
                        "chave": chave,
                        "reason": "fetch-failed"
                        if permanent_failure
                        else "fetch-failed-transient",
                    }
                )
                if permanent_failure:
                    consecutive_transient = 0  # a fonte respondeu: está de pé
                    if item_id and item_key:
                        batcher.register_item(item_id, item_key)
                    consecutive_absent += 1
                    if (
                        not fetched_any
                        and consecutive_absent >= _MAX_CONSECUTIVE_ABSENT
                    ):
                        stats["aborted"] = _ABSENT_STREAK_REASON
                        break
                    continue
                consecutive_transient += 1
                if consecutive_transient >= _MAX_CONSECUTIVE_TRANSIENT_FETCH:
                    stats["aborted"] = "source-unavailable"
                    break
                continue
            consecutive_transient = 0
            consecutive_absent = 0
            fetched_any = True

            # Validate PDF magic bytes — source may serve HTML error pages with .pdf URLs
            if pdf_bytes[:4] != b"%PDF":
                print(
                    f"[WARN] not a valid PDF for {chave} ({url}): "
                    f"header={pdf_bytes[:32]!r}",
                    file=sys.stderr,
                )
                storage.update_resource_status(url, "not-pdf")
                stats["failed"] += 1
                stats["items"].append(
                    {"status": "failed", "chave": chave, "reason": "not-pdf"}
                )
                continue

            if wb_url is None and wayback_saver is not None:
                # Best-effort e sem bloquear: a testemunha independente do Wayback
                # é pedida, não esperada. Nada é registrado na proveniência — o
                # snapshot ainda não existe.
                wayback_saver.submit(url)

            lei_data = {
                "id": f"{ente}-{fonte}-{chave}",
                "ente": ente,
                "fonte": fonte,
                "chave": chave,
                "titulo": f"{tipo.upper()} {chave} ({ente.upper()})",
                "url_original": url,  # proveniência: mapeia o arquivo → fonte (ADR-0010)
                # chave de versão de proveniência (ADR-0004): o instante da captura
                # Wayback de onde os bytes vieram — None quando vieram da fonte.
                "wayback_timestamp": wb_ts,
            }
            if item_id and item_key:
                batcher.register_item(item_id, item_key)
            batcher.add(
                _Staged(
                    capture=make_raw_capture(
                        lei_data, pdf_bytes, fetched_from, wayback_url=wb_url
                    ),
                    url=url,
                    chave=chave,
                    ente=ente,
                    tipo=tipo,
                    wayback_snapshot=wb_url,
                )
            )
    finally:
        # Mesmo se o laço levantar: o que já foi baixado da fonte sobe, e os itens
        # tocados recebem o seu derive — os uploads foram feitos com --no-derive.
        batcher.finish()
        if batcher.abort_reason is not None:
            stats["aborted"] = batcher.abort_reason
        if wayback_saver is not None:
            stats["wayback-save"] = wayback_saver.close(grace=_WAYBACK_SAVE_GRACE_S)
            for saved_url, snapshot in wayback_saver.snapshots.items():
                storage.set_wayback_snapshot(saved_url, snapshot)

    return stats
