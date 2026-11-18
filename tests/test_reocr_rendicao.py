"""Fila ``sem-texto`` que olha a rendição de leitura e lê a camada de texto do PDF.

Offline: o IA, o OCR e a camada de texto são falsos; o poppler só entra num teste
que o pula se ``pdftotext`` não existe.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from typing import Any, Optional
from unittest.mock import patch

import pytest

from leizilla import reocr, textlayer

ITEM = "leizilla_ro_casacivil_lei_0001-1000"

# lei 21: original com texto + compilada sem; lei 22: compilada com texto + original sem;
# lei 23: só compilada, sem texto; lei 24: só original, sem texto.
INDEX = (
    "tipo,numero,rendicao,formato,uuid5,sha256,captured_at,source\n"
    "lei,21,,pdf,a1a1a1a1,sha-21-orig,2026-01-01T00:00:00+00:00,L21.pdf\n"
    "lei,21,compilada,pdf,a2a2a2a2,sha-21-comp,2026-01-02T00:00:00+00:00,"
    "L21 - COMPILADA.pdf\n"
    "lei,22,,pdf,b1b1b1b1,sha-22-orig,2026-01-01T00:00:00+00:00,L22.pdf\n"
    "lei,22,compilada,pdf,b2b2b2b2,sha-22-comp,2026-01-02T00:00:00+00:00,"
    "L22 - COMPILADA.pdf\n"
    "lei,23,compilada,pdf,c1c1c1c1,sha-23-comp,2026-01-02T00:00:00+00:00,"
    "L23 - COMPILADA.pdf\n"
    "lei,24,,pdf,d1d1d1d1,sha-24-orig,2026-01-01T00:00:00+00:00,L24.pdf\n"
)


def _tid(n: int) -> str:
    return f"leizilla-raw-ro-casacivil-lei-{n:05d}"


def _files() -> bytes:
    names = [
        "lei-00021_a1a1a1a1.pdf",
        "lei-00021_a1a1a1a1_djvu.txt",
        "lei-00021_a2a2a2a2.pdf",
        "lei-00022_b1b1b1b1.pdf",
        "lei-00022_b2b2b2b2.pdf",
        "lei-00022_b2b2b2b2_djvu.txt",
        "lei-00023_c1c1c1c1.pdf",
        "lei-00024_d1d1d1d1.pdf",
    ]
    return json.dumps(
        {"files": [{"name": n, "mtime": "1789245941"} for n in names]}
    ).encode()


def _fetch(url: str) -> Optional[bytes]:
    return _files() if "/metadata/" in url else None


@pytest.fixture(autouse=True)
def _ia() -> Any:
    with (
        patch("leizilla.publisher.scrape_identifiers", return_value=[ITEM]),
        patch("leizilla.publisher.fetch_existing_index", return_value=INDEX),
        patch("leizilla.textlayer.time.sleep"),
        patch("leizilla.reocr.time.sleep"),
    ):
        yield


def _queue(com_texto: Any) -> dict[str, str]:
    found = textlayer.collect_sem_texto(
        "ro",
        "casacivil",
        stats=textlayer.BuildStats(),
        com_texto=com_texto,
        fetch=_fetch,
    )
    return {f["texto_id"]: f["rendicao"] for f in found}


def test_a_compiled_pdf_without_text_is_queued_even_if_the_original_has_text() -> None:
    queue = _queue(set())
    assert queue == {
        _tid(21): "compilada",  # the original has text, the compiled does not
        _tid(23): "compilada",
        _tid(24): "original",
    }
    # lei 22: the compiled has text, the original does not; the reading text exists


def test_a_published_row_of_the_compiled_file_covers_the_norm() -> None:
    covered = {_tid(21): "sha-21-comp"}  # the row is the compiled file's own text
    assert _tid(21) not in _queue(covered)
    # a published row from the ORIGINAL does not: the compiled still lacks its text
    assert _tid(21) in _queue({_tid(21): "sha-21-orig"})
    # a row older than the rendition column (unknown sha) counts as an original
    assert _tid(21) in _queue({_tid(21): ""})


def test_the_old_set_form_keeps_the_old_rule() -> None:
    # a plain set of ids (no rendition known) never re-queues a norm that has a row
    assert _tid(21) not in _queue({_tid(21)})


def test_the_queue_row_of_a_compiled_file_carries_its_sha_and_rendition() -> None:
    found = textlayer.collect_sem_texto(
        "ro", "casacivil", stats=textlayer.BuildStats(), com_texto=set(), fetch=_fetch
    )
    row = next(f for f in found if f["texto_id"] == _tid(21))
    assert row["sha256_fonte"] == "sha-21-comp"
    assert row["pdf_url"].endswith("lei-00021_a2a2a2a2.pdf")


# --- camada de texto do PDF antes do OCR ----------------------------------------------
TEXT = (
    "Art. 1º Fica criado o fundo estadual de saúde, com recursos próprios. " * 5 + "\n"
) * 3


def _item(pdf: bytes) -> dict[str, Any]:
    return {
        "texto_id": _tid(21),
        "ente": "ro",
        "fonte": "casacivil",
        "tipo": "lei",
        "numero": 21,
        "ia_item": ITEM,
        "pdf_url": "https://archive.org/download/x/lei-00021_a2a2a2a2.pdf",
        "sha256_fonte": hashlib.sha256(pdf).hexdigest(),
        "_fila": "sem-texto",
    }


def _ocr_must_not_run(pdf: bytes, max_pages: int) -> reocr.OcrOutcome:
    raise AssertionError("OCR rodou num PDF com camada de texto")


def test_a_pdf_with_a_text_layer_is_read_without_ocr() -> None:
    pdf = b"%PDF-born-digital"
    layer = reocr.OcrOutcome(text=TEXT, pages=1, kreuzberg_version="24.08.0")
    rows = reocr.run_reocr(
        [_item(pdf)],
        stats=reocr.ReocrStats(),
        fetch=lambda url: pdf,
        ocr=_ocr_must_not_run,
        text_layer=lambda b: layer,
        kreuzberg_version="ausente",
    )
    (row,) = rows
    assert row["aceito"] and row["motivo"] == reocr.ACEITO
    assert row["engine"] == reocr.PDF_TEXT_ENGINE and row["texto"] == TEXT
    assert row["engine_version"] == "24.08.0" and row["kreuzberg_version"] == ""
    assert row["paginas"] == 1 and row["fila"] == "sem-texto"


def test_a_scanned_pdf_falls_through_to_ocr() -> None:
    pdf = b"%PDF-scanned"
    sparse = reocr.OcrOutcome(text="1\n", pages=3, kreuzberg_version="24.08.0")
    ocr_text = reocr.OcrOutcome(text=TEXT * 4, pages=1, kreuzberg_version="4.10")
    rows = reocr.run_reocr(
        [_item(pdf)],
        stats=reocr.ReocrStats(),
        fetch=lambda url: pdf,
        ocr=lambda b, m: ocr_text,
        text_layer=lambda b: sparse,
        kreuzberg_version="4.10",
    )
    (row,) = rows
    assert row["aceito"] and row["engine"] == reocr.ENGINE
    assert row["kreuzberg_version"] == "4.10"


def test_a_failing_text_layer_tool_falls_through_to_ocr() -> None:
    pdf = b"%PDF-x"
    ocr_text = reocr.OcrOutcome(text=TEXT * 4, pages=1, kreuzberg_version="4.10")
    rows = reocr.run_reocr(
        [_item(pdf)],
        stats=reocr.ReocrStats(),
        fetch=lambda url: pdf,
        ocr=lambda b, m: ocr_text,
        text_layer=lambda b: None,
        kreuzberg_version="4.10",
    )
    assert rows[0]["engine"] == reocr.ENGINE


def test_the_nao_fecha_queue_never_uses_the_text_layer() -> None:
    pdf = b"%PDF-y"
    item = {
        **_item(pdf),
        "_fila": "nao-fecha",
        "texto": "Art. 1º um.",
        "_artigos_ia": 1,
    }
    called: list[bytes] = []
    reocr.run_reocr(
        [item],
        stats=reocr.ReocrStats(),
        fetch=lambda url: pdf,
        ocr=lambda b, m: reocr.OcrOutcome(text="x", pages=1, kreuzberg_version="4.10"),
        text_layer=lambda b: called.append(b),  # type: ignore[arg-type, return-value]
        kreuzberg_version="4.10",
    )
    assert called == []


def test_an_accepted_text_layer_attempt_blocks_a_second_try() -> None:
    attempt = {
        "sha256_fonte": "sha-21-comp",
        "engine": reocr.PDF_TEXT_ENGINE,
        "engine_version": "24.08.0",
        "kreuzberg_version": "",
    }
    candidates = [
        {
            "texto_id": _tid(21),
            "pdf_url": "u",
            "sha256_fonte": "sha-21-comp",
            "numero": 21,
            "tipo": "lei",
        }
    ]
    queue = reocr.select_sem_texto(candidates, [attempt], kreuzberg_version="4.10")
    assert queue == []


def test_the_own_text_of_the_compiled_file_wins_over_the_original_text() -> None:
    accepted = {
        _tid(21): {
            "texto_id": _tid(21),
            "fila": "sem-texto",
            "sha256_fonte": "sha-21-comp",
            "texto": "Art. 1º Fica criado o fundo.\nArt. 2º Esta Lei entra em vigor.\n",
            "engine": reocr.PDF_TEXT_ENGINE,
            "engine_version": "24.08.0",
            "kreuzberg_version": "",
            "parametros": "pdftotext -q",
            "tentado_em": "2026-11-18T00:00:00+00:00",
        }
    }
    djvu = {"lei-00021_a1a1a1a1_djvu.txt": b"Art. 1 texto do original\n"}

    def fetch(url: str) -> Optional[bytes]:
        if "/metadata/" in url:
            return _files()
        return djvu.get(url.rsplit("/", 1)[-1]) or b"Art. 1 texto\n"

    rows, _ = textlayer.build_textos(
        "ro", ["casacivil"], sleep_s=0, fetch=fetch, reocr=accepted
    )
    row = next(r for r in rows if r["texto_id"] == _tid(21))
    assert row["rendicao"] == "compilada" and row["sha256_fonte"] == "sha-21-comp"
    assert row["ocr_motor"] == textlayer.PDF_TEXT_MOTOR
    assert row["texto"].startswith("Art. 1º Fica criado o fundo.")
    assert row["texto_url"] is None
    # the original stays reachable as the other rendition
    assert "sha-21-orig" in row["outras_rendicoes"]


# --- poppler de verdade (pulado sem pdftotext) -------------------------------------
def _tiny_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 20 700 Td ({text}) Tj ET".encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1,
        xref,
    )
    return out


@pytest.mark.skipif(
    shutil.which("pdftotext") is None or shutil.which("pdfinfo") is None,
    reason="no poppler",
)
def test_pdf_text_layer_reads_a_real_text_pdf_and_none_for_garbage() -> None:
    got = reocr.pdf_text_layer(_tiny_pdf("Art. 1o Fica criado o fundo"))
    assert got is not None and "Fica criado o fundo" in got.text and got.pages == 1
    assert reocr.pdf_text_layer(b"not a pdf") is None
