"""Qual rendição a camada de texto mostra (ADR-0015, adendo 2026-11-18). Offline.

A norma tem uma linha em ``textos``; quando o IA tem mais de um arquivo dela
(original e compilada), o texto de leitura é o da compilada, o original segue
alcançável em ``outras_rendicoes`` e o overlay de re-OCR só vale para o PDF de onde
veio (``sha256_fonte``).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch

import pytest

from leizilla import textlayer

ITEM = "leizilla_ro_casacivil_lc_0001-1000"
ORIGINAL = (
    "LEI COMPLEMENTAR N. 68\n\nArt. 1º Primeiro.\nArt. 2º Segundo.\n"
    "Art. 3º Esta Lei entra em vigor na data de sua publicação.\n"
).encode()
COMPILADA = (
    "LEI COMPLEMENTAR N. 68 (compilada)\n\nArt. 1º Primeiro. (Redação dada pela "
    "Lei nº 9)\nArt. 2º (Revogado pela Lei nº 9)\n"
    "Art. 3º Esta Lei entra em vigor na data de sua publicação.\n"
).encode()


def _cap(
    uuid5: str, sha: str, when: str, rendicao: str = "", source: str = "s/LC68.pdf"
) -> dict[str, str]:
    return {
        "tipo": "lc",
        "numero": "68",
        "rendicao": rendicao,
        "formato": "pdf",
        "uuid5": uuid5,
        "sha256": sha,
        "captured_at": when,
        "source": source,
    }


def _index(*caps: dict[str, str]) -> str:
    cols = "tipo,numero,rendicao,formato,uuid5,sha256,captured_at,source"
    lines = [",".join(c[k] for k in cols.split(",")) for c in caps]
    return "\n".join([cols, *lines]) + "\n"


def _entry(name: str, data: Optional[bytes] = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": name, "mtime": "1789245941"}
    if data is not None:
        entry["sha1"] = hashlib.sha1(data).hexdigest()
    return entry


class FakeIA:
    def __init__(self, files: list[dict[str, Any]], texts: dict[str, bytes]) -> None:
        self.metadata = json.dumps({"files": files}).encode()
        self.texts = texts

    def __call__(self, url: str) -> Optional[bytes]:
        if "/metadata/" in url:
            return self.metadata
        return self.texts.get(url.rsplit("/", 1)[-1])


def _build(
    caps: list[dict[str, str]],
    files: list[dict[str, Any]],
    texts: dict[str, bytes],
    **kw: Any,
) -> list[dict[str, Any]]:
    with (
        patch("leizilla.textlayer.time.sleep"),
        patch("leizilla.publisher.scrape_identifiers", return_value=[ITEM]),
        patch("leizilla.publisher.fetch_existing_index", return_value=_index(*caps)),
    ):
        rows, _ = textlayer.build_textos(
            "ro", ["casacivil"], fetch=FakeIA(files, texts), **kw
        )
    return rows


ORIG = _cap("aaaa1111", "sha-orig", "2026-11-20T00:00:00+00:00")  # captured LATER
COMP = _cap(
    "bbbb2222",
    "sha-comp",
    "2026-11-18T00:00:00+00:00",
    "compilada",
    "s/LC68%20-%20COMPILADA.pdf",
)
FILES_BOTH = [
    _entry("aaaa1111.pdf"),
    _entry("aaaa1111_djvu.txt", ORIGINAL),
    _entry("bbbb2222.pdf"),
    _entry("bbbb2222_djvu.txt", COMPILADA),
]
TEXTS_BOTH = {"aaaa1111_djvu.txt": ORIGINAL, "bbbb2222_djvu.txt": COMPILADA}


def test_reading_order_compiled_original_then_the_rest() -> None:
    caps = [
        _cap("1", "s1", "2026-01-01", "revogado"),
        _cap("2", "s2", "2026-01-01", "outra"),
        _cap("3", "s3", "2026-01-01", "retificado"),
        _cap("4", "s4", "2026-01-01", ""),
        _cap("5", "s5", "2026-01-01", "compilada"),
    ]
    got = [textlayer.capture_rendicao(c) for c in textlayer.order_for_reading(caps)]
    assert got == ["compilada", "original", "retificado", "outra", "revogado"]


def test_rendition_comes_from_the_source_name_when_the_column_is_blank() -> None:
    blank = _cap("1", "s1", "2026-01-01", "", "s/LC68%20-%20COMPILADA.pdf")
    plain = _cap("2", "s2", "2026-01-01", "", "s/LC68.pdf")
    unknown = _cap("3", "s3", "2026-01-01", "", "https://planalto/ccivil/lei.htm")
    assert textlayer.capture_rendicao(blank) == "compilada"
    assert textlayer.capture_rendicao(plain) == "original"
    assert textlayer.capture_rendicao(unknown) == "original"
    # declared column wins over the name
    declared = _cap("4", "s4", "2026-01-01", "revogado", "s/LC68.pdf")
    assert textlayer.capture_rendicao(declared) == "revogado"


def test_ties_break_by_newest_capture_then_sha_and_ignore_input_order() -> None:
    a = _cap("1", "sha-b", "2026-02-01")
    b = _cap("2", "sha-a", "2026-02-01")
    c = _cap("3", "sha-z", "2026-03-01")
    for caps in ([a, b, c], [c, b, a], [b, c, a]):
        order = [x["sha256"] for x in textlayer.order_for_reading(caps)]
        assert order == ["sha-z", "sha-a", "sha-b"]


def test_compiled_wins_over_a_more_recent_original_and_the_original_stays_reachable() -> (
    None
):
    (row,) = _build([ORIG, COMP], FILES_BOTH, TEXTS_BOTH)
    assert row["texto_id"] == "leizilla-raw-ro-casacivil-lc-00068"
    assert row["rendicao"] == "compilada"
    assert row["sha256_fonte"] == "sha-comp"
    assert "(compilada)" in row["texto"]
    assert row["pdf_url"].endswith("/bbbb2222.pdf")
    others = json.loads(row["outras_rendicoes"])
    assert others == [
        {
            "rendicao": "original",
            "sha256": "sha-orig",
            "capturado_em": "2026-11-20T00:00:00+00:00",
            "pdf_url": f"https://archive.org/download/{ITEM}/aaaa1111.pdf",
            "texto_url": f"https://archive.org/download/{ITEM}/aaaa1111_djvu.txt",
        }
    ]


def test_single_rendition_row_has_no_other_renditions() -> None:
    (row,) = _build([ORIG], FILES_BOTH[:2], TEXTS_BOTH)
    assert row["rendicao"] == "original"
    assert json.loads(row["outras_rendicoes"]) == []
    assert row["sha256_fonte"] == "sha-orig"


def test_compiled_without_text_yet_is_listed_but_the_original_is_read() -> None:
    files = [f for f in FILES_BOTH if f["name"] != "bbbb2222_djvu.txt"]
    (row,) = _build([ORIG, COMP], files, TEXTS_BOTH)
    assert row["sha256_fonte"] == "sha-orig"
    (other,) = json.loads(row["outras_rendicoes"])
    assert other["rendicao"] == "compilada" and other["texto_url"] is None
    assert other["pdf_url"].endswith("/bbbb2222.pdf")


def test_recapture_of_the_same_bytes_is_not_another_rendition() -> None:
    again = _cap("cccc3333", "sha-orig", "2026-11-21T00:00:00+00:00")
    files = FILES_BOTH + [_entry("cccc3333.pdf")]
    (row,) = _build([ORIG, again, COMP], files, TEXTS_BOTH)
    others = json.loads(row["outras_rendicoes"])
    assert [o["sha256"] for o in others] == ["sha-orig"]
    assert others[0]["texto_url"].endswith("aaaa1111_djvu.txt")  # the twin with text


def test_rendition_does_not_flip_while_the_ia_rederives_the_preferred_one() -> None:
    (first,) = _build([ORIG, COMP], FILES_BOTH, TEXTS_BOTH)
    assert first["sha256_fonte"] == "sha-comp"
    files = [f for f in FILES_BOTH if f["name"] != "bbbb2222_djvu.txt"]
    (again,) = _build(
        [ORIG, COMP], files, TEXTS_BOTH, previous={first["texto_id"]: first}
    )
    assert again["sha256_fonte"] == "sha-comp"
    assert again["texto"] == first["texto"]
    assert [o["rendicao"] for o in json.loads(again["outras_rendicoes"])] == [
        "original"
    ]


def test_previous_row_built_under_the_old_rule_is_replaced_by_the_compiled() -> None:
    (old,) = _build([ORIG], FILES_BOTH[:2], TEXTS_BOTH)
    (new,) = _build(
        [ORIG, COMP], FILES_BOTH, TEXTS_BOTH, previous={old["texto_id"]: old}
    )
    assert new["sha256_fonte"] == "sha-comp"


def _hit(sha_fonte: str, text: str, fila: str = "nao-fecha") -> dict[str, Any]:
    return {
        "sha256_fonte": sha_fonte,
        "texto": text,
        "fila": fila,
        "sha256_texto": hashlib.sha256(text.encode()).hexdigest(),
        "kreuzberg_version": "3.0",
        "parametros": "p",
        "tentado_em": "2026-11-18T00:00:00+00:00",
    }


def test_reocr_of_the_original_is_never_applied_to_the_compiled_text() -> None:
    tid = "leizilla-raw-ro-casacivil-lc-00068"
    accepted = {tid: _hit("sha-orig", "TEXTO REOCR DO ORIGINAL")}
    rows = _build([ORIG, COMP], FILES_BOTH, TEXTS_BOTH, reocr=accepted)
    assert rows[0]["sha256_fonte"] == "sha-comp"
    assert "REOCR" not in rows[0]["texto"]
    # and the other way round: a compiled re-OCR never lands on the original row
    accepted = {tid: _hit("sha-comp", "TEXTO REOCR DA COMPILADA")}
    rows = _build([ORIG], FILES_BOTH[:2], TEXTS_BOTH, reocr=accepted)
    assert "REOCR" not in rows[0]["texto"]
    # the matching one does apply
    rows = _build(
        [ORIG, COMP],
        FILES_BOTH,
        TEXTS_BOTH,
        reocr={tid: _hit("sha-comp", "TEXTO REOCR DA COMPILADA")},
    )
    assert rows[0]["texto"] == "TEXTO REOCR DA COMPILADA"
    assert rows[0]["rendicao"] == "compilada"


def test_parquet_contract_roundtrips_with_the_new_column(tmp_path: Path) -> None:
    rows = _build([ORIG, COMP], FILES_BOTH, TEXTS_BOTH)
    out = tmp_path / "textos.parquet"
    textlayer.write_textos_parquet(rows, out)
    assert textlayer.validate_textos_parquet(out) == []
    back = textlayer.read_textos_parquet(out)["leizilla-raw-ro-casacivil-lc-00068"]
    assert back["rendicao"] == "compilada"
    assert json.loads(back["outras_rendicoes"])[0]["rendicao"] == "original"


@pytest.mark.parametrize("col", ["texto_id", "texto", "sha256_fonte", "pdf_url"])
def test_columns_consumers_read_are_still_in_the_contract(col: str) -> None:
    assert col in textlayer.TEXTOS_SCHEMA
