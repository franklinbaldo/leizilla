"""Internet Archive content-addressed raw layer (ADR-0010).

Raw files are addressed by the SHA-256 of their content; range items bucket by
hash prefix; a per-`(ente, fonte)` index maps the source's idiosyncratic harvest
key (``coddoc-05120``, a Planalto URL path, ...) to the current content hash.

The harvest key is **metadata** — it never appears in a path or a range
boundary. That keeps the catalog source-agnostic: the same code addresses bytes
from any fonte in Brazil, and dedup/immutability fall out of content-addressing.

Coordinate systems (ADR-0010):
  - raw   → content hash   (this module)
  - parsed → URN-LEX        (publisher.upload_parsed / ADR-0005)
The map between them is data (the index + parsed_meta), never a formula.
"""

import csv
import hashlib
import io
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from leizilla.entes import list_slugs

_USER_AGENT = "leizilla-crawler/0.1"

_RAW_PREFIX = "leizilla-raw-"
_HASH_BUCKET_LEN = 2  # hex chars → 256 range items per (ente, fonte)
_IA_DOWNLOAD = "https://archive.org/download"

INDEX_FILENAME = "index.csv"
INDEX_COLUMNS = [
    "source_key",  # harvest key da fonte (ex: coddoc-05120) — metadado, nunca path
    "content_hash",  # SHA-256 hex — endereço do arquivo raw
    "content_type",  # distingue componentes (application/pdf vs text/html)
    "source_url",  # URL original (Ditel/Planalto/Wayback)
    "captured_at",  # ISO-8601 — ordena versões (newest wins)
]


def compute_hash(data: bytes) -> str:
    """SHA-256 hex digest — o endereço de conteúdo de um arquivo raw."""
    return hashlib.sha256(data).hexdigest()


def parse_raw_id(ia_id: str) -> Optional[tuple[str, str, str]]:
    """Divide um raw_id legado em ``(ente, fonte, source_key)``.

    ``leizilla-raw-{ente}-{fonte}-{source_key}`` →
    ``('ro', 'casacivil', 'coddoc-05120')``.

    Usa o catálogo de entes (maior match primeiro) para que entes com hífen como
    ``ro-porto-velho`` sejam resolvidos deterministicamente. Retorna ``None`` se
    não casar com um ente conhecido ou se faltar fonte/source_key.
    """
    if not ia_id.startswith(_RAW_PREFIX):
        return None
    content = ia_id[len(_RAW_PREFIX) :]
    for slug in sorted(list_slugs(), key=len, reverse=True):
        if content.startswith(f"{slug}-"):
            rest = content[len(slug) + 1 :]
            if "-" not in rest:
                return None
            fonte, source_key = rest.split("-", 1)
            if not fonte or not source_key:
                return None
            return slug, fonte, source_key
    return None


def raw_index_identifier(ente: str, fonte: str) -> str:
    """IA item que guarda o índice ``source_key → content_hash`` de um (ente, fonte)."""
    return f"{_RAW_PREFIX}{ente.lower()}-{fonte.lower()}-index"


def raw_range_identifier(ente: str, fonte: str, hash_hex: str) -> str:
    """IA range item que armazena um arquivo raw, bucketizado por prefixo de hash.

    Ex: ``leizilla-raw-ro-casacivil-3f``. O bucket é derivado do hash (ADR-0010),
    nunca de uma chave de fonte — generaliza para qualquer fonte do Brasil.
    """
    bucket = hash_hex[:_HASH_BUCKET_LEN].lower()
    return f"{_RAW_PREFIX}{ente.lower()}-{fonte.lower()}-{bucket}"


def raw_filename(hash_hex: str, suffix: str) -> str:
    """Nome de arquivo content-addressed dentro do range item.

    Ex: ``raw_filename(h, '_djvu.txt')`` → ``'3f8a…d21c_djvu.txt'``. O OCR
    derivado pelo IA (``derive``) fica em ``{hash}_djvu.txt`` ao lado do PDF.
    """
    return f"{hash_hex.lower()}{suffix}"


def download_url(item_id: str, filename: str) -> str:
    """URL de download direto de um arquivo dentro de um IA item."""
    return f"{_IA_DOWNLOAD}/{item_id}/{filename}"


def merge_index_row(
    existing_csv: Optional[str],
    *,
    source_key: str,
    content_hash: str,
    content_type: str,
    source_url: str,
    captured_at: Optional[str] = None,
) -> str:
    """Devolve o índice CSV com uma linha de captura anexada (append-only).

    O índice é histórico: re-capturar o mesmo ``source_key`` com bytes diferentes
    adiciona uma nova linha; a linha mais recente de um source_key é a captura
    corrente. Idempotente em ``(source_key, content_hash)`` idênticos — não gera
    linha duplicada (re-crawl sem mudança de bytes é no-op).
    """
    captured_at = captured_at or datetime.now(tz=timezone.utc).isoformat()
    rows: list[dict[str, str]] = []
    if existing_csv:
        for row in csv.DictReader(io.StringIO(existing_csv)):
            rows.append({c: row.get(c, "") or "" for c in INDEX_COLUMNS})
    # Idempotência: remove linha prévia com mesmo key+hash e re-anexa como a mais nova.
    rows = [
        r
        for r in rows
        if not (r["source_key"] == source_key and r["content_hash"] == content_hash)
    ]
    rows.append(
        {
            "source_key": source_key,
            "content_hash": content_hash,
            "content_type": content_type,
            "source_url": source_url,
            "captured_at": captured_at,
        }
    )
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=INDEX_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def lookup_current_hash(index_csv: str, source_key: str) -> Optional[tuple[str, str]]:
    """Retorna ``(content_hash, content_type)`` da captura corrente (mais recente).

    A captura corrente é a última linha do source_key no índice append-only.
    Retorna ``None`` se o source_key não estiver no índice.
    """
    found: Optional[tuple[str, str]] = None
    for row in csv.DictReader(io.StringIO(index_csv)):
        if row.get("source_key") == source_key:
            found = (row.get("content_hash", ""), row.get("content_type", ""))
    return found


def _fetch_text(url: str, timeout: int = 30) -> Optional[str]:
    """GET de um arquivo texto do IA. ``None`` em qualquer falha de rede/404."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")  # type: ignore[no-any-return]
    except (urllib.error.URLError, OSError, ValueError):
        return None


def resolve_raw_url(ia_id: str, suffix: str, timeout: int = 30) -> Optional[str]:
    """Resolve um raw_id legado para a URL content-addressed do arquivo derivado.

    Passos (ADR-0010): parse do raw_id → fetch do índice do (ente, fonte) → lookup
    do hash corrente do source_key → monta a URL no range item por prefixo de hash.

    IDs que não casam com o padrão raw (itens externos/legados) caem no
    pass-through clássico ``{ia_id}/{ia_id}{suffix}``. Retorna ``None`` quando o
    índice não existe ainda ou o source_key não foi capturado — o chamador trata
    como "OCR ainda não disponível", preservando o contrato de fetch_ocr.
    """
    parsed = parse_raw_id(ia_id)
    if parsed is None:
        return download_url(ia_id, f"{ia_id}{suffix}")

    ente, fonte, source_key = parsed
    index_url = download_url(raw_index_identifier(ente, fonte), INDEX_FILENAME)
    index_csv = _fetch_text(index_url, timeout=timeout)
    if not index_csv:
        return None

    current = lookup_current_hash(index_csv, source_key)
    if current is None:
        return None

    content_hash, _content_type = current
    range_id = raw_range_identifier(ente, fonte, content_hash)
    return download_url(range_id, raw_filename(content_hash, suffix))
