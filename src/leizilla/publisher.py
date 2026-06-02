"""Publicação no Internet Archive e exportação de datasets."""

import atexit
import configparser
import csv
import hashlib
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set

from leizilla import config
from leizilla import storage as storage_module
from leizilla.ia_utils import (
    INDEX_COLUMNS,
    INDEX_FILENAME,
    compute_hash,
    download_url,
    list_identities,
    merge_index_row,
    parse_identity,
    range_bounds,
    range_item_identifier,
    raw_filename,
    remove_index_rows,
    unidentified_item_identifier,
    uuid5_collision,
    uuid5_name,
)

_DATASET_IDENTIFIER_RE = (
    r"^leizilla-dataset-(?P<ente>[a-z][a-z0-9-]*)-v(?P<version>\d+)$"
)

_USER_AGENT = "leizilla-crawler/0.1"

logger = logging.getLogger(__name__)


def _entity_coverage(ente: str) -> str:
    """Geographic coverage string for IA metadata, derived from ente slug."""
    try:
        from leizilla.entes import get_ente

        e = get_ente(ente)
        return "Brazil" if e.tipo == "federal" else f"{e.nome}, Brazil"
    except Exception:
        return "Brazil"


def _raw_identifier(ente: str, fonte: str, chave: str) -> str:
    """Constrói IA identifier para raw item conforme SCHEMA.md §1.2."""
    return f"leizilla-raw-{ente}-{fonte}-{chave}"


def _bundle_identifier(ente: str, fonte: str, dt: Optional[datetime] = None) -> str:
    """Constrói IA identifier para bundle semanal conforme SCHEMA.md §1.2."""
    d = dt or datetime.now(tz=timezone.utc)
    iso = d.isocalendar()
    return f"leizilla-bundle-{ente}-{fonte}-{iso[0]}-W{iso[1]:02d}"


def build_raw_meta(
    lei_data: Dict[str, Any],
    pdf_bytes: bytes,
    fetched_from: str,
    wayback_url: Optional[str] = None,
    wayback_blocked_robots: bool = False,
) -> Dict[str, Any]:
    """Constrói raw_meta.json conforme SCHEMA.md §2.1."""
    ente = str(lei_data.get("ente", "unknown"))
    fonte = str(lei_data.get("fonte", "casacivil"))
    chave = str(lei_data.get("chave") or lei_data.get("id", "unknown"))
    return {
        "leizilla_meta_version": "0.1",
        "ente": ente,
        "fonte": fonte,
        "chave": chave,
        "fonte_url": lei_data.get("url_original"),
        "data_captura": datetime.now(tz=timezone.utc).isoformat(),
        "hash_pdf": f"sha256:{hashlib.sha256(pdf_bytes).hexdigest()}",
        "user_agent": _USER_AGENT,
        "ia_id_bundle": _bundle_identifier(ente, fonte),
        "provenance_wayback": {
            "fetched_from": fetched_from,
            "wayback_url": wayback_url,
            "wayback_blocked_robots": wayback_blocked_robots,
        },
    }


def build_raw_meta_html(
    html_content: str,
    lei_data: Dict[str, Any],
    fetched_from: str,
    wayback_url: Optional[str] = None,
    wayback_blocked_robots: bool = False,
) -> Dict[str, Any]:
    """Constrói raw_meta.json para item HTML (fontes sem PDF, ex: Planalto)."""
    ente = str(lei_data.get("ente", "unknown"))
    fonte = str(lei_data.get("fonte", "planalto"))
    chave = str(lei_data.get("chave") or lei_data.get("id", "unknown"))
    html_bytes = html_content.encode("utf-8")
    return {
        "leizilla_meta_version": "0.1",
        "content_type": "html",
        "ente": ente,
        "fonte": fonte,
        "chave": chave,
        "fonte_url": lei_data.get("url_original"),
        "data_captura": datetime.now(tz=timezone.utc).isoformat(),
        "hash_html": f"sha256:{hashlib.sha256(html_bytes).hexdigest()}",
        "user_agent": _USER_AGENT,
        "ia_id_bundle": _bundle_identifier(ente, fonte),
        "provenance_wayback": {
            "fetched_from": fetched_from,
            "wayback_url": wayback_url,
            "wayback_blocked_robots": wayback_blocked_robots,
        },
    }


def _get_git_sha() -> Optional[str]:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            ).stdout.strip()
            or None
        )
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        return None


def build_dataset_meta(
    parquet_path: Path,
    ente: str,
    version: int,
    row_count: Optional[int] = None,
    git_sha: Optional[str] = None,
) -> Dict[str, Any]:
    """Constrói dataset_meta.json para IA dataset item (SCHEMA.md §3.3).

    KV footer no Parquet (PyArrow) é deferido para M5; por agora o metadata
    vai num sidecar JSON no mesmo IA item.
    """
    parquet_bytes = parquet_path.read_bytes()
    if row_count is None:
        import duckdb

        conn = duckdb.connect()
        try:
            row_count = (
                conn.execute(
                    "SELECT count(*) FROM read_parquet(?)", [str(parquet_path)]
                ).fetchone()
                or (0,)
            )[0]
        finally:
            conn.close()
    effective_git_sha = git_sha if git_sha is not None else _get_git_sha()
    meta: Dict[str, Any] = {
        "leizilla_meta_version": "0.1",
        "schema_version": "0.1",
        "ente": ente,
        "version": version,
        "table": "versoes",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "row_count": row_count,
        "file_size_bytes": parquet_path.stat().st_size,
        "hash_parquet": f"sha256:{hashlib.sha256(parquet_bytes).hexdigest()}",
    }
    if effective_git_sha:
        meta["git_sha"] = effective_git_sha
    return meta


_IA_SCRAPE_URL = "https://archive.org/services/search/v1/scrape"
_IA_DOWNLOAD_URL = "https://archive.org/download"


def count_ia_items(identifier_prefix: str) -> Optional[int]:
    """Count IA items whose identifier starts with prefix via scrape API.

    Returns None on network error (fail-open caller decides what to show).
    Paginates via cursor until exhausted.
    """
    q = f"identifier:{identifier_prefix}*"
    base_url = (
        f"{_IA_SCRAPE_URL}?q={urllib.parse.quote(q)}&count=10000&fields=identifier"
    )

    total = 0
    cursor: Optional[str] = None

    while True:
        url = base_url
        if cursor:
            url += f"&cursor={urllib.parse.quote(cursor)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            total += len(data.get("items", []))
            cursor = data.get("cursor")
            if not cursor:
                break
        except Exception:
            return None

    return total


def _scrape_identifiers(identifier_prefix: str) -> Optional[list[str]]:
    """Lista os identifiers de itens IA que começam com o prefixo (scrape API).

    ``None`` em erro de rede. Pagina via cursor até esgotar.
    """
    q = f"identifier:{identifier_prefix}*"
    base_url = (
        f"{_IA_SCRAPE_URL}?q={urllib.parse.quote(q)}&count=10000&fields=identifier"
    )
    ids: list[str] = []
    cursor: Optional[str] = None
    while True:
        url = base_url
        if cursor:
            url += f"&cursor={urllib.parse.quote(cursor)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            ids.extend(
                item["identifier"]
                for item in data.get("items", [])
                if item.get("identifier")
            )
            cursor = data.get("cursor")
            if not cursor:
                break
        except Exception:
            return None
    return ids


def list_raw_ids(ente: str, fonte: str) -> Set[str]:
    """Return set of legacy raw IDs already captured to IA for this ente/fonte.

    Under ADR-0011 the raw bytes live in identity range items
    (``leizilla_{ente}_{fonte}_{tipo}_{start}-{end}``), each carrying its own
    ``index.csv``. So we enumerate those items via the scrape API, read each
    index, and reconstruct the legacy raw IDs
    (``leizilla-raw-{ente}-{fonte}-{tipo}-{numero}``) the parser knows how to
    resolve.

    Fail-open: returns the empty set when nothing exists yet or on any network
    error, so the caller falls back to the sequential range — never skips due to
    connectivity.
    """
    prefix = f"leizilla_{ente.lower()}_{fonte.lower()}_"
    item_ids = _scrape_identifiers(prefix)
    if not item_ids:
        return set()
    out: Set[str] = set()
    for item_id in item_ids:
        index_url = download_url(item_id, INDEX_FILENAME)
        req = urllib.request.Request(index_url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                index_csv = resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError, ValueError):
            continue
        for identity in list_identities(index_csv):
            out.add(_raw_identifier(ente, fonte, identity))
    return out


def list_parsed_raw_ids(ente: str, fonte: str) -> Set[str]:
    """Return raw item IDs that have already been parsed and uploaded to IA.

    Queries IA for all parsed items of the ente (identifiers matching
    leizilla-{ente}-* excluding raw/bundle/dataset variants), then fetches
    each item's parsed_meta.json to extract ia_id_raw.  Only IDs from the
    given fonte are returned.

    Follows IA scrape API cursor for full pagination — never truncates at
    one page even for large collections (e.g. federal).
    Fail-open: returns empty set on any network error so parse-all never
    silently skips items due to connectivity issues.
    """
    q = (
        f"identifier:leizilla-{ente}-* "
        f"AND NOT identifier:leizilla-raw-{ente}-* "
        f"AND NOT identifier:leizilla-bundle-{ente}-* "
        f"AND NOT identifier:leizilla-dataset-{ente}-*"
    )
    base_url = (
        f"{_IA_SCRAPE_URL}?q={urllib.parse.quote(q)}&count=10000&fields=identifier"
    )

    parsed_ids: list[str] = []
    cursor: Optional[str] = None

    while True:
        url = base_url
        if cursor:
            url += f"&cursor={urllib.parse.quote(cursor)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            parsed_ids.extend(item["identifier"] for item in data.get("items", []))
            cursor = data.get("cursor")
            if not cursor:
                break
        except Exception:
            return set()

    raw_ids: Set[str] = set()
    prefix = f"leizilla-raw-{ente}-{fonte}-"

    for ia_id_parsed in parsed_ids:
        meta_url = f"{_IA_DOWNLOAD_URL}/{ia_id_parsed}/parsed_meta.json"
        try:
            req = urllib.request.Request(meta_url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:
                meta = json.loads(resp.read())
            raw_id = str(meta.get("ia_id_raw", ""))
            if raw_id.startswith(prefix):
                raw_ids.add(raw_id)
        except Exception:
            continue

    return raw_ids


def list_parsed_ia_ids(ente: str) -> list[str]:
    """Return all parsed IA item identifiers for this ente.

    Queries the IA scrape API for leizilla-{ente}-* items, excluding raw,
    bundle, and dataset variants. Returns the parsed item identifiers themselves
    (unlike list_parsed_raw_ids which returns the raw IDs they were derived from).

    Paginates via cursor. Fail-open: returns empty list on any network error.
    """
    q = (
        f"identifier:leizilla-{ente}-* "
        f"AND NOT identifier:leizilla-raw-{ente}-* "
        f"AND NOT identifier:leizilla-bundle-{ente}-* "
        f"AND NOT identifier:leizilla-dataset-{ente}-*"
    )
    base_url = (
        f"{_IA_SCRAPE_URL}?q={urllib.parse.quote(q)}&count=10000&fields=identifier"
    )

    ids: list[str] = []
    cursor: Optional[str] = None

    while True:
        url = base_url
        if cursor:
            url += f"&cursor={urllib.parse.quote(cursor)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            ids.extend(item["identifier"] for item in data.get("items", []))
            cursor = data.get("cursor")
            if not cursor:
                break
        except Exception:
            return []

    return ids


def fetch_parsed_xml(ia_id: str, output_path: Path) -> bool:
    """Download law.xml from an IA parsed item and save to output_path.

    URL: archive.org/download/{ia_id}/law.xml
    Returns True on success, False on any network or I/O error (fail-open).
    """
    url = f"{_IA_DOWNLOAD_URL}/{ia_id}/law.xml"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_bytes = resp.read()
        output_path.write_bytes(xml_bytes)
        return True
    except Exception:
        return False


class IndexFetchError(Exception):
    """Falha transitória ao buscar o index.csv (não é um 404 confirmado).

    Distingue "índice ausente" (404 → seguro começar vazio) de "não foi possível
    determinar" (timeout/5xx/rede). No segundo caso, sobrescrever o índice com uma
    versão de uma linha apagaria todo o histórico source_key → content_hash, então
    o chamador deve abortar em vez de começar do zero.
    """


def _fetch_existing_index(item_id: str) -> Optional[str]:
    """Baixa o index.csv corrente de um item de range do IA.

    Retorna o CSV se existir, ``None`` se for um 404 confirmado (item/índice ainda
    não publicado — seguro começar vazio), e levanta ``IndexFetchError`` em falhas
    transitórias (timeout, 5xx, rede) para que o chamador não sobrescreva o
    histórico existente com um índice vazio.
    """
    url = download_url(item_id, INDEX_FILENAME)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8", errors="replace")  # type: ignore[no-any-return]
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            # IA serve 403/404 para itens/arquivos inexistentes — índice ausente.
            return None
        raise IndexFetchError(f"HTTP {e.code} ao buscar index.csv") from e
    except (urllib.error.URLError, OSError) as e:
        # Timeout, DNS, conexão recusada — transitório, não confirma ausência.
        raise IndexFetchError(str(e)) from e


# formato (coluna do index) → sufixo de arquivo dentro do item.
_FORMATO_SUFFIX: Dict[str, str] = {"pdf": ".pdf", "html": ".html", "docx": ".docx"}


def _fetch_item_file_bytes(item_id: str, filename: str) -> bytes:
    """Baixa os bytes de um arquivo de dentro de um IA item (sem re-buscar a fonte).

    A reconciliação promove arquivos já preservados no item de espera usando os
    bytes do **IA**, nunca re-baixando do portal frágil (ADR-0004).
    """
    url = download_url(item_id, filename)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()  # type: ignore[no-any-return]


def _resolve_uuid5_and_index(
    item_id: str,
    content_bytes: bytes,
    *,
    tipo: str,
    numero: Optional[int],
    rendicao: str,
    formato: str,
    source: str = "",
) -> tuple[str, str]:
    """Resolve o nome de arquivo (UUIDv5) e o index.csv mesclado do item (ADR-0011).

    Busca o index.csv corrente do item, detecta colisão de UUIDv5 truncado (estende
    para o UUID completo se necessário), e mescla a captura (append-only,
    newest-wins). Levanta ``IndexFetchError`` em falha transitória de leitura — o
    chamador aborta em vez de sobrescrever o histórico do item.
    """
    sha256 = compute_hash(content_bytes)
    uuid5 = uuid5_name(content_bytes)
    existing = _fetch_existing_index(item_id)
    if existing and uuid5_collision(existing, uuid5=uuid5, sha256=sha256):
        uuid5 = uuid5_name(content_bytes, length=32)  # estende: garante unicidade
    merged = merge_index_row(
        existing,
        tipo=tipo,
        numero=numero,
        rendicao=rendicao,
        formato=formato,
        uuid5=uuid5,
        sha256=sha256,
        source=source,
    )
    return uuid5, merged


def _range_title(ente: str, fonte: str, tipo: str, numero: int) -> str:
    """Título legível do item de range (ex.: 'Leizilla Raw RO CASACIVIL LEI 5001-6000')."""
    start, end = range_bounds(numero)
    return (
        f"Leizilla Raw {ente.upper()} {fonte.upper()} "
        f"{tipo.upper()} {start:04d}-{end:04d}"
    )


def _unidentified_title(ente: str, fonte: str) -> str:
    """Título do item de espera (ex.: 'Leizilla Raw RO ASSEMBLEIA UNIDENTIFIED')."""
    return f"Leizilla Raw {ente.upper()} {fonte.upper()} UNIDENTIFIED"


_ia_config_cache: Dict[tuple[str, str], str] = {}


def _ia_subprocess_env(
    access_key: Optional[str], secret_key: Optional[str]
) -> Optional[Dict[str, str]]:
    """Devolve um env que autentica o CLI ``ia``, ou ``None`` se sem credenciais.

    O CLI ``ia`` ignora ``IA_ACCESS_KEY``/``IA_SECRET_KEY`` e não tem flags de
    chave: ele só lê credenciais de um arquivo de config, cujo caminho pode ser
    sobrescrito via a env var ``IA_CONFIG_FILE``. Escrevemos um ``ia.ini`` mínimo
    (uma vez por par de credenciais) e apontamos o subprocess para ele, para que
    o upload funcione sem um ``~/.config/internetarchive/ia.ini`` pré-existente.
    """
    if not access_key or not secret_key:
        return None
    key = (access_key, secret_key)
    cfg_path = _ia_config_cache.get(key)
    if cfg_path is None:
        cfg = configparser.ConfigParser()
        cfg["s3"] = {"access": access_key, "secret": secret_key}
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".ini", delete=False, encoding="utf-8"
        )
        cfg.write(tmp)
        tmp.close()
        cfg_path = tmp.name
        _ia_config_cache[key] = cfg_path
        _final_path = cfg_path

        def _cleanup() -> None:
            Path(_final_path).unlink(missing_ok=True)

        atexit.register(_cleanup)
    return {**os.environ, "IA_CONFIG_FILE": cfg_path}


class InternetArchivePublisher:
    """Upload para IA e geração de datasets Parquet."""

    def __init__(self) -> None:
        self.access_key = config.IA_ACCESS_KEY
        self.secret_key = config.IA_SECRET_KEY

    def upload_raw(
        self,
        pdf_path: Path,
        lei_data: Dict[str, Any],
        pdf_bytes: bytes,
        fetched_from: str = "source-fallback",
        wayback_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload raw PDF + raw_meta.json sidecar para IA.

        Identifier: leizilla-raw-{ente}-{fonte}-{chave} (SCHEMA.md §1.2).
        Retorna dict com 'success', 'ia_id', 'ia_url'.
        """
        if not self.access_key or not self.secret_key:
            return {"success": False, "error": "IA credentials not configured"}

        ente = str(lei_data.get("ente", "unknown"))
        fonte = str(lei_data.get("fonte", "casacivil"))
        chave = str(lei_data.get("chave") or lei_data.get("id", "unknown"))
        ia_id = _raw_identifier(ente, fonte, chave)

        # Identidade é evidência, não catraca (ADR-0011 §1): capturamos sempre. Se
        # o contexto rendeu (tipo, número), o item é o range navegável; senão, os
        # bytes ficam **preservados** na área de espera _unidentified (o IA faz OCR)
        # até a reconciliação — nunca há descarte.
        identity = parse_identity(chave)
        if identity is None:
            tipo, numero = "", None
            item_id = unidentified_item_identifier(ente, fonte)
            title = _unidentified_title(ente, fonte)
        else:
            tipo, numero = identity
            item_id = range_item_identifier(ente, fonte, tipo, numero)
            title = _range_title(ente, fonte, tipo, numero)
        rendicao = str(lei_data.get("rendicao", ""))
        # Proveniência (ADR-0010): mapeia o arquivo de volta à sua origem de
        # colheita (URL original; coddoc/path embutido). É como descartamos o
        # coddoc da identidade sem perder a rastreabilidade.
        # Proveniência == URL do recurso que a descoberta usa como chave
        # (`res["url"]`), para a reconciliação casar. Para a ALRO esse é o PDF
        # (`url_pdf_original`), não a página de listagem (`url_original`).
        source = str(
            lei_data.get("url_pdf_original") or lei_data.get("url_original") or ""
        )

        raw_meta = build_raw_meta(lei_data, pdf_bytes, fetched_from, wayback_url)

        # Nome content-addressed (UUIDv5) + index.csv do item. Aborta se não
        # conseguir ler o índice atual (não sobrescreve histórico do item).
        try:
            uuid5, index_csv = _resolve_uuid5_and_index(
                item_id,
                pdf_bytes,
                tipo=tipo,
                numero=numero,
                rendicao=rendicao,
                formato="pdf",
                source=source,
            )
        except IndexFetchError as e:
            return {
                "success": False,
                "error": f"could not read existing index (aborting to avoid data loss): {e}",
                "ia_id": ia_id,
            }

        with tempfile.TemporaryDirectory() as tmp:
            pdf_dst = Path(tmp) / raw_filename(uuid5, ".pdf")
            meta_path = Path(tmp) / raw_filename(uuid5, "_meta.json")
            index_path = Path(tmp) / INDEX_FILENAME

            shutil.copy2(str(pdf_path), str(pdf_dst))
            meta_path.write_text(json.dumps(raw_meta, indent=2, ensure_ascii=False))
            index_path.write_text(index_csv, encoding="utf-8")

            coverage = _entity_coverage(ente)
            desc = (
                f"Documento original (PDF) da legislação do ente federativo "
                f"{ente.upper()}, fonte {fonte}, chave {chave}, "
                f"identificador {ia_id}, capturado pelo projeto Leizilla."
            )
            try:
                subprocess.run(
                    [
                        "ia",
                        "upload",
                        item_id,
                        str(pdf_dst),
                        str(meta_path),
                        str(index_path),
                        "--metadata",
                        f"title:{title}",
                        "--metadata",
                        "mediatype:texts",
                        "--metadata",
                        f"subject:leis;leizilla;{ente};{fonte}",
                        "--metadata",
                        "creator:leizilla-crawler",
                        "--metadata",
                        "language:pt",
                        "--metadata",
                        f"coverage:{coverage}",
                        "--metadata",
                        f"description:{desc}",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    env=_ia_subprocess_env(self.access_key, self.secret_key),
                )
            except subprocess.CalledProcessError as e:
                return {"success": False, "error": e.stderr, "ia_id": ia_id}

        return {
            "success": True,
            "ia_id": ia_id,
            "ia_url": f"https://archive.org/details/{item_id}",
            "uuid5": uuid5,
            "item_id": item_id,
            "identified": identity is not None,
        }

    def upload_raw_html(
        self,
        html_content: str,
        lei_data: Dict[str, Any],
        fetched_from: str = "source-fallback",
        wayback_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload raw HTML + raw_meta.json sidecar para IA.

        Identifier: leizilla-raw-{ente}-{fonte}-{chave} (SCHEMA.md §1.2).
        Análogo a upload_raw mas para fontes que servem HTML (ex: Planalto).
        IA não faz OCR em HTML — Etapa 2 usa fetch_html direto da fonte_url.
        """
        if not self.access_key or not self.secret_key:
            return {"success": False, "error": "IA credentials not configured"}

        ente = str(lei_data.get("ente", "unknown"))
        fonte = str(lei_data.get("fonte", "planalto"))
        chave = str(lei_data.get("chave") or lei_data.get("id", "unknown"))
        ia_id = _raw_identifier(ente, fonte, chave)

        # Identidade é evidência, não catraca (ADR-0011 §1): identificados vão ao
        # range navegável; o resíduo fica preservado na área de espera _unidentified.
        identity = parse_identity(chave)
        if identity is None:
            tipo, numero = "", None
            item_id = unidentified_item_identifier(ente, fonte)
            title = _unidentified_title(ente, fonte)
        else:
            tipo, numero = identity
            item_id = range_item_identifier(ente, fonte, tipo, numero)
            title = _range_title(ente, fonte, tipo, numero)
        rendicao = str(lei_data.get("rendicao", ""))
        # Proveniência == URL do recurso que a descoberta usa como chave
        # (`res["url"]`), para a reconciliação casar. Para a ALRO esse é o PDF
        # (`url_pdf_original`), não a página de listagem (`url_original`).
        source = str(
            lei_data.get("url_pdf_original") or lei_data.get("url_original") or ""
        )

        html_bytes = html_content.encode("utf-8")
        raw_meta = build_raw_meta_html(
            html_content, lei_data, fetched_from, wayback_url
        )

        try:
            uuid5, index_csv = _resolve_uuid5_and_index(
                item_id,
                html_bytes,
                tipo=tipo,
                numero=numero,
                rendicao=rendicao,
                formato="html",
                source=source,
            )
        except IndexFetchError as e:
            return {
                "success": False,
                "error": f"could not read existing index (aborting to avoid data loss): {e}",
                "ia_id": ia_id,
            }

        with tempfile.TemporaryDirectory() as tmp:
            html_dst = Path(tmp) / raw_filename(uuid5, ".html")
            meta_path = Path(tmp) / raw_filename(uuid5, "_meta.json")
            index_path = Path(tmp) / INDEX_FILENAME

            html_dst.write_text(html_content, encoding="utf-8")
            meta_path.write_text(json.dumps(raw_meta, indent=2, ensure_ascii=False))
            index_path.write_text(index_csv, encoding="utf-8")

            coverage = _entity_coverage(ente)
            desc = (
                f"Documento original (HTML) da legislação do ente federativo "
                f"{ente.upper()}, fonte {fonte}, chave {chave}, "
                f"identificador {ia_id}, capturado pelo projeto Leizilla."
            )
            try:
                subprocess.run(
                    [
                        "ia",
                        "upload",
                        item_id,
                        str(html_dst),
                        str(meta_path),
                        str(index_path),
                        "--metadata",
                        f"title:{title}",
                        "--metadata",
                        "mediatype:texts",
                        "--metadata",
                        f"subject:leis;leizilla;{ente};{fonte}",
                        "--metadata",
                        "creator:leizilla-crawler",
                        "--metadata",
                        "language:pt",
                        "--metadata",
                        f"coverage:{coverage}",
                        "--metadata",
                        f"description:{desc}",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    env=_ia_subprocess_env(self.access_key, self.secret_key),
                )
            except FileNotFoundError:
                return {
                    "success": False,
                    "error": "ia CLI não encontrado — instale 'internetarchive'",
                    "ia_id": ia_id,
                }
            except subprocess.CalledProcessError as e:
                return {"success": False, "error": e.stderr, "ia_id": ia_id}

        return {
            "success": True,
            "ia_id": ia_id,
            "ia_url": f"https://archive.org/details/{item_id}",
            "uuid5": uuid5,
            "item_id": item_id,
            "identified": identity is not None,
        }

    def _promote_to_range(
        self,
        ente: str,
        fonte: str,
        tipo: str,
        numero: int,
        content: bytes,
        row: Dict[str, str],
    ) -> Optional[str]:
        """Sobe um arquivo preservado para o item de range com a identidade agora
        conhecida. Devolve o ``uuid5`` promovido, ou ``None`` em falha."""
        range_id = range_item_identifier(ente, fonte, tipo, numero)
        try:
            uuid5, index_csv = _resolve_uuid5_and_index(
                range_id,
                content,
                tipo=tipo,
                numero=numero,
                rendicao=row.get("rendicao", ""),
                formato=row.get("formato", "pdf"),
                source=row.get("source", ""),
            )
        except IndexFetchError as e:
            logger.warning("reconcile: índice do range ilegível (%s): %s", range_id, e)
            return None
        suffix = _FORMATO_SUFFIX.get(row.get("formato", "pdf"), ".pdf")
        with tempfile.TemporaryDirectory() as tmp:
            fdst = Path(tmp) / raw_filename(uuid5, suffix)
            fdst.write_bytes(content)
            index_path = Path(tmp) / INDEX_FILENAME
            index_path.write_text(index_csv, encoding="utf-8")
            try:
                subprocess.run(
                    [
                        "ia",
                        "upload",
                        range_id,
                        str(fdst),
                        str(index_path),
                        "--metadata",
                        f"title:{_range_title(ente, fonte, tipo, numero)}",
                        "--metadata",
                        "mediatype:texts",
                        "--metadata",
                        f"subject:leis;leizilla;{ente};{fonte}",
                        "--metadata",
                        "language:pt",
                        "--metadata",
                        f"coverage:{_entity_coverage(ente)}",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    env=_ia_subprocess_env(self.access_key, self.secret_key),
                )
            except subprocess.CalledProcessError as e:
                logger.warning(
                    "reconcile: upload ao range falhou (%s): %s", range_id, e
                )
                return None
        return uuid5

    def _upload_index_only(self, item_id: str, index_csv: str) -> bool:
        """Reescreve o index.csv de um item (usado para tirar do índice de espera o
        que foi promovido)."""
        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / INDEX_FILENAME
            index_path.write_text(index_csv, encoding="utf-8")
            try:
                subprocess.run(
                    [
                        "ia",
                        "upload",
                        item_id,
                        str(index_path),
                        "--metadata",
                        "mediatype:texts",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    env=_ia_subprocess_env(self.access_key, self.secret_key),
                )
            except subprocess.CalledProcessError as e:
                logger.warning("reconcile: reescrita do índice de espera falhou: %s", e)
                return False
        return True

    def reconcile_unidentified(
        self,
        ente: str,
        fonte: str,
        identity_by_source: Dict[str, tuple[str, int]],
    ) -> Dict[str, Any]:
        """Promove arquivos da área de espera ``_unidentified`` para o item de range
        cuja identidade ``(tipo, número)`` foi (re-)derivada do contexto da fonte.

        ``identity_by_source`` mapeia URL de origem → ``(tipo, número)`` — montado
        pela CLI a partir de uma passada de descoberta com os extratores atuais. Os
        bytes vêm do **IA** (item de espera), nunca do portal frágil (ADR-0004).
        """
        if not self.access_key or not self.secret_key:
            return {"success": False, "error": "IA credentials not configured"}
        holding_id = unidentified_item_identifier(ente, fonte)
        try:
            holding_index = _fetch_existing_index(holding_id)
        except IndexFetchError as e:
            return {
                "success": False,
                "error": f"could not read holding index: {e}",
                "item_id": holding_id,
            }
        if not holding_index:
            return {
                "success": True,
                "promoted": 0,
                "remaining": 0,
                "item_id": holding_id,
            }

        rows = [
            {c: r.get(c, "") or "" for c in INDEX_COLUMNS}
            for r in csv.DictReader(io.StringIO(holding_index))
        ]
        promoted_uuid5s: Set[str] = set()
        for row in rows:
            if row["numero"]:  # já identificado nesta área (não deveria ocorrer)
                continue
            ident = identity_by_source.get(row["source"])
            if ident is None:
                continue
            suffix = _FORMATO_SUFFIX.get(row["formato"], ".pdf")
            try:
                content = _fetch_item_file_bytes(
                    holding_id, raw_filename(row["uuid5"], suffix)
                )
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
                logger.warning("reconcile: download de %s falhou: %s", row["uuid5"], e)
                continue
            tipo, numero = ident
            promoted = self._promote_to_range(ente, fonte, tipo, numero, content, row)
            if promoted is not None:
                promoted_uuid5s.add(row["uuid5"])

        # As promoções ao range já aconteceram; só falta tirar essas linhas do
        # índice de espera. Se essa reescrita falhar, os arquivos seguem listados
        # na espera — reportamos erro (e contamos como remaining), senão o operador
        # acha que a limpeza terminou e a próxima reconciliação re-promove à toa.
        index_rewrite_ok = True
        if promoted_uuid5s:
            new_index = remove_index_rows(holding_index, promoted_uuid5s)
            index_rewrite_ok = self._upload_index_only(holding_id, new_index)

        cleaned = promoted_uuid5s if index_rewrite_ok else set()
        remaining = sum(
            1 for r in rows if not r["numero"] and r["uuid5"] not in cleaned
        )
        result: Dict[str, Any] = {
            "success": index_rewrite_ok,
            "promoted": len(promoted_uuid5s),
            "remaining": remaining,
            "item_id": holding_id,
        }
        if not index_rewrite_ok:
            result["error"] = (
                "arquivos promovidos ao range, mas a reescrita do índice de espera "
                "falhou — linhas promovidas ainda constam em _unidentified"
            )
        return result

    def upload_parsed(
        self,
        ia_id_parsed: str,
        xml_content: str,
        parsed_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Upload law.xml + parsed_meta.json para IA parsed item.

        Identifier: leizilla-{ente}-{tipo}-{numero:05d}-{ano} (SCHEMA.md §1.3).
        Retorna dict com 'success', 'ia_id', 'ia_url'.
        """
        if not self.access_key or not self.secret_key:
            return {"success": False, "error": "IA credentials not configured"}

        ente = str(parsed_meta.get("ente", "unknown"))
        tipo = str(parsed_meta.get("tipo", "lei"))
        titulo = f"Leizilla parsed {ia_id_parsed}"

        with tempfile.TemporaryDirectory() as tmp:
            xml_path = Path(tmp) / "law.xml"
            xml_path.write_text(xml_content, encoding="utf-8")
            meta_path = Path(tmp) / "parsed_meta.json"
            meta_path.write_text(
                json.dumps(parsed_meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            coverage = _entity_coverage(ente)
            desc = (
                f"Texto estruturado (Leizilla XML) da legislação do ente "
                f"{ente.upper()}, tipo {tipo}, identificador {ia_id_parsed}, "
                f"processado pelo projeto Leizilla."
            )
            try:
                subprocess.run(
                    [
                        "ia",
                        "upload",
                        ia_id_parsed,
                        str(xml_path),
                        str(meta_path),
                        "--metadata",
                        f"title:{titulo}",
                        "--metadata",
                        "mediatype:texts",
                        "--metadata",
                        f"subject:leis;leizilla;{ente};{tipo}",
                        "--metadata",
                        "creator:leizilla-parser",
                        "--metadata",
                        "language:pt",
                        "--metadata",
                        f"coverage:{coverage}",
                        "--metadata",
                        f"description:{desc}",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    env=_ia_subprocess_env(self.access_key, self.secret_key),
                )
                return {
                    "success": True,
                    "ia_id": ia_id_parsed,
                    "ia_url": f"https://archive.org/details/{ia_id_parsed}",
                }
            except subprocess.CalledProcessError as e:
                return {"success": False, "error": e.stderr, "ia_id": ia_id_parsed}

    def upload_dataset(
        self,
        parquet_path: Path,
        ente: str,
        version: int = 0,
        row_count: Optional[int] = None,
        git_sha: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload versoes.parquet + dataset_meta.json para IA.

        Identifier: leizilla-dataset-{ente}-v{version} (SCHEMA.md §1.4, §3.5).
        row_count e git_sha são opcionais — caller passa se já os computou.
        """
        if not self.access_key or not self.secret_key:
            return {"success": False, "error": "IA credentials not configured"}

        if version < 0:
            raise ValueError(
                f"version must be >= 0 to satisfy _DATASET_IDENTIFIER_RE, got {version}"
            )

        if not re.match(r"^[a-z][a-z0-9-]*$", ente):
            raise ValueError(
                f"ente must match [a-z][a-z0-9-]* to satisfy _DATASET_IDENTIFIER_RE, got {ente!r}"
            )

        ia_id = f"leizilla-dataset-{ente}-v{version}"
        dataset_meta = build_dataset_meta(
            parquet_path, ente, version, row_count, git_sha
        )
        effective_row_count = dataset_meta["row_count"]

        with tempfile.TemporaryDirectory() as tmp:
            parquet_dst = Path(tmp) / "versoes.parquet"
            shutil.copy2(str(parquet_path), str(parquet_dst))
            meta_path = Path(tmp) / "dataset_meta.json"
            meta_path.write_text(
                json.dumps(dataset_meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            coverage = _entity_coverage(ente)
            desc = (
                f"Dataset Parquet (tabela versoes) das leis do ente {ente.upper()}, "
                f"versão v{version}, gerado pelo projeto Leizilla. "
                f"Contém {effective_row_count} linhas."
            )
            try:
                subprocess.run(
                    [
                        "ia",
                        "upload",
                        ia_id,
                        str(parquet_dst),
                        str(meta_path),
                        "--metadata",
                        f"title:Leizilla Dataset {ente.upper()} v{version}",
                        "--metadata",
                        "mediatype:data",
                        "--metadata",
                        f"subject:leis;leizilla;{ente};parquet;versoes",
                        "--metadata",
                        "creator:leizilla-etl",
                        "--metadata",
                        "language:pt",
                        "--metadata",
                        f"coverage:{coverage}",
                        "--metadata",
                        f"description:{desc}",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    env=_ia_subprocess_env(self.access_key, self.secret_key),
                )
                return {
                    "success": True,
                    "ia_id": ia_id,
                    "ia_url": f"https://archive.org/details/{ia_id}",
                    "row_count": effective_row_count,
                }
            except FileNotFoundError:
                return {
                    "success": False,
                    "error": "ia CLI não encontrado — instale 'internetarchive'",
                    "ia_id": ia_id,
                }
            except subprocess.CalledProcessError as e:
                return {"success": False, "error": e.stderr, "ia_id": ia_id}

    def upload_to_archive(
        self,
        archive_ia_id: str,
        file_path: Path,
        filename_in_archive: str,
        ente: str,
        fonte: str,
    ) -> Dict[str, Any]:
        """Upload a single file to a consolidated archive item.

        Uses standard ia tool incremental upload.
        """
        if not self.access_key or not self.secret_key:
            return {"success": False, "error": "IA credentials not configured"}

        coverage = _entity_coverage(ente)
        title = f"Leizilla Archive {ente.upper()} {fonte.upper()}"
        desc = (
            f"Arquivo consolidado (múltiplos PDFs) contendo a legislação do ente "
            f"{ente.upper()}, fonte {fonte}, gerado pelo projeto Leizilla. "
            f"Permite o download do acervo completo de uma vez via Torrent."
        )

        with tempfile.TemporaryDirectory() as tmp:
            dst_path = Path(tmp) / filename_in_archive
            shutil.copy2(str(file_path), str(dst_path))

            try:
                subprocess.run(
                    [
                        "ia",
                        "upload",
                        archive_ia_id,
                        str(dst_path),
                        "--metadata",
                        f"title:{title}",
                        "--metadata",
                        "mediatype:texts",
                        "--metadata",
                        f"subject:leis;leizilla;{ente};{fonte};archive",
                        "--metadata",
                        "creator:leizilla-crawler",
                        "--metadata",
                        "language:pt",
                        "--metadata",
                        f"coverage:{coverage}",
                        "--metadata",
                        f"description:{desc}",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    env=_ia_subprocess_env(self.access_key, self.secret_key),
                )
                return {"success": True}
            except FileNotFoundError:
                return {
                    "success": False,
                    "error": "ia CLI não encontrado — instale 'internetarchive'",
                }
            except subprocess.CalledProcessError as e:
                return {"success": False, "error": e.stderr}

    def export_dataset_parquet(
        self,
        ente: str,
        output_dir: Path,
        ano: Optional[int] = None,
    ) -> Path:
        """Exporta dataset Parquet para o ente."""
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"leizilla-{ente}"
        if ano:
            filename += f"-{ano}"
        filename += ".parquet"
        output_path = output_dir / filename

        db = storage_module.DuckDBStorage()
        db.export_parquet(output_path, ente=ente, ano=ano)
        db.close()
        return output_path
