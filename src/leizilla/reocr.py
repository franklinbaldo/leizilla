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

Duas filas (ADR-0019, "Fila sem-texto"): ``nao-fecha`` (o que está acima) e
``sem-texto`` (PDF preservado que o IA ainda não derivou, sem linha em ``textos``;
sem texto do IA para comparar, o portão é só "texto não trivial").

O Kreuzberg é pesado e opcional (extra ``reocr``): só é importado dentro de
``ocr_pdf``. Todo o resto do módulo roda sem ele.
"""

from __future__ import annotations

import hashlib
import json
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
import unicodedata
from typing import Any, Callable, Mapping, Optional

from leizilla import publisher, textlayer
from leizilla.defeitos import defeito_de
from leizilla.textlayer import FILA_NAO_FECHA, FILA_SEM_TEXTO, read_closure

logger = logging.getLogger(__name__)

ENGINE = "paddleocr"
#: Motor de uma tentativa da fila ``sem-texto`` que leu a camada de texto embutida do PDF
#: (``pdftotext``, poppler) em vez de rasterizar e rodar OCR. A tentativa só é gravada com
#: esse motor se o texto passou no portão; senão o PDF segue para o OCR e a linha é a do OCR.
PDF_TEXT_ENGINE = "pdftotext"
#: Modelos que o Kreuzberg 4.10 baixa para o backend PaddleOCR (ONNX): detecção
#: ``v2/det/mobile``, classificador ``v2/cls`` e reconhecimento ``rec/latin``.
ENGINE_VERSION = "onnx-v2 det-mobile+cls+rec-latin"
OCR_LANGUAGE = "pt"
RASTER_DPI = 300
DEFAULT_MAX_PAGES = 40
MIN_SLEEP_S = 1.0
_PDF_TIMEOUT_S = 120

#: Piso do portão da fila ``sem-texto``: média de caracteres **não brancos** por
#: página. Nos 25 textos do piloto (PaddleOCR), os textos legíveis ficam em 350 a
#: 2300 por página (mínimo 353; Lei 65, 2 pág., 706 caracteres) e os de página
#: girada/ilegível em 26 a 41. 150 separa os dois grupos com folga para os lados.
MIN_CHARS_POR_PAGINA = 150
FILAS = (FILA_SEM_TEXTO, FILA_NAO_FECHA)
#: Parcela da ``--limit`` reservada à fila ``sem-texto`` (o restante, à ``nao-fecha``).
SEM_TEXTO_PARTE = (2, 3)

ACEITO = "aceito"
TEXTO_TRIVIAL = "texto-trivial"
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
    "fila": "VARCHAR",
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
#: Camada de texto embutida do PDF (sem OCR): ``None`` se não há ou se a ferramenta falha.
TextLayerFn = Callable[[bytes], Optional[OcrOutcome]]


@dataclass
class ReocrStats:
    """Contadores de uma execução de re-OCR."""

    #: Linhas de ``textos`` examinadas e as que o leitor não fecha.
    examinadas: int = 0
    nao_fecham: int = 0
    #: Não fecham mas já tentadas com o mesmo PDF + motor (ou grandes demais).
    ja_tentadas: int = 0
    #: Não fecham por defeito registrado do arquivo oficial (``defeitos-da-fonte.json``).
    defeitos_da_fonte: int = 0
    na_fila: int = 0
    #: Da fila, quantas já leem ao menos 1 artigo próprio no texto do IA (vão primeiro).
    fila_com_artigos: int = 0
    fila_sem_artigos: int = 0
    #: Fila ``sem-texto``: PDFs preservados sem texto (IA nem ``textos``), os já
    #: tentados com o mesmo PDF + motor, e os que sobraram na fila.
    sem_texto_enumeradas: int = 0
    sem_texto_ja_tentadas: int = 0
    sem_texto_na_fila: int = 0
    tentadas: int = 0
    aceitas: int = 0
    rejeitadas: int = 0
    grandes: int = 0
    failures: list[str] = field(default_factory=list)
    truncated: bool = False


# ---------------------------------------------------------------------------
# Leitura e portão
# ---------------------------------------------------------------------------


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


def normalise_ocr(text: str) -> str:
    """Texto do OCR com espaços colapsados e NFC — só para medir, não para guardar."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def judge_sem_texto(new_text: str, pages: int) -> dict[str, Any]:
    """Portão da fila ``sem-texto`` (determinístico, sem LLM).

    Não há texto do IA com que comparar, então o portão não é o da fila
    ``nao-fecha``: o OCR é aceito se, normalizado, tem em média pelo menos
    ``MIN_CHARS_POR_PAGINA`` caracteres não brancos por página. Pega o que o
    motor devolve de uma página girada ou em branco (dezenas de caracteres por
    página). Se o leitor fecha o texto é registrado (``fecha_novo``,
    ``artigos_novo``) mas **não é exigido**: um texto pesquisável que não fecha
    ainda é melhor que nenhum, e aqui nada é substituído.
    """
    compact = re.sub(r"\s+", "", normalise_ocr(new_text))
    per_page = len(compact) / max(pages, 1)
    fecha, own = read_closure(new_text) if compact else (False, 0)
    return {
        "aceito": bool(compact) and per_page >= MIN_CHARS_POR_PAGINA,
        "motivo": (
            OCR_VAZIO
            if not compact
            else ACEITO
            if per_page >= MIN_CHARS_POR_PAGINA
            else TEXTO_TRIVIAL
        ),
        "fecha_novo": fecha,
        "artigos_novo": own,
        "chars_por_pagina": round(per_page, 1),
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
    sha = str(row.get("sha256_fonte") or "")
    if any(k[0] == sha and k[1] == PDF_TEXT_ENGINE for k in done):
        return True  # a camada de texto do PDF já foi lida e aceita
    prev = done.get((sha, ENGINE, ENGINE_VERSION, kreuzberg_version))
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
    defeitos: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Normas com texto cujo leitor não fecha o nível dos artigos, em ordem estável.

    Entra quem tem texto, ``pdf_url`` e ``sha256_fonte`` e cuja leitura
    (``read_hierarchy``) não fecha. Sai quem já foi tentado com o mesmo PDF e o
    mesmo motor (aceito ou rejeitado). Ordem: primeiro quem lê ao menos 1 artigo
    próprio no texto do IA (o caso do re-OCR-piloto: a leitura já está parcial), depois
    quem lê zero; dentro de cada classe, ``texto_id``. Nenhum é descartado, salvo as que
    ``defeitos`` (``leizilla.defeitos``) registra como defeito do arquivo oficial, para
    **os mesmos bytes** (``sha256_fonte``): o OCR não tem o que ganhar. Cada linha devolvida
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
        if defeito_de(row, defeitos) is not None:
            stats.defeitos_da_fonte += 1
            continue
        if _already_done(row, done, kreuzberg_version, max_pages):
            stats.ja_tentadas += 1
            continue
        queue.append({**row, "_artigos_ia": n_own, "_fecha_ia": fecha})
    # sort é estável: dentro de cada classe a ordem por texto_id é preservada.
    queue.sort(key=lambda r: r["_artigos_ia"] == 0)
    stats.na_fila = len(queue)
    stats.fila_com_artigos = sum(1 for r in queue if r["_artigos_ia"] >= 1)
    stats.fila_sem_artigos = len(queue) - stats.fila_com_artigos
    return queue


def shard_of(texto_id: str, count: int) -> int:
    """Fatia (0..count-1) de uma norma: hash estável do ``texto_id``.

    Disjunta e completa por construção, e independente do instante em que cada
    fatia enumera a fila (uma norma nova cai numa fatia só).
    """
    return int(hashlib.sha256(texto_id.encode()).hexdigest()[:12], 16) % count


def parse_shard(spec: str) -> tuple[int, int]:
    """``'i/n'`` (``0 <= i < n``) → ``(i, n)``; ``ValueError`` se malformado."""
    m = re.fullmatch(r"(\d+)/(\d+)", spec.strip())
    if not m or int(m.group(2)) < 1 or int(m.group(1)) >= int(m.group(2)):
        raise ValueError(f"--shard deve ser i/n com 0 <= i < n (recebido: {spec!r})")
    return int(m.group(1)), int(m.group(2))


def in_shard(queue: list[dict[str, Any]], shard: Optional[tuple[int, int]]) -> list:
    """Linhas da fila que pertencem à fatia ``(i, n)`` (tudo, se ``shard`` é None)."""
    if shard is None:
        return queue
    i, n = shard
    return [q for q in queue if shard_of(str(q["texto_id"]), n) == i]


def select_sem_texto(
    candidates: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    *,
    kreuzberg_version: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    years: Optional[dict[str, int]] = None,
    stats: Optional[ReocrStats] = None,
) -> list[dict[str, Any]]:
    """Fila ``sem-texto``: PDFs preservados sem texto, mais recentes primeiro.

    ``candidates`` vem de ``textlayer.collect_sem_texto`` (já sem as normas com
    texto no IA ou em ``textos``). Sai quem já foi tentado com o mesmo PDF e
    motor (mesma regra da outra fila). Ordem: ano da norma decrescente, conforme
    o livro-razão publicado (``years``; sem ano, no fim), depois número
    decrescente, tipo e ``texto_id`` — determinística. Cada item ganha ``_fila``.
    """
    stats = stats or ReocrStats()
    years = years or {}
    done = {attempt_key(a): a for a in attempts}
    queue: list[dict[str, Any]] = []
    for row in candidates:
        stats.sem_texto_enumeradas += 1
        if not row.get("pdf_url") or not row.get("sha256_fonte"):
            continue
        if _already_done(row, done, kreuzberg_version, max_pages):
            stats.sem_texto_ja_tentadas += 1
            continue
        queue.append({**row, "_fila": FILA_SEM_TEXTO})

    def order(r: dict[str, Any]) -> tuple[bool, int, int, str, str]:
        ano = years.get(str(r["texto_id"]))
        return (
            ano is None,
            -(ano or 0),
            -int(r.get("numero") or 0),
            str(r.get("tipo") or ""),
            str(r["texto_id"]),
        )

    queue.sort(key=order)
    stats.sem_texto_na_fila = len(queue)
    return queue


def split_limit(limit: Optional[int], n_sem: int, n_nao: int) -> tuple[int, int]:
    """Quantas normas tentar de cada fila: ``(sem_texto, nao_fecha)``.

    Sem ``limit``, todas. Com ``limit``, a ``sem-texto`` vai primeiro, até 2/3
    (arredondado para baixo, mínimo 1) e a ``nao-fecha`` fica com o resto; o que uma fila não
    usa (fila menor que sua cota) passa para a outra, e nenhuma fila é zerada
    enquanto o limite permitir: com ``limit >= 2`` e as duas não vazias, cada uma
    recebe ao menos 1.
    """
    if limit is None:
        return n_sem, n_nao
    num, den = SEM_TEXTO_PARTE
    quota_sem = max(1, limit * num // den)
    take_sem = min(n_sem, quota_sem)
    take_nao = min(n_nao, limit - take_sem)
    take_sem = min(n_sem, limit - take_nao)
    return take_sem, take_nao


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


def pdf_text_layer(pdf_bytes: bytes) -> Optional[OcrOutcome]:
    """Camada de texto embutida do PDF (``pdftotext``, poppler), sem rasterizar.

    Um PDF nascido digital (os "Text PDF" do IA, a maioria das versões compiladas da
    Casa Civil) já traz o texto: lê-lo é instantâneo, não exige o extra ``reocr`` e é
    melhor que o OCR de uma imagem do mesmo texto. Modo simples (sem ``-layout``: o
    layout enche o texto de corridas de espaços de coluna). ``None`` se o poppler falha
    ou falta; o chamador então cai no OCR. O portão (`judge_sem_texto`) decide se o
    texto serve: um PDF escaneado devolve quase nada.
    """
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "in.pdf"
            pdf_path.write_bytes(pdf_bytes)
            pages = pdf_page_count(pdf_path)
            text = subprocess.run(
                [_require("pdftotext"), "-q", str(pdf_path), "-"],
                capture_output=True,
                check=True,
                timeout=_PDF_TIMEOUT_S,
            ).stdout.decode("utf-8", errors="replace")
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return None
    return OcrOutcome(text=text, pages=pages, kreuzberg_version=_poppler_version())


def _poppler_version() -> str:
    """Versão do poppler (``pdftotext -v`` escreve no stderr), ``'desconhecida'`` se falha."""
    try:
        out = subprocess.run(
            [_require("pdftotext"), "-v"], capture_output=True, text=True, timeout=30
        ).stderr
    except (RuntimeError, OSError, subprocess.SubprocessError):
        return "desconhecida"
    m = re.search(r"version\s+(\S+)", out)
    return m.group(1) if m else "desconhecida"


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
    text_layer: Optional[TextLayerFn] = None,
    kreuzberg_version: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Tenta o re-OCR de cada norma da fila; devolve uma linha por tentativa.

    Na fila ``sem-texto`` um PDF com camada de texto embutida (``text_layer``, por
    padrão `pdf_text_layer`) é lido sem OCR: se o texto passa no portão, a linha
    leva o motor ``pdftotext``; senão o PDF segue para o OCR.

    Sequencial e educado com o IA: um download por vez, ``sleep_s`` (>= 1 s) entre
    eles. Falha de download não vira tentativa (é transitória: a norma volta à fila
    na próxima execução); falha do OCR vira rejeição ``ocr-falhou``.
    """
    fetch = fetch or textlayer.http_get
    ocr = ocr or ocr_pdf
    text_layer = text_layer or pdf_text_layer
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
        fila = str(item.get("_fila") or FILA_NAO_FECHA)
        row = _base_row(
            item,
            kz_version,
            fila=fila,
            sha256_pdf=sha_pdf,
            artigos_ia=item.get("_artigos_ia"),
            fecha_ia=item.get("_fecha_ia"),
        )
        started = time.monotonic()
        stats.tentadas += 1
        if sha_pdf != item.get("sha256_fonte"):
            row.update(motivo=PDF_DIVERGE)
        else:
            layer = text_layer(pdf) if fila == FILA_SEM_TEXTO else None
            if layer is not None and judge_sem_texto(layer.text, layer.pages)["aceito"]:
                row.update(
                    engine=PDF_TEXT_ENGINE,
                    engine_version=layer.kreuzberg_version,
                    parametros="pdftotext -q (sem -layout); camada de texto embutida",
                )
                outcome = layer
                kz_row = ""
                failure: Optional[BaseException] = None
            else:
                kz_row = None
                failure = None
                try:
                    outcome = ocr(pdf, max_pages)
                except TooManyPages as e:
                    stats.grandes += 1
                    row.update(motivo=EXCEDE_PAGINAS, paginas=e.pages)
                    failure = e
                except Exception as e:  # noqa: BLE001 — bulkhead por norma; logado abaixo
                    logger.exception("re-OCR falhou em %s", tid)
                    row.update(motivo=OCR_FALHOU)
                    failure = e
            if failure is None:
                row.update(paginas=outcome.pages)
                row["kreuzberg_version"] = (
                    kz_row if kz_row is not None else outcome.kreuzberg_version
                )
                new_text = outcome.text
                if not new_text.strip():
                    row.update(motivo=OCR_VAZIO)
                elif fila == FILA_SEM_TEXTO:
                    sem = judge_sem_texto(new_text, outcome.pages)
                    row.update(
                        aceito=sem["aceito"],
                        motivo=sem["motivo"],
                        fecha_novo=sem["fecha_novo"],
                        artigos_novo=sem["artigos_novo"],
                        sha256_texto=hashlib.sha256(new_text.encode()).hexdigest(),
                        num_caracteres=len(new_text),
                    )
                    if sem["aceito"]:
                        row["texto"] = new_text
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


def run_queues(
    sem_texto: list[dict[str, Any]],
    nao_fecha: list[dict[str, Any]],
    *,
    stats: ReocrStats,
    limit: Optional[int] = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Executa as duas filas: ``sem-texto`` primeiro, depois ``nao-fecha``.

    A divisão do ``limit`` é a de ``split_limit``. Falha de download não consome
    cota (a norma volta à fila); o que a ``sem-texto`` não usou — fila curta ou
    falhas — passa para a ``nao-fecha``.
    """
    take_sem, take_nao = split_limit(limit, len(sem_texto), len(nao_fecha))
    out: list[dict[str, Any]] = []
    if take_sem:
        out = run_reocr(sem_texto, stats=stats, limit=take_sem, **kwargs)
    if limit is not None:
        take_nao = min(len(nao_fecha), max(take_nao, limit - len(out)))
    if take_nao and nao_fecha:
        if out:
            time.sleep(max(kwargs.get("sleep_s", MIN_SLEEP_S), MIN_SLEEP_S))
        out += run_reocr(nao_fecha, stats=stats, limit=take_nao, **kwargs)
    return out


def enumerate_sem_texto(
    ente: str,
    fontes: list[str],
    textos_rows: list[dict[str, Any]],
    *,
    fetch: Optional[Fetcher] = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """PDFs preservados sem texto (fila ``sem-texto``), sem filtro de tentativas.

    Reusa a enumeração da camada de texto (itens de range → ``index.csv`` →
    arquivos). Fica de fora toda norma que já tem linha com texto no ``textos``
    publicado ou cujo ``_djvu.txt`` já existe no IA. Devolve ``(candidatos,
    falhas)``: com falhas a lista pode estar incompleta (a fila segue assim mesmo;
    o que faltar entra numa próxima execução).
    """
    com_texto = {
        str(r["texto_id"]): str(r.get("sha256_fonte") or "")
        for r in textos_rows
        if r.get("texto")
    }
    stats = textlayer.BuildStats()
    out: list[dict[str, Any]] = []
    for fonte in fontes:
        out.extend(
            textlayer.collect_sem_texto(
                ente, fonte, stats=stats, com_texto=com_texto, fetch=fetch
            )
        )
    return out, stats.failures


def fetch_published_years(ente: str, version: int) -> dict[str, int]:
    """``texto_id`` → ano da norma, do livro-razão publicado (ordem da fila).

    Fail-open: sem o livro-razão a fila ``sem-texto`` se ordena só pelo número.
    """
    item = f"leizilla-dataset-{ente.lower()}-v{version}-latest"
    url = f"https://archive.org/download/{item}/completeness.parquet"
    req = urllib.request.Request(url, headers={"User-Agent": textlayer._USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
    except (urllib.error.URLError, OSError) as e:
        logger.warning(
            "livro-razão indisponível (%s): fila sem ordem por ano — %s", url, e
        )
        return {}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "completeness.parquet"
        path.write_bytes(data)
        return read_years(path)


def read_years(path: Path) -> dict[str, int]:
    """``texto_id`` → ano de um ``completeness.parquet`` (linhas com ano)."""
    import duckdb

    conn = duckdb.connect()
    try:
        rows = conn.execute(
            "SELECT texto_id, ano FROM read_parquet(?) WHERE ano IS NOT NULL",
            [str(path)],
        ).fetchall()
    except duckdb.Error as e:
        logger.warning("livro-razão ilegível (%s): %s", path, e)
        return {}
    finally:
        conn.close()
    return {str(t): int(a) for t, a in rows}


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
        rows = [dict(zip(names, values)) for values in cur.fetchall()]
    finally:
        conn.close()
    for row in rows:
        # Compatibilidade: arquivos anteriores à coluna ``fila`` são ``nao-fecha``.
        row["fila"] = row.get("fila") or FILA_NAO_FECHA
        for col in REOCR_SCHEMA:
            row.setdefault(col, None)
    return rows


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
        if row["fila"] not in FILAS:
            problems.append(f"{tid}: fila desconhecida ({row['fila']})")
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
        # O IA responde 503 (não 404) ao /download/ de um item que nunca existiu;
        # a API de metadados é quem confirma a ausência (devolve ``{}``).
        if e.code == 404 or _item_never_published(item):
            return False
        raise OSError(f"{url}: HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise OSError(f"{url}: {e}") from e
    return True


def _item_never_published(item: str) -> bool:
    """``True`` só se a API de metadados do IA confirma que o item não existe.

    Qualquer falha ao perguntar devolve ``False``: na dúvida, o item existe e quem
    chama aborta em vez de publicar um histórico encolhido.
    """
    url = f"https://archive.org/metadata/{item}"
    req = urllib.request.Request(url, headers={"User-Agent": textlayer._USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return bool(json.loads(resp.read()) == {})
    except (urllib.error.URLError, ValueError):
        return False


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
