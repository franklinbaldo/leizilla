"""Internet Archive raw layer — identity-keyed items, content-addressed files (ADR-0011).

A camada raw é endereçada pela **identidade da norma** ``(ente, fonte, tipo,
número)``: o item IA é um *range bucket* por identidade
(``leizilla_{ente}_{fonte}_{tipo}_{start}-{end}``), e cada arquivo dentro do item
é nomeado por um hash determinístico do conteúdo (UUIDv5 truncado). Um
``index.csv`` por item mapeia ``(tipo, número, rendição, formato)`` → arquivo,
newest-wins.

Identidade é evidência, não catraca (ADR-0011 §1): uma chave de colheita sem
``(tipo, número)`` normativo (ex.: ``coddoc`` puro) não produz identidade — o
recurso não vai ao catálogo navegável, mas é **preservado** na área de espera
``leizilla_{ente}_{fonte}_unidentified`` (o IA faz OCR) até a reconciliação, nunca
descartado. A identidade jurídica pan-Brasil continua na camada *parsed* (URN-LEX,
ADR-0005/0010).
"""

import csv
import hashlib
import io
import json
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from urllib.parse import urlencode

from leizilla.entes import list_slugs

_USER_AGENT = "leizilla-crawler/0.1"
_RAW_PREFIX = "leizilla-raw-"  # forma legada do raw_id (chave no DuckDB/CLI)
_IA_DOWNLOAD = "https://archive.org/download"

_RANGE_SIZE = 1000
_UUID5_LEN = (
    8  # colisão só importa dentro de um item (~1000 leis); sha256 no index detecta
)

# Tipos que NÃO identificam uma norma: são chaves de colheita idiossincráticas da
# fonte (ADR-0011). Uma chave com esses tipos não entra no catálogo navegável —
# é preservada na área de espera _unidentified até a reconciliação.
_NON_IDENTIFYING_TIPOS = {"coddoc", "documento", "fallback", "seq"}

# OCR (_djvu.txt) é derivado pelo IA a partir do PDF; resolvê-lo usa o arquivo PDF.
_SUFFIX_TO_FORMATO: dict[str, str] = {
    "_djvu.txt": "pdf",
    ".pdf": "pdf",
    ".html": "html",
    ".docx": "docx",
}

INDEX_FILENAME = "index.csv"
INDEX_COLUMNS = [
    "tipo",  # tipo normativo (lei, lc, decreto, ...)
    "numero",  # número da norma na fonte
    "rendicao",  # original | compilada | atual | "" (unclassified)
    "formato",  # pdf | html | docx
    "uuid5",  # nome content-addressed do arquivo (UUIDv5 truncado)
    "sha256",  # hash completo — dedup + detecção de colisão de uuid5
    "captured_at",  # ISO-8601 — ordena versões (newest wins)
    "source",  # chave de colheita / URL de origem (ADR-0010): mapeia arquivo→fonte
    # Proveniência da captura (ADR-0016, adendo 2026-11-17). Substitui o sidecar
    # ``_meta.json`` por captura na colheita em lote: uma linha do índice carrega o que
    # o sidecar tinha e o índice ainda não. Linhas antigas leem vazio ("desconhecido").
    "fetched_from",  # wayback | source-fallback | source-direct | refile | ...
    "wayback_url",  # snapshot de onde vieram os bytes (só se fetched_from=wayback)
    "wayback_timestamp",  # instante imutável desse snapshot (14 dígitos)
    "wayback_blocked_robots",  # "true" | "false" | "" (desconhecido)
    "user_agent",  # User-Agent do crawler que baixou os bytes
]
# Colunas de proveniência: as que vêm do sidecar, não da identidade.
PROVENANCE_COLUMNS = INDEX_COLUMNS[8:]

# --- Limitação de taxa do IA, classificada em um só lugar ----------------------------
# O IA recusa uploads com "Please reduce your request rate. - {escopo}_tasks_queued
# exceeds ..." quando há tarefas demais na fila. O ESCOPO da ração vem na mensagem:
#   bucket_tasks_queued     ração do ITEM (só aquele item está cheio)
#   accesskey_tasks_queued  ração da CHAVE de acesso (a conta inteira; 2026-11-17)
#   total_tasks_queued      limite GLOBAL da fila (``exceeds global_limit``)
# Qualquer outro ``{palavra}_tasks_queued`` ainda não visto é tratado como da conta, o
# lado conservador (a colheita recua em vez de insistir).
_IA_TASKS_QUEUED_RE = re.compile(r"\b([a-z0-9_]+?)_tasks_queued\b", re.IGNORECASE)
_IA_RATE_TEXT_RE = re.compile(r"reduce your request rate|slow ?down", re.IGNORECASE)


def classify_ia_throttle(text: Optional[str]) -> Optional[str]:
    """Escopo de uma recusa por taxa do IA: ``"item"``, ``"account"`` ou ``None``.

    ``None`` = o texto não é uma limitação de taxa. ``"item"`` só quando **todo**
    marcador ``*_tasks_queued`` da mensagem é ``bucket``; qualquer outro (``total``,
    ``accesskey`` ou um desconhecido) ou um aviso de taxa sem marcador algum é
    ``"account"``.
    """
    body = text or ""
    scopes = {m.group(1).lower() for m in _IA_TASKS_QUEUED_RE.finditer(body)}
    if scopes:
        return "item" if scopes == {"bucket"} else "account"
    if _IA_RATE_TEXT_RE.search(body):
        return "account"
    return None


def is_ia_queue_full(text: Optional[str]) -> bool:
    """True se o texto traz um marcador ``*_tasks_queued`` (fila de tarefas cheia).

    É a limitação que só passa em minutos ou mais, a que a espera paciente
    (``IaQueueWait``) e o recuo imediato da colheita tratam; um ``reduce your request
    rate`` sem marcador é limite de taxa comum e mantém os recuos curtos.
    """
    return _IA_TASKS_QUEUED_RE.search(text or "") is not None


# --- Sonda de capacidade do IA (somente leitura) ---------------------------------------
# ``GET https://s3.us.archive.org/?check_limit=1&accesskey=<chave>&bucket=<item>`` é o
# mesmo ponto que a biblioteca ``internetarchive`` consulta (``ArchiveSession.
# s3_is_overloaded``) quando um upload falha. Não grava nada e não usa a chave secreta.
# Resposta medida em 2026-11-18 (sem credencial, item real):
#   {"accesskey": "...", "bucket": "...", "over_limit": 0, "detail": {
#      "accesskey_ration": 499, "accesskey_tasks_queued": 0, "bucket_limit": 999,
#      "bucket_ration": 149, "bucket_tasks_queued": 150, "limit_reason": "",
#      "rationing_engaged": 0, "rationing_level": 9999,
#      "total_global_limit": 11999, "total_tasks_queued": 9770}}
# ``over_limit`` é o veredito (a biblioteca também só o usa): ``bucket_tasks_queued``
# (150) pode passar de ``bucket_ration`` (149) com ``over_limit`` 0.
IA_S3_CHECK_LIMIT_URL = "https://s3.us.archive.org/"
IA_CAPACITY_TIMEOUT_S = 12.0


@dataclass(frozen=True)
class IaCapacity:
    """Resposta da sonda: o IA aceita uploads agora? ``scope`` só quando recusa."""

    over_limit: bool
    scope: Optional[str] = None  # "account" | "item" (só se over_limit)
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_ia_capacity(payload: Any) -> Optional[IaCapacity]:
    """Interpreta o JSON de ``check_limit``; ``None`` se não for o formato conhecido.

    Escopo, quando ``over_limit`` != 0: primeiro ``detail.limit_reason`` pela mesma
    ``classify_ia_throttle`` da recusa de upload; senão, qual contador passou da
    ração (conta/global antes de item); senão ``"account"`` (lado conservador).
    """
    if not isinstance(payload, dict) or "over_limit" not in payload:
        return None
    over = payload.get("over_limit")
    if isinstance(over, bool):
        is_over = over
    else:
        n = _num(over)
        if n is None:
            return None
        is_over = n != 0
    raw_detail = payload.get("detail")
    detail: dict[str, Any] = raw_detail if isinstance(raw_detail, dict) else {}
    if not is_over:
        return IaCapacity(False, None, "", detail)
    reason = str(detail.get("limit_reason") or "")
    scope = classify_ia_throttle(reason)
    if scope is None:

        def exceeded(queued: str, limit: str) -> bool:
            q, lim = _num(detail.get(queued)), _num(detail.get(limit))
            return q is not None and lim is not None and q >= lim

        if exceeded("accesskey_tasks_queued", "accesskey_ration") or exceeded(
            "total_tasks_queued", "total_global_limit"
        ):
            scope = "account"
        elif exceeded("bucket_tasks_queued", "bucket_ration"):
            scope = "item"
        else:
            scope = "account"
    return IaCapacity(True, scope, reason, detail)


def probe_ia_capacity(
    access_key: Optional[str],
    bucket: Optional[str] = None,
    timeout: float = IA_CAPACITY_TIMEOUT_S,
) -> Optional[IaCapacity]:
    """Pergunta ao IA se a conta (e o item, se dado) aceita uploads agora.

    Fail-open: sem chave, erro de rede/HTTP, JSON inválido ou formato desconhecido
    devolvem ``None`` (= "não sei", e a colheita segue como antes da sonda).
    """
    if not access_key:
        return None
    params = {"check_limit": "1", "accesskey": access_key}
    if bucket:
        params["bucket"] = bucket
    url = f"{IA_S3_CHECK_LIMIT_URL}?{urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError):  # URLError/HTTPError/timeout são OSError
        return None
    return parse_ia_capacity(payload)


def compute_hash(data: bytes) -> str:
    """SHA-256 hex digest — discriminador de conteúdo (dedup + detecção de colisão)."""
    return hashlib.sha256(data).hexdigest()


def uuid5_name(data: bytes, length: int = _UUID5_LEN) -> str:
    """Nome de arquivo content-addressed: UUIDv5(SHA-256) truncado.

    Determinístico nos bytes; bytes idênticos → mesmo nome (dedup por construção).
    """
    sha = compute_hash(data)
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, sha))[:length]


def parse_identity(chave: str) -> Optional[tuple[str, int]]:
    """Extrai ``(tipo, número)`` de uma chave de colheita, ou ``None``.

    ``'lei-05120' → ('lei', 5120)``. Retorna ``None`` se a chave não casar com
    ``{tipo}-{número}`` ou se o tipo for não-identificante (``coddoc`` etc.) —
    nesse caso o recurso é preservado na área de espera, não promovido ao catálogo.
    """
    m = re.match(r"^([a-z][a-z0-9-]*)-(\d+)$", chave.strip().lower())
    if not m:
        return None
    tipo, numero = m.group(1), int(m.group(2))
    # Rejeita se o PRIMEIRO segmento for não-identificante (ex.: "coddoc",
    # "documento-oficio-123"). O grupo de tipo no regex é guloso e engloba hífens,
    # então sem checar o primeiro segmento um stem de fallback com forma
    # "{palavra}-{dígitos}" (ex.: "documento-oficio-123") escaparia da área de
    # espera para um range navegável sob um tipo espúrio.
    if tipo.split("-", 1)[0] in _NON_IDENTIFYING_TIPOS:
        return None
    return tipo, numero


def range_bounds(num: int, size: int = _RANGE_SIZE) -> tuple[int, int]:
    """Limites do range de ``num`` (ex.: 5120 → (5001, 6000))."""
    if num <= 0:
        return 1, size
    start = ((num - 1) // size) * size + 1
    return start, start + size - 1


def range_item_identifier(ente: str, fonte: str, tipo: str, num: int) -> str:
    """Item IA (range bucket) por identidade: ``leizilla_{ente}_{fonte}_{tipo}_{start}-{end}``.

    Ex.: ``leizilla_ro_casacivil_lei_5001-6000``. Namespaced por ``(ente, fonte,
    tipo)`` — a numeração é da fonte; a identidade nacional vive no parsed.
    """
    start, end = range_bounds(num)
    return (
        f"leizilla_{ente.lower()}_{fonte.lower()}_{tipo.lower()}_{start:04d}-{end:04d}"
    )


def raw_filename(uuid5: str, suffix: str, name_prefix: Optional[str] = None) -> str:
    """Nome do arquivo dentro do item: ``{name_prefix}_{uuid5}{suffix}``."""
    if name_prefix:
        clean_prefix = re.sub(r"[^a-zA-Z0-9_-]", "", name_prefix).lower()
        return f"{clean_prefix}_{uuid5}{suffix}"
    return f"{uuid5}{suffix}"


def unidentified_item_identifier(ente: str, fonte: str) -> str:
    """Item IA de espera para recursos sem ``(tipo, número)`` resolvido (ADR-0011 §1).

    ``leizilla_{ente}_{fonte}_unidentified``. Rede de segurança (exceção, não rota
    normal): bytes capturados por contexto mas ainda sem número são **preservados**
    aqui — o IA faz OCR — até a reconciliação extrair a identidade e promovê-los ao
    item de range. Nunca há descarte.
    """
    return f"leizilla_{ente.lower()}_{fonte.lower()}_unidentified"


def download_url(item_id: str, filename: str) -> str:
    """URL de download direto de um arquivo dentro de um IA item."""
    return f"{_IA_DOWNLOAD}/{item_id}/{filename}"


def parse_raw_id(ia_id: str) -> Optional[tuple[str, str, str]]:
    """Divide um raw_id legado em ``(ente, fonte, chave)``.

    ``leizilla-raw-{ente}-{fonte}-{chave}`` → ``('ro', 'casacivil', 'lei-05120')``.
    Usa o catálogo de entes (maior match primeiro) para resolver entes com hífen
    (``ro-porto-velho``). Retorna ``None`` se não casar com ente conhecido ou se
    faltar fonte/chave.
    """
    if not ia_id.startswith(_RAW_PREFIX):
        return None
    content = ia_id[len(_RAW_PREFIX) :]
    for slug in sorted(list_slugs(), key=len, reverse=True):
        if content.startswith(f"{slug}-"):
            rest = content[len(slug) + 1 :]
            if "-" not in rest:
                return None
            fonte, chave = rest.split("-", 1)
            if not fonte or not chave:
                return None
            return slug, fonte, chave
    return None


def merge_index_row(
    existing_csv: Optional[str],
    *,
    tipo: str,
    numero: Optional[int],
    rendicao: str,
    formato: str,
    uuid5: str,
    sha256: str,
    captured_at: Optional[str] = None,
    source: str = "",
    provenance: Optional[Mapping[str, str]] = None,
) -> str:
    """Devolve o index.csv com a captura anexada (append-only, newest-wins).

    Idempotente em ``(tipo, numero, rendicao, formato, sha256)`` — re-capturar os
    mesmos bytes é no-op (preserva a ordem/proveniência). Bytes diferentes para a
    mesma ``(tipo, numero, rendicao, formato)`` anexam uma linha nova; a mais
    recente é a corrente. Para linhas **não identificadas** (sem número), ``source``
    também entra na chave de idempotência, pois a reconciliação casa por ``source``.

    ``provenance`` preenche as colunas de ``PROVENANCE_COLUMNS`` da linha nova (chaves
    ausentes ficam vazias). Não entra na chave de idempotência: re-capturar os mesmos
    bytes continua sendo no-op e **não** reescreve a proveniência da linha existente.
    """
    captured_at = captured_at or datetime.now(tz=timezone.utc).isoformat()
    rows: list[dict[str, str]] = []
    if existing_csv:
        for row in csv.DictReader(io.StringIO(existing_csv)):
            rows.append({c: row.get(c, "") or "" for c in INDEX_COLUMNS})
    # numero ausente (área de espera _unidentified): grava vazio até reconciliar.
    numero_s = "" if numero is None else str(numero)

    # No-op verdadeiro: mesma identidade+rendição+formato já registrada com estes
    # bytes → preserva (re-anexar mudaria a posição e o "newest wins"). Para linhas
    # **não identificadas** (sem número, área de espera) `source` entra na chave: a
    # reconciliação casa por `source`, então bytes iguais de origens distintas
    # precisam coexistir — senão a 2ª origem (talvez a única promovível) some.
    def _is_noop(r: dict[str, str]) -> bool:
        same = (
            r["tipo"] == tipo
            and r["numero"] == numero_s
            and r["rendicao"] == rendicao
            and r["formato"] == formato
            and r["sha256"] == sha256
        )
        if numero_s == "":
            same = same and r.get("source", "") == source
        return same

    if existing_csv and any(_is_noop(r) for r in rows):
        return existing_csv
    rows.append(
        {
            "tipo": tipo,
            "numero": numero_s,
            "rendicao": rendicao,
            "formato": formato,
            "uuid5": uuid5,
            "sha256": sha256,
            "captured_at": captured_at,
            "source": source,
            **{c: str((provenance or {}).get(c, "") or "") for c in PROVENANCE_COLUMNS},
        }
    )
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=INDEX_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def remove_index_rows(index_csv: str, keys: set[tuple[str, str]]) -> str:
    """Reescreve o index.csv sem as linhas cujo ``(uuid5, source)`` está em ``keys``.

    Usado pela reconciliação ao **promover** arquivos da área de espera
    ``_unidentified`` para o item de range. Removemos por ``(uuid5, source)``, não
    só por ``uuid5``: dois arquivos de bytes idênticos mas origens distintas
    compartilham o ``uuid5`` (dedup por conteúdo), e promover só uma origem **não**
    pode apagar o alias ainda não identificado da outra.
    """
    rows = [
        {c: r.get(c, "") or "" for c in INDEX_COLUMNS}
        for r in csv.DictReader(io.StringIO(index_csv))
        if (r.get("uuid5", ""), r.get("source", "")) not in keys
    ]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=INDEX_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def uuid5_collision(index_csv: str, *, uuid5: str, sha256: str) -> bool:
    """True se ``uuid5`` já existe no índice com um SHA-256 diferente.

    Detecta a colisão rara de UUIDv5 truncado dentro de um item (mesmo nome curto,
    bytes diferentes) — o chamador trata em vez de sobrescrever silenciosamente.
    """
    for row in csv.DictReader(io.StringIO(index_csv)):
        if row.get("uuid5") == uuid5 and row.get("sha256") != sha256:
            return True
    return False


def lookup_current(
    index_csv: str,
    tipo: str,
    numero: int,
    *,
    rendicao: Optional[str] = None,
    formato: Optional[str] = None,
) -> Optional[dict[str, str]]:
    """Retorna a linha corrente (mais recente) para ``(tipo, numero[, rendição][, formato])``.

    Filtra por rendição/formato quando especificados (necessário porque uma norma
    pode ter componentes distintos — pdf/original, html/atual). A corrente é a
    última linha que casa no índice append-only. ``None`` se nada casar.
    """
    numero_s = str(numero)
    found: Optional[dict[str, str]] = None
    for row in csv.DictReader(io.StringIO(index_csv)):
        if row.get("tipo") != tipo or row.get("numero") != numero_s:
            continue
        if rendicao is not None and row.get("rendicao", "") != rendicao:
            continue
        if formato is not None and row.get("formato", "") != formato:
            continue
        found = {c: row.get(c, "") or "" for c in INDEX_COLUMNS}
    return found


def list_identities(index_csv: str) -> set[str]:
    """Conjunto de chaves ``{tipo}-{numero:05d}`` distintas no índice.

    Usado pela descoberta (list_raw_ids) para reconstruir os raw_ids legados que o
    parser sabe resolver. O identifier do item (range) não carrega norma a norma.
    """
    keys: set[str] = set()
    for row in csv.DictReader(io.StringIO(index_csv)):
        tipo = row.get("tipo")
        numero = row.get("numero")
        if tipo and numero and numero.isdigit():
            keys.add(f"{tipo}-{int(numero):05d}")
    return keys


def _fetch_text(url: str, timeout: int = 30) -> Optional[str]:
    """GET de um arquivo texto do IA. ``None`` em qualquer falha de rede/404."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")  # type: ignore[no-any-return]
    except (urllib.error.URLError, OSError, ValueError):
        return None


def resolve_raw_url(
    ia_id: str,
    suffix: str,
    timeout: int = 30,
    rendicao: Optional[str] = None,
) -> Optional[str]:
    """Resolve um raw_id legado para a URL content-addressed do arquivo (ADR-0011).

    Passos: parse do raw_id → identidade ``(tipo, número)`` → item de range →
    fetch do index.csv → lookup do arquivo corrente → monta a URL.

    IDs que não casam com o padrão raw (itens externos/legados) caem no
    pass-through clássico ``{ia_id}/{ia_id}{suffix}``. Retorna ``None`` quando a
    chave não tem identidade (não está na coleção), o índice não existe ainda, ou
    a norma/rendição não foi capturada — o chamador trata como "ainda indisponível".
    """
    parsed = parse_raw_id(ia_id)
    if parsed is None:
        return download_url(ia_id, f"{ia_id}{suffix}")

    ente, fonte, chave = parsed
    identity = parse_identity(chave)
    if identity is None:
        return None  # sem (tipo, número) → não está na coleção

    tipo, numero = identity
    item_id = range_item_identifier(ente, fonte, tipo, numero)
    index_csv = _fetch_text(download_url(item_id, INDEX_FILENAME), timeout=timeout)
    if not index_csv:
        return None

    row = lookup_current(
        index_csv,
        tipo,
        numero,
        rendicao=rendicao,
        formato=_SUFFIX_TO_FORMATO.get(suffix),
    )
    if row is None:
        return None
    tipo_row = row.get("tipo", "")
    numero_row = row.get("numero")
    name_prefix = None
    if tipo_row and numero_row is not None:
        try:
            name_prefix = f"{tipo_row}-{int(numero_row):05d}"
        except (ValueError, TypeError):
            name_prefix = f"{tipo_row}-{numero_row}"
    return download_url(
        item_id,
        raw_filename(row["uuid5"], suffix, name_prefix=name_prefix),
    )
