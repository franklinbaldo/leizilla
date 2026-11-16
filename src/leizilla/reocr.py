"""Re-OCR direcionado (ADR-0019): OCR próprio só onde o leitor não fecha.

O texto de ``textos`` vem do OCR do Internet Archive (ADR-0015). Para as normas cujo
texto o leitor de hierarquia (``hierarchy_sequence.read_hierarchy``) não consegue
fechar no nível dos artigos, este módulo baixa o PDF preservado no IA, rasteriza as
páginas (poppler, que respeita ``/Rotate``) e passa as imagens ao Kreuzberg com o
backend PaddleOCR. O texto novo só é aceito por um portão determinístico (sem LLM):
a leitura tem de fechar **e** ter ao menos tantos artigos próprios quanto o texto do
IA. Rejeitado, o texto do IA continua valendo e a tentativa fica registrada.

Cada tentativa é uma linha de ``reocr.parquet`` (aceitas carregam o texto; rejeitadas
não). Nada no IA é apagado ou sobrescrito: a tabela é um dataset à parte
(``leizilla-reocr-{ente}-v{N}-…``) e ``build-textos`` a usa como sobreposição.

O Kreuzberg é pesado e opcional (extra ``reocr``): só é importado dentro de
``ocr_pdf``. Todo o resto do módulo roda sem ele.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from leizilla import publisher, textlayer
from leizilla.hierarchy_sequence import read_hierarchy

logger = logging.getLogger(__name__)

ENGINE = "paddleocr"
#: Modelos que o Kreuzberg 4.10 baixa para o backend PaddleOCR (ONNX): detecção
#: ``v2/det/mobile``, classificador ``v2/cls`` e reconhecimento ``rec/latin``.
ENGINE_VERSION = "onnx-v2 det-mobile+cls+rec-latin"
OCR_LANGUAGE = "pt"
RASTER_DPI = 300
DEFAULT_MAX_PAGES = 40
MIN_SLEEP_S = 1.0
_PDF_TIMEOUT_S = 120

ACEITO = "aceito"
NAO_FECHA = "nao-fecha"
MENOS_ARTIGOS = "menos-artigos"
PDF_DIVERGE = "pdf-sha256-diverge"
EXCEDE_PAGINAS = "excede-max-paginas"
OCR_VAZIO = "ocr-vazio"
OCR_FALHOU = "ocr-falhou"

# Ordem e tipos das colunas de ``reocr.parquet`` (docs/SCHEMA.md §3.5.1).
REOCR_SCHEMA: dict[str, str] = {
    "texto_id": "VARCHAR",
    "ente": "VARCHAR",
    "fonte": "VARCHAR",
    "tipo": "VARCHAR",
    "numero": "INTEGER",
    "ia_item": "VARCHAR",
    "pdf_url": "VARCHAR",
    "sha256_fonte": "VARCHAR",
    "sha256_pdf": "VARCHAR",
    "paginas": "INTEGER",
    "engine": "VARCHAR",
    "engine_version": "VARCHAR",
    "kreuzberg_version": "VARCHAR",
    "parametros": "VARCHAR",
    "aceito": "BOOLEAN",
    "motivo": "VARCHAR",
    "artigos_ia": "INTEGER",
    "artigos_novo": "INTEGER",
    "fecha_ia": "BOOLEAN",
    "fecha_novo": "BOOLEAN",
    "segundos": "DOUBLE",
    "tentado_em": "VARCHAR",
    "sha256_texto": "VARCHAR",
    "num_caracteres": "INTEGER",
    "texto": "VARCHAR",
}

Fetcher = Callable[[str], Optional[bytes]]


class TooManyPages(Exception):
    """O PDF tem mais páginas que ``--max-pages``."""

    def __init__(self, pages: int) -> None:
        super().__init__(f"{pages} páginas")
        self.pages = pages


@dataclass
class OcrOutcome:
    """Resultado do OCR de um PDF: texto das páginas na ordem, e a contagem."""

    text: str
    pages: int
    kreuzberg_version: str


OcrFn = Callable[[bytes, int], OcrOutcome]


@dataclass
class ReocrStats:
    """Contadores de uma execução de re-OCR."""

    #: Linhas de ``textos`` examinadas e as que o leitor não fecha.
    examinadas: int = 0
    nao_fecham: int = 0
    #: Não fecham mas já tentadas com o mesmo PDF + motor (ou grandes demais).
    ja_tentadas: int = 0
    na_fila: int = 0
    tentadas: int = 0
    aceitas: int = 0
    rejeitadas: int = 0
    grandes: int = 0
    failures: list[str] = field(default_factory=list)
    truncated: bool = False


# ---------------------------------------------------------------------------
# Leitura e portão
# ---------------------------------------------------------------------------


def read_closure(text: str) -> tuple[bool, int]:
    """``(nível dos artigos fecha, nº de artigos próprios)`` segundo o leitor."""
    report = read_hierarchy(text)
    own = sum(
        1 for n in report["nodes"] if n["kind"] == "artigo" and n["status"] == "own"
    )
    return bool(report["levels"]["artigo"]["closes"]), own


def judge(ia_text: str, new_text: str) -> dict[str, Any]:
    """Portão de aceitação (determinístico, sem LLM).

    Aceita só se a leitura do texto novo fecha **e** tem ao menos tantos artigos
    próprios quanto a do texto do IA. Devolve ``aceito``, ``motivo`` e as medidas.
    """
    fecha_ia, n_ia = read_closure(ia_text)
    fecha_novo, n_novo = read_closure(new_text)
    if not fecha_novo:
        motivo = NAO_FECHA
    elif n_novo < n_ia:
        motivo = MENOS_ARTIGOS
    else:
        motivo = ACEITO
    return {
        "aceito": motivo == ACEITO,
        "motivo": motivo,
        "fecha_ia": fecha_ia,
        "fecha_novo": fecha_novo,
        "artigos_ia": n_ia,
        "artigos_novo": n_novo,
    }


# ---------------------------------------------------------------------------
# Fila
# ---------------------------------------------------------------------------


def attempt_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    """Identidade de uma tentativa: o PDF (sha256 da captura) e o motor usado."""
    return (
        str(row.get("sha256_fonte") or ""),
        str(row.get("engine") or ""),
        str(row.get("engine_version") or ""),
        str(row.get("kreuzberg_version") or ""),
    )


def _already_done(
    row: dict[str, Any],
    done: dict[tuple[str, str, str, str], dict[str, Any]],
    kreuzberg_version: str,
    max_pages: int,
) -> bool:
    prev = done.get(
        (str(row.get("sha256_fonte") or ""), ENGINE, ENGINE_VERSION, kreuzberg_version)
    )
    if prev is None:
        return False
    # Rejeitado por tamanho só deixa de valer se agora o limite o comporta.
    if prev.get("motivo") == EXCEDE_PAGINAS:
        return int(prev.get("paginas") or 0) > max_pages
    return True


def select_queue(
    textos_rows: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    *,
    kreuzberg_version: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    stats: Optional[ReocrStats] = None,
) -> list[dict[str, Any]]:
    """Normas com texto cujo leitor não fecha o nível dos artigos, em ordem estável.

    Entra quem tem texto, ``pdf_url`` e ``sha256_fonte`` e cuja leitura
    (``read_hierarchy``) não fecha. Sai quem já foi tentado com o mesmo PDF e o
    mesmo motor (aceito ou rejeitado). Ordem: ``texto_id``. Cada linha devolvida
    ganha ``_artigos_ia``/``_fecha_ia`` (medidas do texto de entrada).
    """
    stats = stats or ReocrStats()
    done = {attempt_key(a): a for a in attempts}
    queue: list[dict[str, Any]] = []
    for row in sorted(textos_rows, key=lambda r: str(r["texto_id"])):
        text = row.get("texto")
        if not text or not row.get("pdf_url") or not row.get("sha256_fonte"):
            continue
        stats.examinadas += 1
        fecha, n_own = read_closure(str(text))
        if fecha:
            continue
        stats.nao_fecham += 1
        if _already_done(row, done, kreuzberg_version, max_pages):
            stats.ja_tentadas += 1
            continue
        queue.append({**row, "_artigos_ia": n_own, "_fecha_ia": fecha})
    stats.na_fila = len(queue)
    return queue


# ---------------------------------------------------------------------------
# PDF -> páginas -> Kreuzberg/PaddleOCR
# ---------------------------------------------------------------------------


def _require(tool: str) -> str:
    path = shutil.which(tool)
    if path is None:
        raise RuntimeError(f"{tool} não encontrado — instale poppler-utils")
    return path


def pdf_page_count(pdf_path: Path) -> int:
    """Número de páginas via ``pdfinfo`` (poppler)."""
    out = subprocess.run(
        [_require("pdfinfo"), str(pdf_path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.MULTILINE)
    if not m:
        raise RuntimeError("pdfinfo não informou o número de páginas")
    return int(m.group(1))


def rasterize(pdf_path: Path, out_dir: Path, dpi: int = RASTER_DPI) -> list[Path]:
    """Páginas do PDF como PNG em tons de cinza, na ordem, com ``/Rotate`` aplicado.

    O poppler gira a página conforme o atributo ``/Rotate``; o caminho de OCR do
    Kreuzberg não, e lê de cabeça para baixo os PDFs gravados com ``/Rotate 180``.
    """
    subprocess.run(
        [
            _require("pdftoppm"),
            "-r",
            str(dpi),
            "-gray",
            "-png",
            str(pdf_path),
            str(out_dir / "p"),
        ],
        check=True,
        capture_output=True,
        timeout=600,
    )
    return sorted(out_dir.glob("p-*.png"))


def ocr_pdf(pdf_bytes: bytes, max_pages: int = DEFAULT_MAX_PAGES) -> OcrOutcome:
    """OCR de um PDF: poppler rasteriza, Kreuzberg+PaddleOCR lê cada página.

    Levanta ``TooManyPages`` antes de rasterizar se passar de ``max_pages``.
    Importa o Kreuzberg aqui, só quando há o que ler (extra ``reocr``).
    """
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        pdf_path = work / "in.pdf"
        pdf_path.write_bytes(pdf_bytes)
        pages = pdf_page_count(pdf_path)
        if pages > max_pages:
            raise TooManyPages(pages)
        images_dir = work / "img"
        images_dir.mkdir()
        images = rasterize(pdf_path, images_dir)

        import kreuzberg

        config = kreuzberg.ExtractionConfig(
            force_ocr=True,
            use_cache=False,
            ocr=kreuzberg.OcrConfig(backend="paddleocr", language=OCR_LANGUAGE),
        )
        texts = [
            kreuzberg.extract_file_sync(str(img), config=config).content
            for img in images
        ]
        return OcrOutcome(
            text="\n\n".join(t.strip() for t in texts),
            pages=pages,
            kreuzberg_version=str(kreuzberg.__version__),
        )


def installed_kreuzberg_version() -> str:
    """Versão do Kreuzberg instalado (``'ausente'`` sem o extra ``reocr``)."""
    from importlib import metadata

    try:
        return metadata.version("kreuzberg")
    except metadata.PackageNotFoundError:
        return "ausente"


def _params(dpi: int = RASTER_DPI) -> str:
    return (
        f"backend=paddleocr; language={OCR_LANGUAGE}; force_ocr=true; "
        f"rasterizer=pdftoppm -r {dpi} -gray; pages=concat"
    )


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _base_row(
    item: dict[str, Any], kreuzberg_version: str, **extra: Any
) -> dict[str, Any]:
    row: dict[str, Any] = {c: None for c in REOCR_SCHEMA}
    for c in (
        "texto_id",
        "ente",
        "fonte",
        "tipo",
        "numero",
        "ia_item",
        "pdf_url",
        "sha256_fonte",
    ):
        row[c] = item.get(c)
    row.update(
        engine=ENGINE,
        engine_version=ENGINE_VERSION,
        kreuzberg_version=kreuzberg_version,
        parametros=_params(),
        aceito=False,
        tentado_em=_now(),
    )
    row.update(extra)
    return row


def run_reocr(
    queue: list[dict[str, Any]],
    *,
    stats: ReocrStats,
    limit: Optional[int] = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    sleep_s: float = MIN_SLEEP_S,
    fetch: Optional[Fetcher] = None,
    ocr: Optional[OcrFn] = None,
    kreuzberg_version: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Tenta o re-OCR de cada norma da fila; devolve uma linha por tentativa.

    Sequencial e educado com o IA: um download por vez, ``sleep_s`` (>= 1 s) entre
    eles. Falha de download não vira tentativa (é transitória: a norma volta à fila
    na próxima execução); falha do OCR vira rejeição ``ocr-falhou``.
    """
    fetch = fetch or textlayer.http_get
    ocr = ocr or ocr_pdf
    kz_version = kreuzberg_version or installed_kreuzberg_version()
    out: list[dict[str, Any]] = []
    first = True
    for item in queue:
        if limit is not None and len(out) >= limit:
            stats.truncated = True
            break
        if not first:
            time.sleep(max(sleep_s, MIN_SLEEP_S))
        first = False
        tid = str(item["texto_id"])
        pdf = fetch(str(item["pdf_url"]))
        if pdf is None:
            stats.failures.append(f"{tid}: download do PDF falhou")
            continue
        sha_pdf = hashlib.sha256(pdf).hexdigest()
        row = _base_row(
            item,
            kz_version,
            sha256_pdf=sha_pdf,
            artigos_ia=item.get("_artigos_ia"),
            fecha_ia=item.get("_fecha_ia"),
        )
        started = time.monotonic()
        stats.tentadas += 1
        if sha_pdf != item.get("sha256_fonte"):
            row.update(motivo=PDF_DIVERGE)
        else:
            try:
                outcome = ocr(pdf, max_pages)
            except TooManyPages as e:
                stats.grandes += 1
                row.update(motivo=EXCEDE_PAGINAS, paginas=e.pages)
            except Exception:  # noqa: BLE001 — bulkhead por norma; logado abaixo
                logger.exception("re-OCR falhou em %s", tid)
                row.update(motivo=OCR_FALHOU)
            else:
                row.update(paginas=outcome.pages)
                row["kreuzberg_version"] = outcome.kreuzberg_version
                new_text = outcome.text
                if not new_text.strip():
                    row.update(motivo=OCR_VAZIO)
                else:
                    verdict = judge(str(item["texto"]), new_text)
                    row.update(
                        aceito=verdict["aceito"],
                        motivo=verdict["motivo"],
                        fecha_ia=verdict["fecha_ia"],
                        fecha_novo=verdict["fecha_novo"],
                        artigos_ia=verdict["artigos_ia"],
                        artigos_novo=verdict["artigos_novo"],
                        sha256_texto=hashlib.sha256(new_text.encode()).hexdigest(),
                        num_caracteres=len(new_text),
                    )
                    if verdict["aceito"]:
                        row["texto"] = new_text
        row["segundos"] = round(time.monotonic() - started, 2)
        if row["aceito"]:
            stats.aceitas += 1
        else:
            stats.rejeitadas += 1
        out.append(row)
    return out


def merge_attempts(
    previous: list[dict[str, Any]], new: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Histórico + tentativas novas; mesma (norma, PDF, motor) fica com a mais nova."""
    merged: dict[tuple[str, tuple[str, str, str, str]], dict[str, Any]] = {}
    for row in [*previous, *new]:
        merged[(str(row["texto_id"]), attempt_key(row))] = row
    return sorted(
        merged.values(), key=lambda r: (str(r["texto_id"]), str(r["tentado_em"]))
    )


# ---------------------------------------------------------------------------
# Parquet
# ---------------------------------------------------------------------------


def write_reocr_parquet(rows: list[dict[str, Any]], output_path: Path) -> None:
    """Grava ``reocr.parquet`` (ZSTD), ordenado por ``texto_id``."""
    import duckdb

    if not rows:
        raise ValueError("rows is empty — nothing to write")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(REOCR_SCHEMA)
    conn = duckdb.connect()
    try:
        conn.execute(
            "CREATE TABLE reocr ("
            + ", ".join(f"{c} {t}" for c, t in REOCR_SCHEMA.items())
            + ")"
        )
        conn.executemany(
            f"INSERT INTO reocr VALUES ({', '.join('?' for _ in cols)})",
            [[row.get(c) for c in cols] for row in rows],
        )
        target = str(output_path).replace("'", "''")
        conn.execute(
            f"COPY (SELECT * FROM reocr ORDER BY texto_id, tentado_em) TO '{target}' "
            "(FORMAT parquet, COMPRESSION zstd)"
        )
    finally:
        conn.close()


def read_reocr_parquet(path: Path) -> list[dict[str, Any]]:
    """Lê um ``reocr.parquet`` como lista de linhas."""
    import duckdb

    conn = duckdb.connect()
    try:
        cur = conn.execute("SELECT * FROM read_parquet(?)", [str(path)])
        names = [d[0] for d in cur.description or []]
        return [dict(zip(names, values)) for values in cur.fetchall()]
    finally:
        conn.close()


def validate_reocr_parquet(path: Path) -> list[str]:
    """Gate de release de ``reocr`` (lista de violações, vazia se OK)."""
    import duckdb

    conn = duckdb.connect()
    try:
        described = conn.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)])
        actual = {r[0]: r[1] for r in described.fetchall()}
    finally:
        conn.close()
    if actual != REOCR_SCHEMA:
        return [
            "colunas divergem do contrato: "
            f"{sorted(set(actual) ^ set(REOCR_SCHEMA)) or 'tipos'}"
        ]
    problems: list[str] = []
    seen: set[tuple[str, tuple[str, str, str, str]]] = set()
    for row in read_reocr_parquet(path):
        tid = str(row["texto_id"])
        ident = (tid, attempt_key(row))
        if ident in seen:
            problems.append(f"{tid}: tentativa duplicada")
        seen.add(ident)
        if not row["sha256_fonte"] or not row["motivo"]:
            problems.append(f"{tid}: sha256_fonte/motivo ausente")
        if bool(row["aceito"]) != (row["motivo"] == ACEITO):
            problems.append(f"{tid}: aceito incoerente com o motivo")
        text = row["texto"]
        if row["aceito"]:
            if not text or not str(text).strip():
                problems.append(f"{tid}: aceito sem texto")
            elif hashlib.sha256(str(text).encode()).hexdigest() != row["sha256_texto"]:
                problems.append(f"{tid}: sha256_texto não confere com o texto")
        elif text is not None:
            problems.append(f"{tid}: rejeitado não pode carregar texto")
    return problems


def load_accepted(path: Path) -> dict[str, dict[str, Any]]:
    """Re-OCRs aceitos de um ``reocr.parquet``: ``texto_id`` → linha mais recente.

    Fail-open: arquivo ausente ou ilegível devolve ``{}`` (``build-textos`` se
    comporta como sem sobreposição). Linhas cujo texto não confere com o
    ``sha256_texto`` são descartadas.
    """
    try:
        rows = read_reocr_parquet(path)
    except Exception as e:  # noqa: BLE001 — sobreposição é opcional; fail-open
        logger.warning("reocr.parquet ilegível (%s): sem sobreposição — %s", path, e)
        return {}
    accepted: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda r: str(r.get("tentado_em") or "")):
        text = row.get("texto")
        if not row.get("aceito") or not text:
            continue
        if hashlib.sha256(str(text).encode()).hexdigest() != row.get("sha256_texto"):
            logger.warning(
                "reocr: %s com sha256_texto divergente — ignorado", row["texto_id"]
            )
            continue
        accepted[str(row["texto_id"])] = row
    return accepted


def fetch_published_reocr(ente: str, version: int, dest: Path) -> bool:
    """Baixa o ``reocr.parquet`` do ponteiro latest. ``False`` se nunca publicado.

    Erros de rede (≠ 404) levantam ``OSError``: quem chama não deve publicar um
    histórico encolhido por não ter conseguido ler o anterior.
    """
    item = publisher.reocr_item_identifier(ente, version, "latest")
    url = f"https://archive.org/download/{item}/reocr.parquet"
    req = urllib.request.Request(url, headers={"User-Agent": textlayer._USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            dest.write_bytes(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise OSError(f"{url}: HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise OSError(f"{url}: {e}") from e
    return True


def build_reocr_meta(
    parquet_path: Path,
    ente: str,
    version: int,
    revision: str,
    git_sha: Optional[str] = None,
) -> dict[str, Any]:
    """``dataset_meta.json`` do item de ``reocr`` (mesma forma do de ``textos``)."""
    import duckdb

    conn = duckdb.connect()
    try:
        counts = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE aceito) FROM read_parquet(?)",
            [str(parquet_path)],
        ).fetchone() or (0, 0)
    finally:
        conn.close()
    meta: dict[str, Any] = {
        "leizilla_meta_version": "0.1",
        "schema_version": "0.1",
        "ente": ente,
        "version": version,
        "revision": revision,
        "table": "reocr",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "row_count": int(counts[0]),
        "rows_aceitas": int(counts[1]),
        "file_size_bytes": parquet_path.stat().st_size,
        "hash_parquet": (
            f"sha256:{hashlib.sha256(parquet_path.read_bytes()).hexdigest()}"
        ),
    }
    if git_sha:
        meta["git_sha"] = git_sha
    return meta
