"""Teacher-labelling batch pipeline (DAG node ``boundary-decision-parser``).

Produces **line-level structural labels** for Rondônia norms through the
Anthropic Message Batches API. The labels are the independent gold used to
measure the deterministic reader (``article_sequence.py``) and to calibrate the
cheap decision models — so this module is a *classifier, not a rewriter*: the
model receives the OCR text with numbered lines and answers with labels only for
the lines that START a structural element. The norm text is never re-emitted.

Three resumable steps, each a subcommand (``python -m leizilla.teacher_batch``):

``plan``     enumerate inputs on the Internet Archive, build the requests and
             print the estimated cost per model. Sends nothing billable.
``submit``   same enumeration, then the mandatory cost guard (``--max-usd``, no
             default), then creates the batch(es) and writes a manifest JSON
             with the batch ids and the ``custom_id`` → (item, uuid5, chunk) map.
``collect``  reads the manifest, fetches the results, validates every response
             against the label schema, merges chunks deterministically and
             writes one JSONL per norm plus a summary of failures.

Batches may take up to 24h, so ``submit`` and ``collect`` are separate runs; the
manifest is the only state carried between them.

Design notes that are easy to get wrong:

* **Line numbers are global and stable.** They are 1-based indexes into
  ``text.split("\\n")`` of the exact ``_djvu.txt`` bytes (``text_sha256`` is in
  the output so a consumer can check it holds the same text). Blank lines are
  not sent, but they still count.
* **No response is ever length-truncated by construction**: a document is cut
  into chunks of at most ``max_lines`` non-blank lines, and ``max_tokens`` is
  sized from the chunk. A chunk carries read-only context (head of the document
  and the lines just before it); only its *owned* lines may be labelled, so the
  merge is a plain concatenation with no tie-breaking.
* **Nothing is silently accepted.** A norm is written only when every one of its
  chunks succeeded with ``stop_reason == "end_turn"`` and valid labels; anything
  else lands in ``failures.jsonl`` with the reason.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import math
import os
import re
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import duckdb
import typer

from leizilla import publisher
from leizilla.ia_utils import download_url

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Contract versions (provenance — bump when the prompt or the schema changes)
# --------------------------------------------------------------------------

PROMPT_VERSION = "teacher-labels-v1"
LABEL_SCHEMA_VERSION = "1"
MANIFEST_VERSION = 1

CATEGORIES: tuple[str, ...] = (
    "ementa",
    "preambulo",
    "artigo",
    "paragrafo",
    "inciso",
    "alinea",
    "item",
    "vigencia",
    "revogacao",
    "assinatura",
    "anexo",
)
NUMBERED_CATEGORIES: frozenset[str] = frozenset(
    {"artigo", "paragrafo", "inciso", "alinea"}
)
AMEND_ACTIONS: tuple[str, ...] = ("altera", "revoga")

_NULLABLE_STRING: Dict[str, Any] = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NULLABLE_INTEGER: Dict[str, Any] = {"anyOf": [{"type": "integer"}, {"type": "null"}]}

# Strict JSON schema for ``output_config.format`` (structured outputs). Only
# constructs the API documents as supported: every object closed with
# ``additionalProperties: false``, every property required, optionality through
# ``anyOf`` with null, no numeric/string/array constraints.
LABEL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer"},
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "number": _NULLABLE_STRING,
                    "quoted": {"type": "boolean"},
                },
                "required": ["line", "category", "number", "quoted"],
                "additionalProperties": False,
            },
        },
        "amends": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": list(AMEND_ACTIONS)},
                    "tipo": {"type": "string"},
                    "numero": _NULLABLE_STRING,
                    "ano": _NULLABLE_INTEGER,
                },
                "required": ["action", "tipo", "numero", "ano"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["labels", "amends"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
Você é um anotador especialista em técnica legislativa brasileira. Sua tarefa é \
CLASSIFICAR linhas do texto de uma norma do Estado de Rondônia; você nunca \
reescreve, corrige ou devolve o texto da norma.

# Entrada

O texto vem de OCR de documentos digitalizados (muitos datilografados nos anos \
1980) e chega com as linhas numeradas, no formato `NÚMERO<TAB>TEXTO`. Linhas em \
branco foram omitidas, por isso a numeração pode ter saltos: use sempre o número \
que acompanha a linha. Normas longas chegam em partes; nesse caso há blocos de \
contexto somente para leitura:

- `<contexto_cabecalho>`: as primeiras linhas da norma (epígrafe, ementa);
- `<contexto_anterior>`: as linhas imediatamente anteriores à parte atual;
- `<linhas_a_rotular>`: as ÚNICAS linhas que você pode rotular.

# O que rotular

Rotule SOMENTE a linha em que COMEÇA um elemento estrutural. Linhas de \
continuação (o resto de um artigo, de um inciso, de uma ementa) não recebem \
rótulo. A maioria das linhas não recebe rótulo. Categorias:

- `ementa`: primeira linha do resumo do objeto da norma (logo após a epígrafe).
- `preambulo`: primeira linha da fórmula de promulgação ("O GOVERNADOR DO ESTADO \
DE RONDÔNIA, ...", "Faço saber que a Assembleia Legislativa decreta ...").
- `artigo`: linha que abre um artigo ("Art. 1º", "Artigo 2º").
- `paragrafo`: linha que abre um parágrafo ("§ 1º", "Parágrafo único").
- `inciso`: linha que abre um inciso (algarismo romano: "I -", "II –").
- `alinea`: linha que abre uma alínea (letra minúscula: "a)", "b)").
- `item`: linha que abre um item dentro de alínea (algarismo arábico: "1.", "2 -").
- `vigencia`: linha que abre a cláusula de vigência ("Esta Lei entra em vigor ..."). \
Se a cláusula é o conteúdo de um artigo e começa na mesma linha do "Art.", rotule \
a linha como `artigo`, não como `vigencia`; use `vigencia` quando a cláusula \
começa em linha própria.
- `revogacao`: linha que abre a cláusula revogatória ("Revogam-se as disposições \
em contrário", "Ficam revogados ..."), com a mesma regra da vigência.
- `assinatura`: primeira linha do fecho (local e data, "Palácio do Governo ...") e \
cada linha com nome de autoridade signatária.
- `anexo`: linha que abre um anexo ("ANEXO I", "ANEXO ÚNICO").

Cabeçalhos repetidos de página ("GOVERNO DO ESTADO DE RONDÔNIA", "GOVERNADORIA"), \
epígrafe, linhas de tabelas, ruído de OCR e carimbos não são rotulados.

# Campo `number`

Para `artigo`, `paragrafo`, `inciso` e `alinea`, informe o número ou a letra \
NORMALIZADO, como deve ser lido no contexto, não como o OCR o grafou; para as \
demais categorias use `null`.

- `artigo`: algarismos arábicos sem ordinal: "1", "2", "10"; com sufixo quando \
houver: "5-A".
- `paragrafo`: "1", "2", ...; parágrafo único é "unico".
- `inciso`: algarismo romano em maiúsculas: "I", "IV", "XII".
- `alinea`: letra minúscula: "a", "b".

O OCR destrói com frequência o sinal ordinal e os algarismos. Exemplos reais: \
"Art. Io" é o artigo 1; "Art. 42" entre o artigo 3 e o artigo 5 é o artigo 4 (o \
"º" virou "2"); "Art. 1Q", "Art. 3°", "Art. 2-", "Art. 6?" são 1, 3, 2 e 6; \
"Il -" é o inciso II; "§ 12" depois de nenhum parágrafo é o § 1º. Use a sequência \
dos elementos vizinhos para decidir. Se não for possível determinar o número, \
use `null`.

# Campo `quoted`

Leis alteradoras transcrevem dispositivos de OUTRA norma ("O art. 5º da Lei nº \
123 passa a vigorar com a seguinte redação: 'Art. 5º ...'"). Rotule também esses \
dispositivos transcritos, com `quoted: true`: eles pertencem à norma citada, não \
à sequência de artigos desta norma. Os dispositivos próprios desta norma levam \
`quoted: false`. A transcrição nem sempre vem entre aspas no OCR: decida pelo \
contexto (o comando de alteração que a antecede, a quebra na numeração). Uma \
simples menção a um artigo no meio de uma frase ("nos termos do art. 3º") não \
abre elemento e não é rotulada.

# Campo `amends`

Liste as normas que ESTA norma altera ou revoga expressamente, conforme o que \
está visível nesta parte do texto: `action` é "altera" (nova redação, acréscimo, \
supressão parcial) ou "revoga" (revogação de norma ou de dispositivos dela); \
`tipo` em minúsculas sem acento ("lei", "lei complementar", "decreto", \
"decreto-lei", "constituicao estadual"); `numero` só com algarismos, ou `null`; \
`ano` com quatro algarismos quando declarado, ou `null`. Revogação genérica \
("disposições em contrário") não entra. Sem alterações visíveis, devolva lista \
vazia.

# Saída

Responda apenas com o objeto JSON do esquema: `labels` em ordem crescente de \
linha, no máximo um rótulo por linha, usando somente números de linha presentes \
em `<linhas_a_rotular>`; e `amends`.
"""


def prompt_sha256() -> str:
    """Hash of everything that defines the labelling contract sent to the model."""
    blob = SYSTEM_PROMPT + "\n" + json.dumps(LABEL_SCHEMA, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Models and prices
# --------------------------------------------------------------------------

# Prices copied on 2026-11-14 from
# https://platform.claude.com/docs/en/about-claude/pricing (USD per million
# tokens, standard rate). Batch requests cost 50% of every token category and
# the discount stacks with prompt caching (same page, "Batch processing" and
# "How do discounts stack?"). Re-check before a large run: there is deliberately
# no fallback price for an unknown model — ``submit`` refuses it.
BATCH_DISCOUNT = 0.5
CACHE_WRITE_5M_MULT = 1.25
CACHE_WRITE_1H_MULT = 2.0


@dataclass(frozen=True)
class ModelSpec:
    model: str
    input_usd_mtok: float
    output_usd_mtok: float
    cache_read_mult: float
    supports_effort: bool
    # Prompt size above which the model switches to a more expensive rate card
    # (Claude Haiku 5.5: 100K). Requests are kept far below it by chunking; the
    # guard refuses a request that would cross it instead of mispricing it.
    long_prompt_threshold: Optional[int] = None


MODELS: Dict[str, ModelSpec] = {
    spec.model: spec
    for spec in (
        ModelSpec("claude-haiku-5-5", 0.10, 0.50, 0.1, True, 100_000),
        ModelSpec("claude-haiku-4-5", 1.00, 5.00, 0.1, False),
        ModelSpec("claude-sonnet-5-5", 2.00, 10.00, 0.05, True),
        ModelSpec("claude-opus-5-5", 4.00, 20.00, 0.05, True),
    )
}
DEFAULT_MODEL = "claude-haiku-5-5"
EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")

# Batch API limits (https://platform.claude.com/docs/en/build-with-claude/
# batch-processing): 100,000 requests or 256 MB per batch; custom_id must match
# ^[a-zA-Z0-9_-]{1,64}$. The defaults below stay well inside both.
BATCH_MAX_REQUESTS = 100_000
BATCH_MAX_BYTES = 256 * 1024 * 1024
DEFAULT_REQUESTS_PER_BATCH = 10_000
DEFAULT_BYTES_PER_BATCH = 100 * 1024 * 1024
_CUSTOM_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# --------------------------------------------------------------------------
# Estimation constants
# --------------------------------------------------------------------------

# Conservative on purpose. This environment cannot call the token counting API,
# so the offline estimate assumes 2 characters per token, far denser than
# Portuguese prose usually tokenizes (and the current Haiku tokenizer counts
# ~30% more tokens than the previous one for the same text). ``plan
# --count-sample N`` measures the real ratio with ``messages.count_tokens``.
CHARS_PER_TOKEN = 2.0
# Fixed per-request overhead not visible in the text (message framing, the
# structured-output instructions the API adds for the schema).
REQUEST_OVERHEAD_TOKENS = 600
# Worst-case output of one label object ({"line":12345,"category":"paragrafo",
# "number":"unico","quoted":false},) with margin.
TOKENS_PER_LABEL = 40
# Share of sent lines assumed to carry a label in the *estimate* (the measured
# share of marker lines in the corpus is well below this).
ESTIMATE_LABEL_SHARE = 0.5
# Output tokens assumed to be spent thinking, per request, in the *estimate*.
# These are assumptions, not measurements — the pilot's summary.json reports the
# real output tokens per request.
THINKING_ESTIMATE: Dict[str, int] = {
    "low": 500,
    "medium": 1500,
    "high": 4000,
    "xhigh": 8000,
    "max": 12000,
}
# max_tokens = base + per-line allowance, capped. Thinking counts toward
# max_tokens on models that think by default, hence the generous base.
MAX_TOKENS_BASE = 3072
MAX_TOKENS_CAP = 16000

DEFAULT_MAX_LINES = 250
DEFAULT_MAX_CHARS = 20_000
DEFAULT_CONTEXT_LINES = 15
DEFAULT_HEAD_LINES = 10

_UNIDENTIFIED_SUFFIX = "_unidentified"
_USER_AGENT = "leizilla-crawler/0.1"

# Text sources: ``ia`` downloads one ``_djvu.txt`` per norm (slow); ``textos``
# reads the published text layer (one parquet, every text, including texts made
# by the project's own OCR that have no ``_djvu.txt``). The text sent to the model
# is the same string in both cases, so the label headers match either way.
TEXT_SOURCES: tuple[str, ...] = ("ia", "textos")
DEFAULT_TEXTOS_URL = (
    "https://archive.org/download/leizilla-textos-ro-v0-latest/textos.parquet"
)
LABELS_ARCHIVE = "labels.tar.gz"
# Label set name: ``main`` is the tuning set; any other name (e.g. a held-out set)
# is kept apart in the manifest, the summary, the headers and the IA identifier.
DEFAULT_LABEL_SET = "main"
_LABEL_SET_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_IA_ITEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_UUID5_RE = re.compile(r"^[0-9a-f]{8}$")


class TeacherBatchError(RuntimeError):
    """A condition that must stop the step (cost guard, bad manifest, ...)."""


# --------------------------------------------------------------------------
# Inputs: norms on the Internet Archive
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class NormRef:
    """One norm identity with IA OCR text available."""

    item: str
    fonte: str
    tipo: str
    numero: int
    uuid5: str
    txt_name: str

    @property
    def key(self) -> str:
        return f"{self.item}/{self.uuid5}"

    @property
    def ident(self) -> tuple[str, str]:
        """Norm identity as the label headers record it: ``(item, uuid5)``."""
        return (self.item, self.uuid5)

    @property
    def stem(self) -> str:
        return f"{self.tipo}-{self.numero:05d}_{self.uuid5}"


@dataclass
class Enumeration:
    norms: List[NormRef] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def enumerate_norms(
    ente: str, fontes: Sequence[str], tipos: Optional[Sequence[str]] = None
) -> Enumeration:
    """List norm identities that have a ``_djvu.txt`` in the RO raw range items.

    Same sources of truth as ``coverage.compute_fonte_coverage``: the range
    items found by identifier prefix, each item's ``index.csv`` (latest capture
    per identity) and its file list. Transient failures are *recorded*, never
    swallowed — the caller decides whether a partial enumeration is acceptable.
    """
    out = Enumeration()
    wanted = {t.lower() for t in tipos} if tipos else None
    for fonte in fontes:
        prefix = f"leizilla_{ente.lower()}_{fonte.lower()}_"
        item_ids = publisher.scrape_identifiers(prefix)
        if item_ids is None:
            out.errors.append(f"{prefix}*: item search failed")
            continue
        for item in sorted(item_ids):
            if item.endswith(_UNIDENTIFIED_SUFFIX):
                continue
            try:
                index_csv = publisher.fetch_existing_index(item)
            except publisher.IndexFetchError as exc:
                out.errors.append(f"{item}: index.csv fetch failed ({exc})")
                continue
            if index_csv is None:
                continue
            files = publisher.fetch_item_filenames(item)
            if files is None:
                out.errors.append(f"{item}: file list fetch failed")
                continue
            latest: Dict[tuple[str, int], Dict[str, str]] = {}
            for row in csv.DictReader(io.StringIO(index_csv)):
                tipo = (row.get("tipo") or "").strip()
                numero_s = (row.get("numero") or "").strip()
                uuid5 = (row.get("uuid5") or "").strip()
                if row.get("formato") != "pdf" or not tipo or not uuid5:
                    continue
                if not numero_s.isdigit():
                    continue
                if wanted is not None and tipo.lower() not in wanted:
                    continue
                if not any(n.endswith(f"{uuid5}_djvu.txt") for n in files):
                    continue
                ident = (tipo, int(numero_s))
                current = latest.get(ident)
                if current is None or (row.get("captured_at") or "") > (
                    current.get("captured_at") or ""
                ):
                    latest[ident] = row
            for (tipo, numero), row in sorted(latest.items()):
                uuid5 = row["uuid5"].strip()
                txt_name = sorted(n for n in files if n.endswith(f"{uuid5}_djvu.txt"))[
                    0
                ]
                out.norms.append(
                    NormRef(
                        item=item,
                        fonte=fonte,
                        tipo=tipo,
                        numero=numero,
                        uuid5=uuid5,
                        txt_name=txt_name,
                    )
                )
    return out


def select_norms(
    norms: Sequence[NormRef],
    limit: Optional[int] = None,
    shuffle_seed: Optional[str] = None,
    only_keys: Optional[Iterable[str]] = None,
) -> List[NormRef]:
    """Deterministic subset for a pilot.

    Without ``shuffle_seed`` the order is (item, tipo, numero). With it, norms
    are ordered by a hash of ``seed|key`` — a reproducible spread over items and
    decades instead of the first N laws of 1982.
    """
    selected = list(norms)
    if only_keys is not None:
        keep = set(only_keys)
        selected = [n for n in selected if n.key in keep]
    if shuffle_seed is not None:
        selected.sort(
            key=lambda n: hashlib.sha256(
                f"{shuffle_seed}|{n.key}".encode("utf-8")
            ).hexdigest()
        )
    else:
        selected.sort(key=lambda n: (n.item, n.tipo, n.numero, n.uuid5))
    if limit is not None:
        selected = selected[: max(0, limit)]
    return selected


def fetch_text(
    ref: NormRef,
    cache_dir: Optional[Path] = None,
    *,
    retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> Optional[str]:
    """Download one ``_djvu.txt`` from IA (optionally through a local cache).

    ``None`` after ``retries`` failed attempts — the caller records the norm as
    not fetched rather than labelling an empty text.
    """
    cache_path: Optional[Path] = None
    if cache_dir is not None:
        cache_path = cache_dir / ref.item / ref.txt_name
        if cache_path.is_file():
            return cache_path.read_text(encoding="utf-8")
    url = download_url(ref.item, ref.txt_name)
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=40) as resp:
                text: str = resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError) as exc:
            logger.warning("fetch %s failed (%d/%d): %s", url, attempt, retries, exc)
            if attempt < retries:
                sleep(2.0 * attempt)
            continue
        if cache_path is not None:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(text, encoding="utf-8")
        return text
    return None


# --------------------------------------------------------------------------
# Text source ``textos``: the published text layer (one parquet)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TextoRecord:
    ref: NormRef
    text: str
    text_sha256: str
    ocr_motor: Optional[str]


@dataclass
class TextosCorpus:
    file_sha256: str
    records: List[TextoRecord] = field(default_factory=list)
    skipped: Dict[str, int] = field(default_factory=dict)


def _url_basename(url: str) -> str:
    return url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]


def uuid5_from_filename(name: str) -> Optional[str]:
    """The uuid5 the pipeline puts in a raw file name.

    ``lei-00331_672fe440_djvu.txt`` and ``decreto-32194_faa3b3e6.pdf`` give
    ``672fe440`` and ``faa3b3e6``; ``000001_df90ea45_djvu.txt`` gives ``df90ea45``.
    Same rule as ``enumerate_norms``, which keys norms by ``index.csv`` uuid5.
    """
    for suffix in ("_djvu.txt", ".pdf"):
        if name.endswith(suffix):
            candidate = name[: -len(suffix)].rsplit("_", 1)[-1]
            return candidate if _UUID5_RE.match(candidate) else None
    return None


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_textos(path: Path) -> TextosCorpus:
    """Read the published ``textos.parquet`` into norm refs with their text.

    Identity is ``(ia_item, uuid5)``, the label header's ``(item, uuid5)``: taken
    from ``texto_url`` when it names the raw ``_djvu.txt``, else from ``pdf_url``
    (re-OCR rows have no djvu). ``txt_name`` is that file name; for pdf-only rows
    it is the pdf name with ``_djvu.txt`` in place of ``.pdf`` (a label only, never
    fetched from IA on this path). The text is hashed exactly as ``build_plan``
    hashes it, so the header ``text_sha256`` is the one the comparison script
    checks. A row whose declared ``sha256_texto`` disagrees with its text is
    skipped and counted, never labelled.
    """
    corpus = TextosCorpus(file_sha256=_file_sha256(path))
    con = duckdb.connect()
    try:
        rows = con.execute(
            "select ia_item, fonte, tipo, numero, texto_url, pdf_url, sha256_texto, "
            "ocr_motor, texto from read_parquet(?) where texto is not null "
            "order by ia_item, tipo, numero, texto_id",
            [str(path)],
        ).fetchall()
    finally:
        con.close()

    seen: set[tuple[str, str]] = set()

    def skip(reason: str) -> None:
        corpus.skipped[reason] = corpus.skipped.get(reason, 0) + 1

    for item, fonte, tipo, numero, texto_url, pdf_url, declared, motor, text in rows:
        if not (item and tipo and numero is not None):
            skip("incomplete_row")
            continue
        if texto_url:
            txt_name = _url_basename(texto_url)
        elif pdf_url:
            txt_name = Path(_url_basename(pdf_url)).stem + "_djvu.txt"
        else:
            skip("no_identity")
            continue
        uuid5 = uuid5_from_filename(txt_name)
        if uuid5 is None:
            skip("no_identity")
            continue
        sha = hashlib.sha256(str(text).encode("utf-8")).hexdigest()
        if declared is not None and declared != sha:
            skip("sha_mismatch")
            continue
        ident = (str(item), uuid5)
        if ident in seen:
            raise TeacherBatchError(f"textos: duplicate identity {ident}")
        seen.add(ident)
        ref = NormRef(
            item=str(item),
            fonte=str(fonte or ""),
            tipo=str(tipo),
            numero=int(numero),
            uuid5=uuid5,
            txt_name=txt_name,
        )
        corpus.records.append(
            TextoRecord(
                ref=ref,
                text=str(text),
                text_sha256=sha,
                ocr_motor=str(motor) if motor is not None else None,
            )
        )
    return corpus


def _download_to(url: str, dest: Path, *, retries: int = 3) -> None:
    """Download a whole file; raises ``TeacherBatchError`` after ``retries``."""
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as resp:
                dest.write_bytes(resp.read())
            return
        except (urllib.error.URLError, OSError) as exc:
            logger.warning("download %s failed (%d/%d): %s", url, attempt, retries, exc)
            if attempt < retries:
                time.sleep(2.0 * attempt)
    raise TeacherBatchError(f"download failed after {retries} attempts: {url}")


# --------------------------------------------------------------------------
# Exclusion of norms already labelled
# --------------------------------------------------------------------------


def _label_headers(root: Path) -> List[Dict[str, Any]]:
    """Header records of every norm file under ``root`` (failures.jsonl skipped)."""
    headers: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("*.jsonl")):
        if path.name == "failures.jsonl":
            continue
        with path.open(encoding="utf-8") as fh:
            first = fh.readline()
        if not first.strip():
            continue
        header = json.loads(first)
        if header.get("record") == "norm":
            headers.append(header)
    return headers


def _fetch_label_headers(item: str) -> List[Dict[str, Any]]:
    """Headers from the ``labels.tar.gz`` of an IA item, extracted to a temp dir."""
    url = download_url(item, LABELS_ARCHIVE)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / LABELS_ARCHIVE
        extracted = Path(tmp) / "labels"
        extracted.mkdir()
        _download_to(url, archive)
        try:
            with tarfile.open(archive, "r:gz") as tar:
                tar.extractall(extracted, filter="data")
        except tarfile.TarError as exc:
            raise TeacherBatchError(f"{url}: unreadable archive ({exc})") from exc
        return _label_headers(extracted)


def load_label_index(source: str) -> LabelIndex:
    """``(item, uuid5)`` -> set of ``text_sha256`` of every label on record.

    ``source`` is a local labels directory or an IA item holding
    ``labels.tar.gz``. Every label file counts, whatever its label set.
    """
    local = Path(source)
    if local.is_dir():
        headers = _label_headers(local)
    elif _IA_ITEM_RE.match(source):
        headers = _fetch_label_headers(source)
    else:
        raise TeacherBatchError(
            f"--exclude-labelled {source!r} is neither a directory nor an IA item"
        )
    index: LabelIndex = {}
    for header in headers:
        ident = (str(header["item"]), str(header["uuid5"]))
        index.setdefault(ident, set()).add(str(header["text_sha256"]))
    return index


def check_label_set(name: str) -> str:
    if not _LABEL_SET_RE.match(name):
        raise TeacherBatchError(
            f"label_set {name!r} must be lowercase letters, digits and hyphens "
            "(max 32 chars)"
        )
    return name


# --------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    """Global 1-based line numbers; only ``owned`` lines may be labelled."""

    index: int
    total: int
    owned: tuple[int, ...]
    context: tuple[int, ...]
    head: tuple[int, ...]

    @property
    def first_line(self) -> int:
        return self.owned[0]

    @property
    def last_line(self) -> int:
        return self.owned[-1]


def split_lines(text: str) -> List[str]:
    """The one definition of a line: ``text.split("\\n")``, 1-based when cited."""
    return text.split("\n")


def chunk_document(
    lines: Sequence[str],
    max_lines: int = DEFAULT_MAX_LINES,
    max_chars: int = DEFAULT_MAX_CHARS,
    context_lines: int = DEFAULT_CONTEXT_LINES,
    head_lines: int = DEFAULT_HEAD_LINES,
) -> List[Chunk]:
    """Cut a document into chunks of non-blank lines.

    Every non-blank line is owned by exactly one chunk, in order. A chunk closes
    when it reaches ``max_lines`` lines or ``max_chars`` characters. Chunks
    after the first also carry, read-only, the ``context_lines`` lines just
    before them and the first ``head_lines`` lines of the document (minus any
    overlap between the two). Returns ``[]`` for a text with no content.
    """
    if max_lines < 1 or max_chars < 1:
        raise ValueError("max_lines and max_chars must be positive")
    nonblank = [i + 1 for i, line in enumerate(lines) if line.strip()]
    if not nonblank:
        return []
    groups: List[List[int]] = []
    current: List[int] = []
    chars = 0
    for n in nonblank:
        size = len(lines[n - 1]) + 1
        if current and (len(current) >= max_lines or chars + size > max_chars):
            groups.append(current)
            current, chars = [], 0
        current.append(n)
        chars += size
    groups.append(current)

    position = {n: i for i, n in enumerate(nonblank)}
    head_all = nonblank[: max(0, head_lines)]
    chunks: List[Chunk] = []
    for index, owned in enumerate(groups):
        context: List[int] = []
        head: List[int] = []
        if index > 0:
            start = position[owned[0]]
            context = nonblank[max(0, start - max(0, context_lines)) : start]
            floor = context[0] if context else owned[0]
            head = [n for n in head_all if n < floor]
        chunks.append(
            Chunk(
                index=index,
                total=len(groups),
                owned=tuple(owned),
                context=tuple(context),
                head=tuple(head),
            )
        )
    return chunks


def _numbered(lines: Sequence[str], numbers: Iterable[int]) -> str:
    return "\n".join(f"{n}\t{lines[n - 1].strip()}" for n in numbers)


def render_user_message(ref: NormRef, lines: Sequence[str], chunk: Chunk) -> str:
    """The per-request (uncached) part of the prompt."""
    parts = [
        f'<norma tipo="{ref.tipo}" numero="{ref.numero}" '
        f'parte="{chunk.index + 1}/{chunk.total}">'
    ]
    if chunk.head:
        parts.append(
            "<contexto_cabecalho>\n"
            + _numbered(lines, chunk.head)
            + "\n</contexto_cabecalho>"
        )
    if chunk.context:
        parts.append(
            "<contexto_anterior>\n"
            + _numbered(lines, chunk.context)
            + "\n</contexto_anterior>"
        )
    parts.append(
        "<linhas_a_rotular>\n" + _numbered(lines, chunk.owned) + "\n</linhas_a_rotular>"
    )
    parts.append("</norma>")
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Requests and cost
# --------------------------------------------------------------------------


@dataclass
class PlannedRequest:
    custom_id: str
    norm: NormRef
    chunk: Chunk
    text_sha256: str
    n_lines: int
    user_text: str
    max_tokens: int


@dataclass
class Plan:
    requests: List[PlannedRequest] = field(default_factory=list)
    norms: List[NormRef] = field(default_factory=list)
    empty: List[str] = field(default_factory=list)
    fetch_failed: List[str] = field(default_factory=list)
    enumeration_errors: List[str] = field(default_factory=list)
    # Exclusion against existing labels (only when --exclude-labelled is given).
    available: int = 0
    labelled_excluded: List[str] = field(default_factory=list)
    # Selected norm key -> "new_norm" | "new_text" (new text of a labelled norm).
    status: Dict[str, str] = field(default_factory=dict)
    # Selected norm key -> OCR motor of its text (provenance of the text).
    ocr_motor: Dict[str, Optional[str]] = field(default_factory=dict)
    # Where the texts and the exclusion came from; recorded in the manifest.
    sources: Dict[str, Any] = field(default_factory=dict)


def max_tokens_for(chunk: Chunk, cap: int = MAX_TOKENS_CAP) -> int:
    """Enough for a label on every owned line plus thinking, never above ``cap``."""
    return min(cap, MAX_TOKENS_BASE + TOKENS_PER_LABEL * len(chunk.owned))


LabelIndex = Dict[tuple[str, str], set[str]]


def label_status(
    ident: tuple[str, str], text_sha256: str, labelled: Optional[LabelIndex]
) -> Optional[str]:
    """Classify one norm text against the existing labels.

    ``None`` without an index. ``excluded``: a label exists for the same identity
    and the same text sha256. ``new_text``: labelled norm whose text changed (e.g.
    re-OCR replaced it), so it is selected. ``new_norm``: never labelled.
    """
    if labelled is None:
        return None
    shas = labelled.get(ident)
    if shas is None:
        return "new_norm"
    return "excluded" if text_sha256 in shas else "new_text"


def build_plan(
    norms: Sequence[NormRef],
    load_text: Callable[[NormRef], Optional[str]],
    *,
    max_lines: int = DEFAULT_MAX_LINES,
    max_chars: int = DEFAULT_MAX_CHARS,
    context_lines: int = DEFAULT_CONTEXT_LINES,
    head_lines: int = DEFAULT_HEAD_LINES,
    max_tokens_cap: int = MAX_TOKENS_CAP,
    labelled: Optional[LabelIndex] = None,
) -> Plan:
    plan = Plan()
    for seq, ref in enumerate(norms):
        text = load_text(ref)
        if text is None:
            plan.fetch_failed.append(ref.key)
            continue
        plan.available += 1
        text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        status = label_status(ref.ident, text_sha, labelled)
        if status == "excluded":
            plan.labelled_excluded.append(ref.key)
            continue
        lines = split_lines(text)
        chunks = chunk_document(
            lines,
            max_lines=max_lines,
            max_chars=max_chars,
            context_lines=context_lines,
            head_lines=head_lines,
        )
        if not chunks:
            plan.empty.append(ref.key)
            continue
        plan.norms.append(ref)
        if status is not None:
            plan.status[ref.key] = status
        for chunk in chunks:
            custom_id = f"t{seq:06d}-{ref.uuid5}-c{chunk.index:04d}"
            if not _CUSTOM_ID_RE.match(custom_id):
                raise TeacherBatchError(f"invalid custom_id {custom_id!r}")
            plan.requests.append(
                PlannedRequest(
                    custom_id=custom_id,
                    norm=ref,
                    chunk=chunk,
                    text_sha256=text_sha,
                    n_lines=len(lines),
                    user_text=render_user_message(ref, lines, chunk),
                    max_tokens=max_tokens_for(chunk, max_tokens_cap),
                )
            )
    return plan


def resolve_model(model: str) -> ModelSpec:
    spec = MODELS.get(model)
    if spec is None:
        raise TeacherBatchError(
            f"unknown model {model!r}: no price on file, so no cost can be "
            f"guaranteed. Known models: {', '.join(sorted(MODELS))}. Add the "
            "model and its current price to MODELS in teacher_batch.py."
        )
    return spec


def build_request_params(
    req: PlannedRequest, spec: ModelSpec, effort: str, cache: bool
) -> Dict[str, Any]:
    """Messages API params for one chunk (the ``params`` of a batch request).

    * the instruction prefix is a system block, byte-identical across requests,
      with a 1-hour cache breakpoint (batches can run longer than 5 minutes);
    * ``output_config.format`` constrains the answer to ``LABEL_SCHEMA``;
    * no sampling parameters and no ``thinking`` field: current models reject
      non-default sampling and think adaptively by default; depth is set with
      ``output_config.effort`` where the model accepts it.
    """
    system_block: Dict[str, Any] = {"type": "text", "text": SYSTEM_PROMPT}
    if cache:
        system_block["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    output_config: Dict[str, Any] = {
        "format": {"type": "json_schema", "schema": LABEL_SCHEMA}
    }
    if spec.supports_effort:
        output_config["effort"] = effort
    return {
        "model": spec.model,
        "max_tokens": req.max_tokens,
        "system": [system_block],
        "messages": [{"role": "user", "content": req.user_text}],
        "output_config": output_config,
    }


def estimate_tokens(chars: int, chars_per_token: float = CHARS_PER_TOKEN) -> int:
    return math.ceil(chars / chars_per_token)


@dataclass
class CostEstimate:
    model: str
    effort: Optional[str]
    requests: int
    norms: int
    chars_per_token: float
    system_tokens: int
    input_tokens: int
    estimated_output_tokens: int
    ceiling_output_tokens: int
    estimate_usd: float
    ceiling_usd: float
    max_request_input_tokens: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def estimate_cost(
    plan: Plan,
    spec: ModelSpec,
    effort: str,
    cache: bool,
    chars_per_token: float = CHARS_PER_TOKEN,
) -> CostEstimate:
    """Two numbers per model, both at batch prices.

    ``estimate_usd``: conservative expectation — conservative token density, no
    credit for cache hits, thinking allowance by effort and a label on half of
    all lines.

    ``ceiling_usd``: an upper bound for the requests as built — every request
    spends its whole ``max_tokens`` and, with caching on, pays the 1-hour cache
    write premium on the shared prefix with zero hits. It is a bound only as far
    as ``chars_per_token`` really is conservative for the model's tokenizer.
    """
    system_tokens = estimate_tokens(len(SYSTEM_PROMPT), chars_per_token)
    n = len(plan.requests)
    user_tokens = [
        estimate_tokens(len(r.user_text), chars_per_token) + REQUEST_OVERHEAD_TOKENS
        for r in plan.requests
    ]
    input_tokens = sum(user_tokens) + system_tokens * n
    think = THINKING_ESTIMATE[effort] if spec.supports_effort else 0
    est_out = sum(
        min(
            r.max_tokens,
            think
            + 200
            + math.ceil(TOKENS_PER_LABEL * ESTIMATE_LABEL_SHARE * len(r.chunk.owned)),
        )
        for r in plan.requests
    )
    ceil_out = sum(r.max_tokens for r in plan.requests)
    in_price = spec.input_usd_mtok * BATCH_DISCOUNT / 1e6
    out_price = spec.output_usd_mtok * BATCH_DISCOUNT / 1e6
    estimate = input_tokens * in_price + est_out * out_price
    system_mult = CACHE_WRITE_1H_MULT if cache else 1.0
    ceiling = (
        sum(user_tokens) * in_price
        + system_tokens * n * in_price * system_mult
        + ceil_out * out_price
    )
    return CostEstimate(
        model=spec.model,
        effort=effort if spec.supports_effort else None,
        requests=n,
        norms=len(plan.norms),
        chars_per_token=chars_per_token,
        system_tokens=system_tokens,
        input_tokens=input_tokens,
        estimated_output_tokens=est_out,
        ceiling_output_tokens=ceil_out,
        estimate_usd=round(estimate, 4),
        ceiling_usd=round(ceiling, 4),
        max_request_input_tokens=(max(user_tokens) + system_tokens) if n else 0,
    )


def check_cost_guard(
    estimate: CostEstimate, spec: ModelSpec, max_usd: float, guard: str
) -> None:
    """Raise unless the run fits ``max_usd``. Called before any batch exists."""
    if guard not in ("ceiling", "estimate"):
        raise TeacherBatchError(f"unknown guard {guard!r} (ceiling|estimate)")
    if not (max_usd > 0):
        raise TeacherBatchError("--max-usd must be a positive number")
    if (
        spec.long_prompt_threshold is not None
        and estimate.max_request_input_tokens >= spec.long_prompt_threshold
    ):
        raise TeacherBatchError(
            f"a request is estimated at {estimate.max_request_input_tokens} input "
            f"tokens, at or above the {spec.long_prompt_threshold}-token threshold "
            f"where {spec.model} switches to a higher price. Lower --max-chars."
        )
    amount = estimate.ceiling_usd if guard == "ceiling" else estimate.estimate_usd
    if amount > max_usd:
        raise TeacherBatchError(
            f"cost guard: {guard} US${amount:.2f} for {estimate.requests} requests "
            f"on {spec.model} exceeds --max-usd {max_usd:.2f}. Nothing was submitted."
        )


def count_tokens_sample(
    client: Any,
    plan: Plan,
    spec: ModelSpec,
    effort: str,
    sample: int,
) -> Optional[Dict[str, Any]]:
    """Measure real input tokens on a deterministic sample of requests.

    Uses ``messages.count_tokens`` (free, model-specific). Returns the measured
    characters-per-token ratio, to compare with ``CHARS_PER_TOKEN``.
    """
    if sample <= 0 or not plan.requests:
        return None
    step = max(1, len(plan.requests) // sample)
    picked = plan.requests[::step][:sample]
    chars = 0
    tokens = 0
    for req in picked:
        params = build_request_params(req, spec, effort, cache=False)
        counted = client.messages.count_tokens(
            model=params["model"],
            system=params["system"],
            messages=params["messages"],
            output_config=params["output_config"],
        )
        tokens += int(counted.input_tokens)
        chars += len(SYSTEM_PROMPT) + len(req.user_text)
    return {
        "model": spec.model,
        "sampled_requests": len(picked),
        "chars": chars,
        "input_tokens": tokens,
        "measured_chars_per_token": round(chars / tokens, 4) if tokens else None,
        "assumed_chars_per_token": CHARS_PER_TOKEN,
    }


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------


def git_sha() -> Optional[str]:
    return os.getenv("GITHUB_SHA") or publisher.get_git_sha()


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def split_batches(
    requests: Sequence[Dict[str, Any]],
    max_requests: int = DEFAULT_REQUESTS_PER_BATCH,
    max_bytes: int = DEFAULT_BYTES_PER_BATCH,
) -> List[List[Dict[str, Any]]]:
    """Group batch requests so each batch respects both API limits."""
    if not (0 < max_requests <= BATCH_MAX_REQUESTS):
        raise TeacherBatchError(f"max_requests must be in 1..{BATCH_MAX_REQUESTS}")
    if not (0 < max_bytes <= BATCH_MAX_BYTES):
        raise TeacherBatchError(f"max_bytes must be in 1..{BATCH_MAX_BYTES}")
    batches: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    size = 0
    for request in requests:
        request_bytes = len(json.dumps(request, ensure_ascii=False).encode("utf-8"))
        if request_bytes > max_bytes:
            raise TeacherBatchError(
                f"request {request['custom_id']} alone is {request_bytes} bytes"
            )
        if current and (
            len(current) >= max_requests or size + request_bytes > max_bytes
        ):
            batches.append(current)
            current, size = [], 0
        current.append(request)
        size += request_bytes
    if current:
        batches.append(current)
    return batches


def build_manifest(
    plan: Plan,
    estimate: CostEstimate,
    *,
    ente: str,
    effort: Optional[str],
    cache: bool,
    max_usd: float,
    guard: str,
    label_set: str = DEFAULT_LABEL_SET,
) -> Dict[str, Any]:
    return {
        "manifest_version": MANIFEST_VERSION,
        "created_at": _now(),
        "ente": ente,
        "label_set": label_set,
        "sources": plan.sources,
        "model": estimate.model,
        "effort": effort,
        "prompt_cache": cache,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha256(),
        "label_schema_version": LABEL_SCHEMA_VERSION,
        "git_sha": git_sha(),
        "max_usd": max_usd,
        "guard": guard,
        "estimate": estimate.to_dict(),
        "enumeration_errors": list(plan.enumeration_errors),
        "fetch_failed": list(plan.fetch_failed),
        "empty": list(plan.empty),
        "batches": [],
        "requests": {
            r.custom_id: {
                "item": r.norm.item,
                "fonte": r.norm.fonte,
                "tipo": r.norm.tipo,
                "numero": r.norm.numero,
                "uuid5": r.norm.uuid5,
                "txt_name": r.norm.txt_name,
                "chunk": r.chunk.index,
                "chunks": r.chunk.total,
                "first_line": r.chunk.first_line,
                "last_line": r.chunk.last_line,
                "n_lines": r.n_lines,
                "text_sha256": r.text_sha256,
                "max_tokens": r.max_tokens,
            }
            for r in plan.requests
        },
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_manifest(path: Path) -> Dict[str, Any]:
    manifest: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise TeacherBatchError(
            f"{path}: manifest_version {manifest.get('manifest_version')!r} "
            f"is not {MANIFEST_VERSION}"
        )
    return manifest


def submit_batches(
    client: Any,
    plan: Plan,
    spec: ModelSpec,
    manifest: Dict[str, Any],
    manifest_path: Path,
    *,
    effort: str,
    cache: bool,
    max_requests: int = DEFAULT_REQUESTS_PER_BATCH,
    max_bytes: int = DEFAULT_BYTES_PER_BATCH,
) -> Dict[str, Any]:
    """Create the batch(es); the manifest is rewritten after *each* creation.

    If a later ``create`` raises, the batches already created (and billed) are
    on disk in the manifest, which is written first with ``batches: []`` so that
    a crash can never leave a created batch unrecorded by more than one call.
    """
    # Plain dicts in the wire shape of the SDK's ``Request`` /
    # ``MessageCreateParamsNonStreaming`` TypedDicts: {custom_id, params}.
    requests: List[Dict[str, Any]] = [
        {
            "custom_id": req.custom_id,
            "params": build_request_params(req, spec, effort, cache),
        }
        for req in plan.requests
    ]
    groups = split_batches(requests, max_requests, max_bytes)
    write_json(manifest_path, manifest)
    for group in groups:
        batch = client.messages.batches.create(requests=group)
        manifest["batches"].append(
            {
                "id": batch.id,
                "created_at": _now(),
                "request_count": len(group),
                "custom_ids": [r["custom_id"] for r in group],
            }
        )
        write_json(manifest_path, manifest)
    return manifest


# --------------------------------------------------------------------------
# Collect: validation and merge
# --------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*)\n```\s*$", re.DOTALL)


def validate_payload(
    payload: Any, first_line: int, last_line: int
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """Check one chunk answer against ``LABEL_SCHEMA`` and the chunk's range.

    Returns ``(labels, amends, problems)``. Any problem invalidates the chunk:
    the labels are gold, so a response that breaks the contract is reported, not
    repaired.
    """
    problems: List[str] = []
    if not isinstance(payload, dict):
        return [], [], ["payload is not an object"]
    extra = set(payload) - {"labels", "amends"}
    if extra:
        problems.append(f"unexpected keys: {sorted(extra)}")
    raw_labels = payload.get("labels")
    raw_amends = payload.get("amends")
    if not isinstance(raw_labels, list):
        problems.append("labels is not an array")
        raw_labels = []
    if not isinstance(raw_amends, list):
        problems.append("amends is not an array")
        raw_amends = []

    labels: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for i, raw in enumerate(raw_labels):
        where = f"labels[{i}]"
        if not isinstance(raw, dict) or set(raw) != {
            "line",
            "category",
            "number",
            "quoted",
        }:
            problems.append(f"{where}: wrong shape")
            continue
        line, category = raw["line"], raw["category"]
        number, quoted = raw["number"], raw["quoted"]
        if isinstance(line, bool) or not isinstance(line, int):
            problems.append(f"{where}: line is not an integer")
            continue
        if category not in CATEGORIES:
            problems.append(f"{where}: unknown category {category!r}")
            continue
        if number is not None and not isinstance(number, str):
            problems.append(f"{where}: number is not a string or null")
            continue
        if not isinstance(quoted, bool):
            problems.append(f"{where}: quoted is not a boolean")
            continue
        if not (first_line <= line <= last_line):
            problems.append(
                f"{where}: line {line} outside owned range {first_line}-{last_line}"
            )
            continue
        if line in seen:
            problems.append(f"{where}: duplicate line {line}")
            continue
        seen.add(line)
        if category not in NUMBERED_CATEGORIES:
            number = None
        elif number is not None:
            number = number.strip() or None
        labels.append(
            {"line": line, "category": category, "number": number, "quoted": quoted}
        )

    amends: List[Dict[str, Any]] = []
    for i, raw in enumerate(raw_amends):
        where = f"amends[{i}]"
        if not isinstance(raw, dict) or set(raw) != {
            "action",
            "tipo",
            "numero",
            "ano",
        }:
            problems.append(f"{where}: wrong shape")
            continue
        action, tipo, numero, ano = (
            raw["action"],
            raw["tipo"],
            raw["numero"],
            raw["ano"],
        )
        if action not in AMEND_ACTIONS:
            problems.append(f"{where}: unknown action {action!r}")
            continue
        if not isinstance(tipo, str) or not tipo.strip():
            problems.append(f"{where}: tipo is not a non-empty string")
            continue
        if numero is not None and not isinstance(numero, str):
            problems.append(f"{where}: numero is not a string or null")
            continue
        if ano is not None and (isinstance(ano, bool) or not isinstance(ano, int)):
            problems.append(f"{where}: ano is not an integer or null")
            continue
        amends.append(
            {
                "action": action,
                "tipo": tipo.strip().lower(),
                "numero": (numero.strip() or None) if numero else None,
                "ano": ano,
            }
        )
    labels.sort(key=lambda label: label["line"])
    return labels, amends, problems


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _usage_dict(usage: Any) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for name in (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ):
        value = _get(usage, name)
        out[name] = int(value) if isinstance(value, int) else 0
    return out


@dataclass
class ChunkOutcome:
    custom_id: str
    ok: bool
    reason: Optional[str] = None
    detail: Optional[str] = None
    stop_reason: Optional[str] = None
    labels: List[Dict[str, Any]] = field(default_factory=list)
    amends: List[Dict[str, Any]] = field(default_factory=list)
    usage: Dict[str, int] = field(default_factory=dict)


def interpret_result(entry: Any, request_meta: Dict[str, Any]) -> ChunkOutcome:
    """Turn one batch result line into labels or an explicit failure reason."""
    custom_id = str(_get(entry, "custom_id"))
    result = _get(entry, "result")
    result_type = _get(result, "type")
    if result_type != "succeeded":
        error = _get(result, "error")
        detail = None
        if error is not None:
            inner = _get(error, "error", error)
            detail = f"{_get(inner, 'type')}: {_get(inner, 'message')}"
        return ChunkOutcome(custom_id, False, f"result_{result_type}", detail)
    message = _get(result, "message")
    usage = _usage_dict(_get(message, "usage"))
    stop_reason = _get(message, "stop_reason")
    outcome = ChunkOutcome(custom_id, False, stop_reason=stop_reason, usage=usage)
    if stop_reason != "end_turn":
        # max_tokens = truncated JSON; refusal = no schema guarantee. Never parse.
        outcome.reason = f"stop_reason_{stop_reason}"
        return outcome
    text = next(
        (
            _get(block, "text")
            for block in (_get(message, "content") or [])
            if _get(block, "type") == "text"
        ),
        None,
    )
    if not isinstance(text, str) or not text.strip():
        outcome.reason = "no_text_block"
        return outcome
    body = text.strip()
    fenced = _FENCE_RE.match(body)
    if fenced:
        body = fenced.group(1)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        outcome.reason = "invalid_json"
        outcome.detail = str(exc)
        return outcome
    labels, amends, problems = validate_payload(
        payload, int(request_meta["first_line"]), int(request_meta["last_line"])
    )
    if problems:
        outcome.reason = "schema_violation"
        outcome.detail = "; ".join(problems[:5])
        return outcome
    outcome.ok = True
    outcome.labels = labels
    outcome.amends = amends
    return outcome


def merge_chunks(
    outcomes: Sequence[ChunkOutcome], chunk_indexes: Sequence[int]
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Deterministic merge: owned ranges are disjoint and ordered, so labels are
    concatenated in chunk order; ``amends`` is the ordered union."""
    ordered = [o for _, o in sorted(zip(chunk_indexes, outcomes), key=lambda p: p[0])]
    labels: List[Dict[str, Any]] = []
    amends: List[Dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for outcome in ordered:
        labels.extend(outcome.labels)
        for amend in outcome.amends:
            ident = (amend["action"], amend["tipo"], amend["numero"], amend["ano"])
            if ident not in seen:
                seen.add(ident)
                amends.append(amend)
    lines = [label["line"] for label in labels]
    if lines != sorted(set(lines)):
        raise TeacherBatchError("merged labels are not strictly increasing by line")
    return labels, amends


def measured_cost_usd(usage: Dict[str, int], spec: ModelSpec, cache_1h: bool) -> float:
    """Cost of the usage actually reported by the API, at batch prices."""
    in_price = spec.input_usd_mtok * BATCH_DISCOUNT / 1e6
    out_price = spec.output_usd_mtok * BATCH_DISCOUNT / 1e6
    write_mult = CACHE_WRITE_1H_MULT if cache_1h else CACHE_WRITE_5M_MULT
    return round(
        usage.get("input_tokens", 0) * in_price
        + usage.get("cache_creation_input_tokens", 0) * in_price * write_mult
        + usage.get("cache_read_input_tokens", 0) * in_price * spec.cache_read_mult
        + usage.get("output_tokens", 0) * out_price,
        6,
    )


def batches_status(client: Any, manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for batch in manifest["batches"]:
        current = client.messages.batches.retrieve(batch["id"])
        counts = _get(current, "request_counts")
        out.append(
            {
                "id": batch["id"],
                "processing_status": _get(current, "processing_status"),
                "request_counts": {
                    name: _get(counts, name, 0)
                    for name in (
                        "processing",
                        "succeeded",
                        "errored",
                        "canceled",
                        "expired",
                    )
                },
            }
        )
    return out


def wait_for_batches(
    client: Any,
    manifest: Dict[str, Any],
    wait_minutes: float,
    *,
    poll_seconds: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[bool, List[Dict[str, Any]]]:
    """Poll until every batch has ``processing_status == "ended"`` or time is up."""
    deadline = clock() + wait_minutes * 60.0
    while True:
        status = batches_status(client, manifest)
        if all(s["processing_status"] == "ended" for s in status):
            return True, status
        if clock() >= deadline:
            return False, status
        sleep(poll_seconds)


def collect_results(
    client: Any, manifest: Dict[str, Any], out_dir: Path
) -> Dict[str, Any]:
    """Fetch, validate, merge and write. Assumes every batch has ended."""
    spec = resolve_model(manifest["model"])
    requests: Dict[str, Dict[str, Any]] = manifest["requests"]
    submitted = {cid for b in manifest["batches"] for cid in b["custom_ids"]}
    outcomes: Dict[str, ChunkOutcome] = {}
    unknown_ids: List[str] = []
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for batch in manifest["batches"]:
        with (raw_dir / f"{batch['id']}.jsonl").open("w", encoding="utf-8") as raw:
            # Results come in any order: always key by custom_id.
            for entry in client.messages.batches.results(batch["id"]):
                dumped = entry.to_dict() if hasattr(entry, "to_dict") else entry
                raw.write(json.dumps(dumped, ensure_ascii=False, default=str) + "\n")
                custom_id = str(_get(entry, "custom_id"))
                meta = requests.get(custom_id)
                if meta is None:
                    unknown_ids.append(custom_id)
                    continue
                outcomes[custom_id] = interpret_result(entry, meta)

    by_norm: Dict[tuple[str, str], List[str]] = {}
    for custom_id, meta in requests.items():
        by_norm.setdefault((meta["item"], meta["uuid5"]), []).append(custom_id)

    provenance = {
        "label_set": manifest.get("label_set", DEFAULT_LABEL_SET),
        "model": manifest["model"],
        "effort": manifest.get("effort"),
        "prompt_version": manifest["prompt_version"],
        "prompt_sha256": manifest["prompt_sha256"],
        "label_schema_version": manifest["label_schema_version"],
        "git_sha": manifest.get("git_sha"),
        "collected_git_sha": git_sha(),
        "batch_ids": [b["id"] for b in manifest["batches"]],
    }
    usage_total = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    for outcome in outcomes.values():
        for name, value in outcome.usage.items():
            usage_total[name] = usage_total.get(name, 0) + value

    failures: List[Dict[str, Any]] = []
    reasons: Dict[str, int] = {}
    labels_written = 0
    norms_ok = 0
    category_counts: Dict[str, int] = {}
    labels_dir = out_dir / "labels"
    for (item, uuid5), custom_ids in sorted(by_norm.items()):
        custom_ids.sort(key=lambda cid: int(requests[cid]["chunk"]))
        first = requests[custom_ids[0]]
        chunk_problems: List[Dict[str, Any]] = []
        for cid in custom_ids:
            found = outcomes.get(cid)
            if found is None:
                reason = "not_submitted" if cid not in submitted else "missing_result"
                chunk_problems.append({"custom_id": cid, "reason": reason})
            elif not found.ok:
                chunk_problems.append(
                    {
                        "custom_id": cid,
                        "reason": str(found.reason),
                        "detail": found.detail,
                        "stop_reason": found.stop_reason,
                    }
                )
        if chunk_problems:
            for problem in chunk_problems:
                why = str(problem["reason"])
                reasons[why] = reasons.get(why, 0) + 1
            failures.append(
                {
                    "key": f"{item}/{uuid5}",
                    "item": item,
                    "uuid5": uuid5,
                    "tipo": first["tipo"],
                    "numero": first["numero"],
                    "chunks": len(custom_ids),
                    "problems": chunk_problems,
                }
            )
            continue
        labels, amends = merge_chunks(
            [outcomes[cid] for cid in custom_ids],
            [int(requests[cid]["chunk"]) for cid in custom_ids],
        )
        header = {
            "record": "norm",
            "ente": manifest["ente"],
            "fonte": first["fonte"],
            "item": item,
            "uuid5": uuid5,
            "tipo": first["tipo"],
            "numero": first["numero"],
            "txt_name": first["txt_name"],
            "text_sha256": first["text_sha256"],
            "n_lines": first["n_lines"],
            "chunks": len(custom_ids),
            "n_labels": len(labels),
            "amends": amends,
            **provenance,
        }
        path = (
            labels_dir
            / item
            / f"{first['tipo']}-{int(first['numero']):05d}_{uuid5}.jsonl"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(header, ensure_ascii=False) + "\n")
            for label in labels:
                fh.write(
                    json.dumps({"record": "label", **label}, ensure_ascii=False) + "\n"
                )
                category_counts[label["category"]] = (
                    category_counts.get(label["category"], 0) + 1
                )
        norms_ok += 1
        labels_written += len(labels)

    with (out_dir / "failures.jsonl").open("w", encoding="utf-8") as fh:
        for failure in failures:
            fh.write(json.dumps(failure, ensure_ascii=False) + "\n")

    measured = measured_cost_usd(
        usage_total, spec, cache_1h=bool(manifest.get("prompt_cache"))
    )
    answered = len(outcomes)
    summary = {
        **provenance,
        "collected_at": _now(),
        "ente": manifest["ente"],
        "norms_total": len(by_norm),
        "norms_ok": norms_ok,
        "norms_failed": len(failures),
        "requests_total": len(requests),
        "requests_with_result": answered,
        "unknown_custom_ids": sorted(unknown_ids),
        "labels": labels_written,
        "labels_by_category": dict(sorted(category_counts.items())),
        "failure_reasons": dict(sorted(reasons.items())),
        "usage": usage_total,
        "measured_usd": measured,
        "measured_usd_per_request": round(measured / answered, 6) if answered else None,
        "estimate": manifest.get("estimate"),
        "sources": manifest.get("sources", {}),
        "not_labelled_at_submit": {
            "enumeration_errors": manifest.get("enumeration_errors", []),
            "fetch_failed": manifest.get("fetch_failed", []),
            "empty": manifest.get("empty", []),
        },
    }
    write_json(out_dir / "summary.json", summary)
    write_json(out_dir / "manifest.json", manifest)
    return summary


# --------------------------------------------------------------------------
# Optional publication to the Internet Archive
# --------------------------------------------------------------------------


def ia_identifier(ente: str, revision: str, label_set: str = DEFAULT_LABEL_SET) -> str:
    """Immutable item per collection run — never overwrites an earlier one
    (same rule as dataset releases, issue #175). Label sets other than ``main``
    get their own name in the identifier, so they cannot be mistaken for it."""
    if label_set == DEFAULT_LABEL_SET:
        return f"leizilla-teacher-labels-{ente.lower()}-{revision}"
    return f"leizilla-teacher-labels-{ente.lower()}-{label_set}-{revision}"


def upload_to_ia(
    out_dir: Path, summary: Dict[str, Any], revision: Optional[str] = None
) -> Dict[str, Any]:
    """Upload ``labels/`` (one tar.gz), ``failures.jsonl``, ``summary.json`` and
    the manifest as one IA data item, through the same ``ia upload`` wrapper
    (pacing, retry, credentials) the rest of the pipeline uses."""
    ente = str(summary["ente"])
    label_set = str(summary.get("label_set", DEFAULT_LABEL_SET))
    effective_revision = revision or datetime.now(tz=timezone.utc).strftime(
        "%Y%m%dt%H%M%Sz"
    )
    ia_id = ia_identifier(ente, effective_revision, label_set)
    set_suffix = "" if label_set == DEFAULT_LABEL_SET else f" [{label_set}]"
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "labels.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(out_dir / "labels", arcname="labels")
        description = (
            f"Rótulos estruturais por linha (gold de professor, revisão "
            f"{effective_revision}, conjunto {label_set}) de normas do ente "
            f"{ente.upper()}, gerados "
            f"pelo projeto Leizilla sobre o texto OCR do Internet Archive. "
            f"{summary['norms_ok']} normas, {summary['labels']} rótulos. "
            f"Proveniência completa em summary.json."
        )
        args = [
            "ia",
            "upload",
            ia_id,
            str(archive),
            str(out_dir / "failures.jsonl"),
            str(out_dir / "summary.json"),
            str(out_dir / "manifest.json"),
            "--metadata",
            f"title:Leizilla Teacher Labels {ente.upper()}{set_suffix} "
            f"({effective_revision})",
            "--metadata",
            "mediatype:data",
            "--metadata",
            f"subject:leis;leizilla;{ente};labels;gold;{label_set}",
            "--metadata",
            "creator:leizilla-teacher-batch",
            "--metadata",
            "language:pt",
            "--metadata",
            f"description:{description}",
        ]
        try:
            publisher.InternetArchivePublisher()._run_ia_upload(args)
        except FileNotFoundError:
            return {
                "success": False,
                "ia_id": ia_id,
                "error": "ia CLI não encontrado — instale 'internetarchive'",
            }
        except subprocess.CalledProcessError as exc:
            return {"success": False, "ia_id": ia_id, "error": exc.stderr}
    return {"success": True, "ia_id": ia_id}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Teacher-labelling batch pipeline: plan → submit → collect.",
)


def _client() -> Any:
    import anthropic

    return anthropic.Anthropic()


def _split_csv(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()] or None


def _read_failure_keys(path: Optional[Path]) -> Optional[List[str]]:
    if path is None:
        return None
    keys = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            keys.append(str(json.loads(line)["key"]))
    return keys


def _prepare(
    *,
    ente: str,
    fonte: str,
    tipo: Optional[str],
    limit: Optional[int],
    shuffle_seed: Optional[str],
    cache_dir: Optional[Path],
    retry_failures: Optional[Path],
    max_lines: int,
    max_chars: int,
    max_tokens_cap: int,
    fetch_delay: float,
    text_source: str = "ia",
    textos: Optional[Path] = None,
    exclude_labelled: Optional[str] = None,
) -> Plan:
    if text_source not in TEXT_SOURCES:
        raise TeacherBatchError(f"text_source must be one of {', '.join(TEXT_SOURCES)}")
    labelled = load_label_index(exclude_labelled) if exclude_labelled else None
    only_keys = _read_failure_keys(retry_failures)
    if text_source == "textos":
        corpus = _load_textos_corpus(textos)
        texts = {r.ref.key: r for r in corpus.records}
        # Exclusion happens before --limit, so a pilot limit counts new norms.
        pool: List[NormRef] = []
        pre_excluded: List[str] = []
        for record in corpus.records:
            status = label_status(record.ref.ident, record.text_sha256, labelled)
            if status == "excluded":
                pre_excluded.append(record.ref.key)
            else:
                pool.append(record.ref)
        norms = select_norms(
            pool, limit=limit, shuffle_seed=shuffle_seed, only_keys=only_keys
        )
        typer.echo(
            f"{len(corpus.records)} texts in textos.parquet"
            + (f", skipped {corpus.skipped}" if corpus.skipped else "")
            + f"; {len(norms)} selected"
        )

        def load_textos_text(ref: NormRef) -> Optional[str]:
            return texts[ref.key].text

        plan = build_plan(
            norms,
            load_textos_text,
            max_lines=max_lines,
            max_chars=max_chars,
            max_tokens_cap=max_tokens_cap,
            labelled=labelled,
        )
        plan.available = len(corpus.records)
        plan.labelled_excluded = pre_excluded + plan.labelled_excluded
        plan.ocr_motor = {ref.key: texts[ref.key].ocr_motor for ref in plan.norms}
        plan.sources = {
            "text_source": "textos",
            "textos": {
                "file_sha256": corpus.file_sha256,
                "texts": len(corpus.records),
                "skipped": corpus.skipped,
            },
        }
    else:
        enumeration = enumerate_norms(ente, _split_csv(fonte) or [], _split_csv(tipo))
        norms = select_norms(
            enumeration.norms,
            limit=limit,
            shuffle_seed=shuffle_seed,
            only_keys=only_keys,
        )
        typer.echo(
            f"{len(enumeration.norms)} norms with OCR text found, {len(norms)} selected"
        )

        def load(ref: NormRef) -> Optional[str]:
            cached = (
                cache_dir is not None
                and (cache_dir / ref.item / ref.txt_name).is_file()
            )
            text = fetch_text(ref, cache_dir)
            if not cached and fetch_delay > 0:
                time.sleep(fetch_delay)
            return text

        # ia: the text must be fetched to compare its sha256, so exclusion runs
        # after the fetch and only the selected norms are downloaded.
        plan = build_plan(
            norms,
            load,
            max_lines=max_lines,
            max_chars=max_chars,
            max_tokens_cap=max_tokens_cap,
            labelled=labelled,
        )
        plan.enumeration_errors = list(enumeration.errors)
        plan.available = len(enumeration.norms)
        plan.sources = {"text_source": "ia"}
    if labelled is not None:
        plan.sources["exclude_labelled"] = {
            "source": exclude_labelled,
            "labelled_norms": len(labelled),
            "labelled_texts": sum(len(s) for s in labelled.values()),
        }
    return plan


def _load_textos_corpus(path: Optional[Path]) -> TextosCorpus:
    """Local ``--textos`` parquet, or the published one downloaded to a temp dir."""
    if path is not None:
        return load_textos(path)
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "textos.parquet"
        _download_to(DEFAULT_TEXTOS_URL, local)
        return load_textos(local)


def _selection_breakdown(plan: Plan) -> Dict[str, Any]:
    """Counts of the selected norms by status, tipo and OCR motor."""
    by_status: Dict[str, int] = {}
    by_tipo: Dict[str, int] = {}
    by_motor: Dict[str, int] = {}
    for ref in plan.norms:
        status = plan.status.get(ref.key, "all")
        by_status[status] = by_status.get(status, 0) + 1
        by_tipo[ref.tipo] = by_tipo.get(ref.tipo, 0) + 1
        # textos: the motor recorded per row (None = not recorded). ia: no motor,
        # the text is the IA's own _djvu.txt.
        if plan.sources.get("text_source") == "ia":
            motor = "ia-djvu"
        else:
            motor = plan.ocr_motor.get(ref.key) or "(not recorded)"
        by_motor[motor] = by_motor.get(motor, 0) + 1
    return {
        "by_status": dict(sorted(by_status.items())),
        "by_tipo": dict(sorted(by_tipo.items())),
        "by_ocr_motor": dict(sorted(by_motor.items())),
    }


def _echo_selection(plan: Plan) -> None:
    breakdown = _selection_breakdown(plan)
    if plan.status:
        status = breakdown["by_status"]
        split = (
            f" (new norms {status.get('new_norm', 0)}, new texts of labelled norms "
            f"{status.get('new_text', 0)})"
        )
    else:
        split = ""
    typer.echo(
        f"texts available: {plan.available}; excluded as labelled: "
        f"{len(plan.labelled_excluded)}; selected: {len(plan.norms)}{split}"
    )
    typer.echo(f"selected by tipo: {breakdown['by_tipo']}")
    typer.echo(f"selected by ocr_motor: {breakdown['by_ocr_motor']}")


def _echo_estimate(estimate: CostEstimate) -> None:
    effort = f" effort={estimate.effort}" if estimate.effort else ""
    typer.echo(
        f"{estimate.model}{effort}: {estimate.norms} norms, {estimate.requests} "
        f"requests, ~{estimate.input_tokens:,} input tok, "
        f"~{estimate.estimated_output_tokens:,} output tok "
        f"(ceiling {estimate.ceiling_output_tokens:,}) → "
        f"estimate US${estimate.estimate_usd:.2f}, ceiling US${estimate.ceiling_usd:.2f}"
    )


def _echo_gaps(plan: Plan) -> None:
    for label, values in (
        ("enumeration errors", plan.enumeration_errors),
        ("texts not fetched", plan.fetch_failed),
        ("empty texts", plan.empty),
    ):
        if values:
            typer.echo(f"WARNING {len(values)} {label}: {values[:5]}", err=True)


_ENTE = typer.Option("ro", "--ente", help="Ente federativo.")
_FONTE = typer.Option("casacivil", "--fonte", help="Fonte(s), separadas por vírgula.")
_TIPO = typer.Option(
    None, "--tipo", help="Filtrar por tipo(s) (lei, lc, decreto, ...), por vírgula."
)
_LIMIT = typer.Option(None, "--limit", help="Máximo de normas (piloto).")
_SEED = typer.Option(
    None,
    "--shuffle-seed",
    help="Ordena as normas por hash(seed|chave) antes do --limit: amostra "
    "reprodutível espalhada pelos itens.",
)
_CACHE_DIR = typer.Option(
    None, "--cache-dir", help="Cache local dos _djvu.txt baixados."
)
_MAX_LINES = typer.Option(DEFAULT_MAX_LINES, "--max-lines")
_MAX_CHARS = typer.Option(DEFAULT_MAX_CHARS, "--max-chars")
_MAX_TOKENS_CAP = typer.Option(MAX_TOKENS_CAP, "--max-tokens-cap")
_FETCH_DELAY = typer.Option(0.4, "--fetch-delay", help="Segundos entre downloads.")
_EFFORT = typer.Option("medium", "--effort", help="|".join(EFFORTS))
_CACHE = typer.Option(
    True, "--prompt-cache/--no-prompt-cache", help="Cache de 1h do prefixo."
)
_TEXT_SOURCE = typer.Option(
    "ia",
    "--text-source",
    help="ia: um _djvu.txt por norma no IA (lento). textos: o parquet publicado "
    "(--textos, ou baixado do IA).",
)
_TEXTOS = typer.Option(
    None,
    "--textos",
    help="textos.parquet local (com --text-source textos). Vazio = baixa o publicado.",
)
_EXCLUDE_LABELLED = typer.Option(
    None,
    "--exclude-labelled",
    help="Pula normas já rotuladas com o mesmo texto (mesma identidade e sha256). "
    "Diretório local de rótulos ou item do IA com labels.tar.gz.",
)
_LABEL_SET = typer.Option(
    DEFAULT_LABEL_SET,
    "--label-set",
    help="Nome do conjunto de rótulos (main = conjunto de ajuste; outro nome = "
    "conjunto separado, ex. holdout-2026-11).",
)


def _check_effort(effort: str) -> None:
    if effort not in EFFORTS:
        raise typer.BadParameter(f"effort must be one of {', '.join(EFFORTS)}")


@app.command()
def plan(
    ente: str = _ENTE,
    fonte: str = _FONTE,
    tipo: Optional[str] = _TIPO,
    limit: Optional[int] = _LIMIT,
    shuffle_seed: Optional[str] = _SEED,
    cache_dir: Optional[Path] = _CACHE_DIR,
    model: Optional[str] = typer.Option(
        None, "--model", help="Só este modelo (padrão: todos os conhecidos)."
    ),
    effort: str = _EFFORT,
    prompt_cache: bool = _CACHE,
    count_sample: int = typer.Option(
        0,
        "--count-sample",
        help="Mede tokens reais de N requisições com a API de contagem de "
        "tokens (gratuita; exige ANTHROPIC_API_KEY).",
    ),
    out: Optional[Path] = typer.Option(None, "--out", help="Grava o plano em JSON."),
    max_lines: int = _MAX_LINES,
    max_chars: int = _MAX_CHARS,
    max_tokens_cap: int = _MAX_TOKENS_CAP,
    fetch_delay: float = _FETCH_DELAY,
    text_source: str = _TEXT_SOURCE,
    textos: Optional[Path] = _TEXTOS,
    exclude_labelled: Optional[str] = _EXCLUDE_LABELLED,
    label_set: str = _LABEL_SET,
) -> None:
    """Enumera as entradas e estima o custo por modelo. Não envia nada pago."""
    _check_effort(effort)
    try:
        specs = [resolve_model(model)] if model else list(MODELS.values())
        check_label_set(label_set)
        built = _prepare(
            ente=ente,
            fonte=fonte,
            tipo=tipo,
            limit=limit,
            shuffle_seed=shuffle_seed,
            cache_dir=cache_dir,
            retry_failures=None,
            max_lines=max_lines,
            max_chars=max_chars,
            max_tokens_cap=max_tokens_cap,
            fetch_delay=fetch_delay,
            text_source=text_source,
            textos=textos,
            exclude_labelled=exclude_labelled,
        )
    except TeacherBatchError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    _echo_selection(built)
    _echo_gaps(built)
    estimates = [estimate_cost(built, spec, effort, prompt_cache) for spec in specs]
    for estimate in estimates:
        _echo_estimate(estimate)
    measured: List[Dict[str, Any]] = []
    if count_sample > 0:
        client = _client()
        for spec in specs:
            sample = count_tokens_sample(client, built, spec, effort, count_sample)
            if sample:
                measured.append(sample)
                typer.echo(
                    f"{spec.model}: measured {sample['measured_chars_per_token']} "
                    f"chars/token on {sample['sampled_requests']} requests "
                    f"(estimate assumes {CHARS_PER_TOKEN})"
                )
    if out is not None:
        write_json(
            out,
            {
                "created_at": _now(),
                "ente": ente,
                "label_set": label_set,
                "text_source": text_source,
                "sources": built.sources,
                "texts_available": built.available,
                "excluded_as_labelled": len(built.labelled_excluded),
                "selection": _selection_breakdown(built),
                "prompt_version": PROMPT_VERSION,
                "prompt_sha256": prompt_sha256(),
                "git_sha": git_sha(),
                "estimates": [e.to_dict() for e in estimates],
                "token_count_samples": measured,
                "enumeration_errors": built.enumeration_errors,
                "fetch_failed": built.fetch_failed,
                "empty": built.empty,
            },
        )


@app.command()
def submit(
    max_usd: float = typer.Option(
        ...,
        "--max-usd",
        help="Teto de custo em US$ (obrigatório, sem padrão). Acima dele nada "
        "é enviado.",
    ),
    manifest_path: Path = typer.Option(
        ..., "--manifest", help="Onde gravar o manifesto do envio."
    ),
    model: str = typer.Option(DEFAULT_MODEL, "--model"),
    guard: str = typer.Option(
        "ceiling",
        "--guard",
        help="ceiling: compara --max-usd com o limite superior (todas as "
        "requisições gastando max_tokens). estimate: compara com a estimativa "
        "conservadora — escolha explícita para modelos mais caros.",
    ),
    ente: str = _ENTE,
    fonte: str = _FONTE,
    tipo: Optional[str] = _TIPO,
    limit: Optional[int] = _LIMIT,
    shuffle_seed: Optional[str] = _SEED,
    cache_dir: Optional[Path] = _CACHE_DIR,
    effort: str = _EFFORT,
    prompt_cache: bool = _CACHE,
    retry_failures: Optional[Path] = typer.Option(
        None,
        "--retry-failures",
        help="failures.jsonl de um collect anterior: reenvia só essas normas.",
    ),
    allow_partial: bool = typer.Option(
        False,
        "--allow-partial",
        help="Envia mesmo com erros de enumeração ou textos não baixados.",
    ),
    max_lines: int = _MAX_LINES,
    max_chars: int = _MAX_CHARS,
    max_tokens_cap: int = _MAX_TOKENS_CAP,
    fetch_delay: float = _FETCH_DELAY,
    text_source: str = _TEXT_SOURCE,
    textos: Optional[Path] = _TEXTOS,
    exclude_labelled: Optional[str] = _EXCLUDE_LABELLED,
    label_set: str = _LABEL_SET,
) -> None:
    """Cria o(s) batch(es) depois da trava de custo e grava o manifesto."""
    _check_effort(effort)
    try:
        spec = resolve_model(model)
        check_label_set(label_set)
        if manifest_path.exists():
            raise TeacherBatchError(
                f"{manifest_path} already exists: a submit may already have "
                "created (billed) batches. Collect it or choose another path."
            )
        built = _prepare(
            ente=ente,
            fonte=fonte,
            tipo=tipo,
            limit=limit,
            shuffle_seed=shuffle_seed,
            cache_dir=cache_dir,
            retry_failures=retry_failures,
            max_lines=max_lines,
            max_chars=max_chars,
            max_tokens_cap=max_tokens_cap,
            fetch_delay=fetch_delay,
            text_source=text_source,
            textos=textos,
            exclude_labelled=exclude_labelled,
        )
        _echo_selection(built)
        _echo_gaps(built)
        if not built.requests:
            raise TeacherBatchError("no requests to submit")
        if (built.enumeration_errors or built.fetch_failed) and not allow_partial:
            raise TeacherBatchError(
                "inputs are incomplete (see warnings). Re-run, or pass "
                "--allow-partial to label what was fetched."
            )
        estimate = estimate_cost(built, spec, effort, prompt_cache)
        _echo_estimate(estimate)
        check_cost_guard(estimate, spec, max_usd, guard)
        manifest = build_manifest(
            built,
            estimate,
            ente=ente,
            effort=estimate.effort,
            cache=prompt_cache,
            max_usd=max_usd,
            guard=guard,
            label_set=label_set,
        )
        submit_batches(
            _client(),
            built,
            spec,
            manifest,
            manifest_path,
            effort=effort,
            cache=prompt_cache,
        )
    except TeacherBatchError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    for batch in manifest["batches"]:
        typer.echo(f"batch {batch['id']}: {batch['request_count']} requests")
    typer.echo(f"manifest: {manifest_path}")


@app.command()
def collect(
    manifest_path: Path = typer.Option(..., "--manifest"),
    out_dir: Path = typer.Option(..., "--out-dir"),
    wait_minutes: float = typer.Option(
        0.0, "--wait-minutes", help="Espera até N minutos pelos batches."
    ),
    upload_ia: bool = typer.Option(
        False, "--upload-ia", help="Publica o resultado num item do IA."
    ),
    allow_failures: bool = typer.Option(
        False,
        "--allow-failures",
        help="Sai com 0 mesmo havendo normas com falha (elas ficam em "
        "failures.jsonl de qualquer forma).",
    ),
    label_set: Optional[str] = typer.Option(
        None,
        "--label-set",
        help="Conjunto esperado. Se informado e diferente do manifesto, nada é "
        "coletado (evita publicar um holdout como se fosse o conjunto principal).",
    ),
) -> None:
    """Busca os resultados, valida, funde os pedaços e grava um JSONL por norma.

    Códigos de saída: 0 ok; 3 batches ainda em processamento (rode de novo mais
    tarde); 4 concluído com normas em falha; 2 erro.
    """
    try:
        manifest = load_manifest(manifest_path)
        if not manifest["batches"]:
            raise TeacherBatchError("manifest has no batch: nothing was submitted")
        manifest_set = str(manifest.get("label_set", DEFAULT_LABEL_SET))
        if label_set is not None and check_label_set(label_set) != manifest_set:
            raise TeacherBatchError(
                f"--label-set {label_set!r} does not match the manifest's label set "
                f"{manifest_set!r}; nothing was collected."
            )
        client = _client()
        ended, status = wait_for_batches(client, manifest, wait_minutes)
        for entry in status:
            typer.echo(
                f"batch {entry['id']}: {entry['processing_status']} "
                f"{entry['request_counts']}"
            )
        if not ended:
            typer.echo("batches still processing — run collect again later", err=True)
            raise typer.Exit(3)
        summary = collect_results(client, manifest, out_dir)
    except TeacherBatchError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    typer.echo(
        f"{summary['norms_ok']}/{summary['norms_total']} norms labelled, "
        f"{summary['labels']} labels, measured US${summary['measured_usd']:.4f}; "
        f"failures: {summary['failure_reasons'] or 'none'}"
    )
    if upload_ia:
        if summary["norms_ok"] == 0:
            typer.echo("nothing to upload", err=True)
        else:
            result = upload_to_ia(out_dir, summary)
            write_json(out_dir / "ia_upload.json", result)
            typer.echo(f"IA upload: {result}")
            if not result["success"]:
                raise typer.Exit(2)
    if summary["norms_failed"] and not allow_failures:
        raise typer.Exit(4)


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    app()


if __name__ == "__main__":
    main()
