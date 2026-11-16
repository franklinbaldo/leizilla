"""Re-OCR direcionado (ADR-0019) — offline; Kreuzberg nunca é importado."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import urllib.error
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from leizilla import publisher, reocr, textlayer
from leizilla.cli import app
from test_textlayer import INDEX as _INDEX
from test_textlayer import ITEM as _ITEM
from test_textlayer import OPEN as _TL_OPEN
from test_textlayer import _default_ia

_runner = CliRunner()

CLOSING = (
    "LEI N. 7, DE 1983\n\nDispõe sobre coisa alguma.\n\n"
    "Art. 1º Fica criada a coisa.\n"
    "Art. 2º A coisa será mantida.\n"
    "Art. 3º Esta Lei entra em vigor na data de sua publicação.\n"
)
OPEN = "LEI N. 9\n\nArt. 1º Primeiro.\nArt. 5º Quinto, sem os do meio.\n"
# Não fecha (falta o 5), mas o leitor acha 6 artigos próprios.
MANY_OPEN = (
    "LEI N. 9\n\nArt. 1º A.\nArt. 2º B.\nArt. 3º C.\nArt. 4º D.\nArt. 6º F.\n"
    "Art. 7º Esta Lei entra em vigor na data de sua publicação.\n"
)
SHORT_CLOSING = (
    "LEI N. 9\n\nArt. 1º A.\n"
    "Art. 2º Esta Lei entra em vigor na data de sua publicação.\n"
)
KZ = "4.10.4"


def _pdf(n: int) -> bytes:
    return f"%PDF fake {n}".encode()


def _row(n: int, text: str) -> dict[str, Any]:
    return {
        "texto_id": f"leizilla-raw-ro-casacivil-lei-{n:05d}",
        "ente": "ro",
        "fonte": "casacivil",
        "tipo": "lei",
        "numero": n,
        "ia_item": "leizilla_ro_casacivil_lei_0001-1000",
        "pdf_url": f"https://archive.org/download/x/{n}.pdf",
        "sha256_fonte": hashlib.sha256(_pdf(n)).hexdigest(),
        "texto": text,
    }


def _fetch(url: str) -> Optional[bytes]:
    n = int(url.rsplit("/", 1)[-1].split(".")[0])
    return _pdf(n)


def _ocr_returning(text: str, pages: int = 2) -> Any:
    def _ocr(pdf: bytes, max_pages: int) -> reocr.OcrOutcome:
        return reocr.OcrOutcome(text=text, pages=pages, kreuzberg_version=KZ)

    return _ocr


@pytest.fixture(autouse=True)
def _no_sleep() -> Any:
    with patch("leizilla.reocr.time.sleep"):
        yield


def _queue(rows: list[dict[str, Any]], attempts: Optional[list[Any]] = None) -> Any:
    stats = reocr.ReocrStats()
    queue = reocr.select_queue(rows, attempts or [], kreuzberg_version=KZ, stats=stats)
    return queue, stats


def test_kreuzberg_is_not_imported_by_the_module() -> None:
    assert "kreuzberg" not in sys.modules


# --- fila -------------------------------------------------------------------


def test_queue_holds_only_norms_the_reader_does_not_close_in_stable_order() -> None:
    rows = [
        _row(11, OPEN),
        _row(7, CLOSING),  # fecha: fora
        _row(9, MANY_OPEN),
        {**_row(12, OPEN), "texto": ""},  # sem texto: fora
        {**_row(13, OPEN), "pdf_url": None},  # sem PDF: fora
    ]
    queue, stats = _queue(rows)
    assert [q["numero"] for q in queue] == [9, 11]
    assert [q["_artigos_ia"] for q in queue] == [6, 1]
    assert (stats.examinadas, stats.nao_fecham, stats.na_fila) == (3, 2, 2)


def test_queue_skips_norms_already_attempted_with_same_pdf_and_engine() -> None:
    row = _row(9, MANY_OPEN)
    queue, _ = _queue([row])
    done = reocr.run_reocr(
        queue,
        stats=reocr.ReocrStats(),
        fetch=_fetch,
        ocr=_ocr_returning(OPEN),
        kreuzberg_version=KZ,
    )
    assert done[0]["aceito"] is False
    again, stats = _queue([row], done)
    assert again == [] and stats.ja_tentadas == 1
    # PDF diferente (captura nova) volta à fila
    changed = {**row, "sha256_fonte": "outro"}
    assert len(_queue([changed], done)[0]) == 1
    # motor/versão diferente também
    bumped = [{**done[0], "kreuzberg_version": "9.9.9"}]
    assert len(_queue([row], bumped)[0]) == 1


def test_oversized_attempt_is_retried_only_when_max_pages_grows() -> None:
    row = _row(9, MANY_OPEN)
    attempt = {
        **reocr._base_row(row, KZ),
        "motivo": reocr.EXCEDE_PAGINAS,
        "paginas": 60,
    }
    stats = reocr.ReocrStats()
    assert not reocr.select_queue(
        [row], [attempt], kreuzberg_version=KZ, max_pages=40, stats=stats
    )
    assert reocr.select_queue([row], [attempt], kreuzberg_version=KZ, max_pages=80)


# --- portão -----------------------------------------------------------------


def _attempt(ia_text: str, new_text: str, **kw: Any) -> dict[str, Any]:
    queue, stats = _queue([_row(9, ia_text)])
    return reocr.run_reocr(
        queue,
        stats=stats,
        fetch=kw.get("fetch", _fetch),
        ocr=_ocr_returning(new_text),
        kreuzberg_version=KZ,
    )[0]


def test_gate_accepts_closing_text_with_at_least_as_many_articles() -> None:
    row = _attempt(OPEN, CLOSING)
    assert row["aceito"] is True and row["motivo"] == reocr.ACEITO
    assert (row["artigos_ia"], row["artigos_novo"]) == (1, 3)
    assert (row["fecha_ia"], row["fecha_novo"]) == (False, True)
    assert row["texto"] == CLOSING
    assert row["sha256_texto"] == hashlib.sha256(CLOSING.encode()).hexdigest()
    assert row["engine"] == "paddleocr" and row["kreuzberg_version"] == KZ
    assert row["paginas"] == 2 and row["segundos"] is not None


def test_gate_rejects_text_that_still_does_not_close() -> None:
    row = _attempt(OPEN, MANY_OPEN)
    assert row["aceito"] is False and row["motivo"] == reocr.NAO_FECHA
    assert row["texto"] is None and row["sha256_texto"] is not None


def test_gate_rejects_closing_text_with_fewer_articles_than_ia() -> None:
    row = _attempt(MANY_OPEN, SHORT_CLOSING)
    assert row["aceito"] is False and row["motivo"] == reocr.MENOS_ARTIGOS
    assert (row["artigos_ia"], row["artigos_novo"]) == (6, 2)
    assert row["texto"] is None


def test_pdf_hash_mismatch_empty_ocr_and_ocr_error_are_recorded_as_rejections() -> None:
    mismatch = _attempt(OPEN, CLOSING, fetch=lambda u: b"outro pdf")
    assert mismatch["motivo"] == reocr.PDF_DIVERGE and not mismatch["aceito"]
    assert _attempt(OPEN, "   \n")["motivo"] == reocr.OCR_VAZIO

    def boom(pdf: bytes, max_pages: int) -> reocr.OcrOutcome:
        raise RuntimeError("pdftoppm quebrou")

    queue, stats = _queue([_row(9, OPEN)])
    failed = reocr.run_reocr(
        queue, stats=stats, fetch=_fetch, ocr=boom, kreuzberg_version=KZ
    )
    assert failed[0]["motivo"] == reocr.OCR_FALHOU and not failed[0]["aceito"]


def test_too_many_pages_is_counted_and_recorded_without_text() -> None:
    def big(pdf: bytes, max_pages: int) -> reocr.OcrOutcome:
        raise reocr.TooManyPages(99)

    queue, stats = _queue([_row(9, OPEN)])
    out = reocr.run_reocr(
        queue, stats=stats, fetch=_fetch, ocr=big, kreuzberg_version=KZ
    )
    assert out[0]["motivo"] == reocr.EXCEDE_PAGINAS and out[0]["paginas"] == 99
    assert stats.grandes == 1 and stats.aceitas == 0


def test_download_failure_is_not_an_attempt_and_limit_truncates() -> None:
    rows = [_row(9, OPEN), _row(11, OPEN), _row(12, OPEN)]
    queue, stats = _queue(rows)
    out = reocr.run_reocr(
        queue,
        stats=stats,
        limit=1,
        fetch=lambda u: None,
        ocr=_ocr_returning(CLOSING),
        kreuzberg_version=KZ,
    )
    assert out == [] and len(stats.failures) == 3  # falha não consome o limite

    queue, stats = _queue(rows)
    out = reocr.run_reocr(
        queue,
        stats=stats,
        limit=2,
        fetch=_fetch,
        ocr=_ocr_returning(CLOSING),
        kreuzberg_version=KZ,
    )
    assert [r["numero"] for r in out] == [9, 11] and stats.truncated


# --- parquet / sobreposição ---------------------------------------------------


def _accepted_rows() -> list[dict[str, Any]]:
    queue, stats = _queue([_row(9, OPEN), _row(11, MANY_OPEN)])
    return reocr.run_reocr(
        queue,
        stats=stats,
        fetch=_fetch,
        ocr=_ocr_returning(CLOSING),  # 9: aceita; 11: 3 < 6 artigos, rejeitada
        kreuzberg_version=KZ,
    )


def test_parquet_roundtrip_validation_and_accepted_loading(tmp_path: Path) -> None:
    rows = _accepted_rows()
    assert [r["aceito"] for r in rows] == [True, False]
    path = tmp_path / "reocr.parquet"
    reocr.write_reocr_parquet(rows, path)
    assert reocr.validate_reocr_parquet(path) == []
    accepted = reocr.load_accepted(path)
    assert list(accepted) == [rows[0]["texto_id"]]
    assert accepted[rows[0]["texto_id"]]["texto"] == CLOSING
    meta = reocr.build_reocr_meta(path, "ro", 0, "20261116t000000z")
    assert meta["table"] == "reocr" and meta["row_count"] == 2
    assert meta["rows_aceitas"] == 1

    bad = [{**rows[1], "texto": "vazou"}, {**rows[0], "sha256_texto": "x"}]
    bad_path = tmp_path / "bad.parquet"
    reocr.write_reocr_parquet(bad, bad_path)
    problems = reocr.validate_reocr_parquet(bad_path)
    assert any("rejeitado" in p for p in problems)
    assert any("sha256_texto" in p for p in problems)
    assert reocr.load_accepted(bad_path) == {}  # texto adulterado nunca sobrepõe


def test_load_accepted_is_fail_open(tmp_path: Path) -> None:
    assert reocr.load_accepted(tmp_path / "nao-existe.parquet") == {}
    garbage = tmp_path / "g.parquet"
    garbage.write_bytes(b"not parquet")
    assert reocr.load_accepted(garbage) == {}


def test_merge_keeps_history_and_replaces_same_attempt() -> None:
    rows = _accepted_rows()
    newer = {**rows[1], "tentado_em": "2999-01-01T00:00:00+00:00", "segundos": 99.0}
    merged = reocr.merge_attempts(rows, [newer])
    assert len(merged) == 2
    assert [m for m in merged if m["texto_id"] == newer["texto_id"]][0][
        "segundos"
    ] == 99.0


def _textos_row(n: int, text: str) -> dict[str, Any]:
    return textlayer.build_row(
        ente="ro",
        fonte="casacivil",
        tipo="lei",
        numero=n,
        rendicao="",
        sha256_fonte=_row(n, text)["sha256_fonte"],
        capturado_em="2026-01-01",
        ia_item="leizilla_ro_casacivil_lei_0001-1000",
        pdf_name=f"{n}.pdf",
        texto_name=f"{n}_djvu.txt",
        text_bytes=text.encode(),
        ocr_motor="tesseract 5.3.0",
        sha1_texto_ia="abc",
    )


def test_overlay_replaces_text_for_accepted_rows_only() -> None:
    rows = [_textos_row(9, OPEN), _textos_row(11, MANY_OPEN)]
    accepted = {r["texto_id"]: r for r in _accepted_rows() if r["aceito"]}
    applied = textlayer.apply_reocr_overlay(rows, accepted)
    assert applied == 1
    won, kept = rows
    assert won["texto"] == CLOSING and won["artigos_fecham"] is True
    assert won["ocr_motor"] == textlayer.REOCR_MOTOR
    assert won["ocr_modulo_versao"] == KZ and won["sha1_texto_ia"] is None
    assert won["sha256_texto"] == hashlib.sha256(CLOSING.encode()).hexdigest()
    assert won["texto_url"].endswith("9_djvu.txt")  # elo com o texto do IA
    assert kept["texto"] == MANY_OPEN and kept["ocr_motor"] == "tesseract 5.3.0"


def test_overlay_ignores_reocr_of_a_different_pdf() -> None:
    row = _textos_row(9, OPEN)
    accepted = {r["texto_id"]: r for r in _accepted_rows() if r["aceito"]}
    row["sha256_fonte"] = "captura-nova"
    assert textlayer.apply_reocr_overlay([row], accepted) == 0
    assert row["texto"] == OPEN


# --- build-textos: sobreposição de ponta a ponta --------------------------------


def _build_with(reocr_path: Optional[Path], tmp_path: Path) -> list[dict[str, Any]]:
    out = tmp_path / "t.parquet"
    args = ["build-textos", "--output", str(out), "--fontes", "casacivil"]
    if reocr_path is not None:
        args += ["--reocr", str(reocr_path)]
    with (
        patch("leizilla.textlayer.http_get", _default_ia()),
        patch("leizilla.textlayer.time.sleep"),
        patch("leizilla.publisher.scrape_identifiers", return_value=[_ITEM]),
        patch("leizilla.publisher.fetch_existing_index", return_value=_INDEX),
    ):
        result = _runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return list(textlayer.read_textos_parquet(out).values())


def _reocr_parquet_for_lei_9(tmp_path: Path, accepted: bool) -> Path:
    """reocr.parquet com tentativa sobre a lei 9 (sha-9 no INDEX do test_textlayer)."""
    text = CLOSING
    row = {
        **reocr._base_row(_row(9, ""), KZ),
        "texto_id": "leizilla-raw-ro-casacivil-lei-00009",
        "sha256_fonte": "sha-9",
        "sha256_pdf": "sha-9",
        "aceito": accepted,
        "motivo": reocr.ACEITO if accepted else reocr.NAO_FECHA,
        "paginas": 1,
        "artigos_ia": 2,
        "artigos_novo": 3,
        "fecha_ia": False,
        "fecha_novo": accepted,
        "segundos": 1.0,
        "sha256_texto": hashlib.sha256(text.encode()).hexdigest(),
        "num_caracteres": len(text),
        "texto": text if accepted else None,
    }
    path = tmp_path / "reocr.parquet"
    reocr.write_reocr_parquet([row], path)
    return path


def test_build_textos_prefers_accepted_reocr_and_records_origin(
    tmp_path: Path,
) -> None:
    rows = _build_with(_reocr_parquet_for_lei_9(tmp_path, True), tmp_path)
    by_id = {r["texto_id"]: r for r in rows}
    lei9 = by_id["leizilla-raw-ro-casacivil-lei-00009"]
    assert lei9["texto"] == CLOSING and lei9["ocr_motor"] == textlayer.REOCR_MOTOR
    assert lei9["artigos_fecham"] is True
    lei7 = by_id["leizilla-raw-ro-casacivil-lei-00007"]
    assert lei7["ocr_motor"] != textlayer.REOCR_MOTOR


def test_build_textos_ignores_rejected_and_missing_reocr(tmp_path: Path) -> None:
    baseline = _build_with(None, tmp_path)
    rejected = _build_with(_reocr_parquet_for_lei_9(tmp_path, False), tmp_path)
    missing = _build_with(tmp_path / "nao-existe.parquet", tmp_path)
    assert rejected == baseline and missing == baseline
    lei9 = {r["texto_id"]: r for r in baseline}["leizilla-raw-ro-casacivil-lei-00009"]
    assert lei9["texto"] == _TL_OPEN.decode()


# --- CLI ------------------------------------------------------------------------


def _write_textos(tmp_path: Path) -> Path:
    path = tmp_path / "textos.parquet"
    textlayer.write_textos_parquet(
        [_textos_row(7, CLOSING), _textos_row(9, OPEN), _textos_row(11, MANY_OPEN)],
        path,
    )
    return path


def test_cli_reocr_dry_run_lists_queue_without_ocr_or_download(
    tmp_path: Path,
) -> None:
    textos = _write_textos(tmp_path)
    with (
        patch("leizilla.reocr.fetch_published_reocr", return_value=False),
        patch("leizilla.reocr.run_reocr") as run,
    ):
        result = _runner.invoke(
            app, ["reocr", "--textos", str(textos), "--dry-run", "--limit", "5"]
        )
    assert result.exit_code == 0, result.output
    assert "2 na fila" in result.output and "lei-00009" in result.output
    assert not run.called


def test_cli_reocr_writes_incremental_parquet_and_skips_done_norms(
    tmp_path: Path,
) -> None:
    textos = _write_textos(tmp_path)
    out = tmp_path / "reocr.parquet"
    row9, row11 = _row(9, OPEN), _row(11, MANY_OPEN)

    def fake_ocr(pdf: bytes, max_pages: int) -> reocr.OcrOutcome:
        return reocr.OcrOutcome(CLOSING, 2, KZ)

    rows = {r["texto_id"]: r for r in textlayer.read_textos_parquet(textos).values()}
    # os sha256_fonte de _textos_row já são os de _pdf(n); a URL é a do build_row
    assert rows[row9["texto_id"]]["sha256_fonte"] == row9["sha256_fonte"]
    assert rows[row11["texto_id"]]["sha256_fonte"] == row11["sha256_fonte"]

    def fetch(url: str) -> Optional[bytes]:
        n = int(url.rsplit("/", 1)[-1].split(".")[0])
        return _pdf(n)

    common = [
        patch("leizilla.reocr.fetch_published_reocr", return_value=False),
        patch("leizilla.reocr.installed_kreuzberg_version", return_value=KZ),
        patch("leizilla.reocr.ocr_pdf", fake_ocr),
        patch("leizilla.textlayer.http_get", fetch),
    ]
    for p in common:
        p.start()
    try:
        first = _runner.invoke(
            app, ["reocr", "--textos", str(textos), "--output", str(out)]
        )
        assert first.exit_code == 0, first.output
        attempts = reocr.read_reocr_parquet(out)
        assert {a["numero"]: a["motivo"] for a in attempts} == {
            9: reocr.ACEITO,
            11: reocr.MENOS_ARTIGOS,
        }
        assert reocr.validate_reocr_parquet(out) == []

        # segunda execução com o histórico: nada a tentar
        second = _runner.invoke(
            app,
            [
                "reocr",
                "--textos",
                str(textos),
                "--previous",
                str(out),
                "--output",
                str(tmp_path / "again.parquet"),
            ],
        )
        assert second.exit_code == 0, second.output
        assert "Fila vazia" in second.output
        assert not (tmp_path / "again.parquet").exists()
    finally:
        for p in common:
            p.stop()


def test_cli_reocr_upload_goes_through_publisher_after_the_gate(
    tmp_path: Path,
) -> None:
    textos = _write_textos(tmp_path)
    out = tmp_path / "reocr.parquet"

    def fetch(url: str) -> Optional[bytes]:
        return _pdf(int(url.rsplit("/", 1)[-1].split(".")[0]))

    with (
        patch("leizilla.reocr.fetch_published_reocr", return_value=False),
        patch("leizilla.reocr.installed_kreuzberg_version", return_value=KZ),
        patch("leizilla.reocr.ocr_pdf", _ocr_returning(CLOSING)),
        patch("leizilla.textlayer.http_get", fetch),
        patch.object(
            publisher.InternetArchivePublisher,
            "upload_reocr",
            return_value={
                "success": True,
                "ia_url": "https://archive.org/details/x",
                "latest_pointer": {"success": True, "ia_url": "u"},
            },
        ) as upload,
    ):
        result = _runner.invoke(
            app,
            ["reocr", "--textos", str(textos), "--output", str(out), "--upload"],
        )
    assert result.exit_code == 0, result.output
    assert upload.call_count == 1
    assert upload.call_args.args[2:] == ("ro", 0)


def test_cli_reocr_aborts_when_previous_history_cannot_be_read(
    tmp_path: Path,
) -> None:
    textos = _write_textos(tmp_path)
    with patch("leizilla.reocr.fetch_published_reocr", side_effect=OSError("rede")):
        result = _runner.invoke(app, ["reocr", "--textos", str(textos)])
    assert result.exit_code == 1 and "abortando" in result.output


def test_cli_reocr_rejects_sleep_below_one_second(tmp_path: Path) -> None:
    result = _runner.invoke(
        app, ["reocr", "--textos", str(_write_textos(tmp_path)), "--sleep", "0.2"]
    )
    assert result.exit_code == 1


def test_upload_reocr_uses_dedicated_items(tmp_path: Path) -> None:
    assert (
        publisher.reocr_item_identifier("ro", 0, "latest")
        == "leizilla-reocr-ro-v0-latest"
    )
    parquet = tmp_path / "reocr.parquet"
    reocr.write_reocr_parquet(_accepted_rows(), parquet)
    meta = reocr.build_reocr_meta(parquet, "ro", 0, "20261116t000000z")
    pub = publisher.InternetArchivePublisher.__new__(publisher.InternetArchivePublisher)
    pub.access_key, pub.secret_key = "a", "b"
    calls: list[list[str]] = []
    with patch.object(pub, "_run_ia_upload", side_effect=calls.append):
        result = pub.upload_reocr(parquet, meta, "ro", 0)
    assert result["success"] and result["ia_id"] == (
        "leizilla-reocr-ro-v0-20261116t000000z"
    )
    assert [c[2] for c in calls] == [
        "leizilla-reocr-ro-v0-20261116t000000z",
        "leizilla-reocr-ro-v0-latest",
    ]
    assert all("--no-derive" in c for c in calls)
    assert any(a.endswith("reocr.parquet") for a in calls[0])


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("u", code, "x", None, None)  # type: ignore[arg-type]


def test_fetch_published_reocr_503_on_missing_item_is_first_run(
    tmp_path: Path,
) -> None:
    """IA answers 503, not 404, to /download/ of an item that never existed."""
    meta = MagicMock()
    meta.__enter__.return_value.read.return_value = b"{}"
    with patch(
        "leizilla.reocr.urllib.request.urlopen",
        side_effect=[_http_error(503), meta],
    ):
        assert reocr.fetch_published_reocr("ro", 0, tmp_path / "r.parquet") is False


def test_fetch_published_reocr_503_on_existing_item_aborts(tmp_path: Path) -> None:
    meta = MagicMock()
    meta.__enter__.return_value.read.return_value = b'{"files": []}'
    with (
        patch(
            "leizilla.reocr.urllib.request.urlopen",
            side_effect=[_http_error(503), meta],
        ),
        pytest.raises(OSError, match="HTTP 503"),
    ):
        reocr.fetch_published_reocr("ro", 0, tmp_path / "r.parquet")


def test_fetch_published_reocr_metadata_unreachable_aborts(tmp_path: Path) -> None:
    with (
        patch(
            "leizilla.reocr.urllib.request.urlopen",
            side_effect=[_http_error(503), urllib.error.URLError("down")],
        ),
        pytest.raises(OSError, match="HTTP 503"),
    ):
        reocr.fetch_published_reocr("ro", 0, tmp_path / "r.parquet")


# --- ordem da fila ----------------------------------------------------------

ZERO = "LEI N. 3\n\nDispõe sobre nada.\n"  # sem artigos: não fecha, lê zero


def test_queue_puts_norms_with_own_articles_first_then_zero_article_ones() -> None:
    rows = [_row(1, ZERO), _row(11, OPEN), _row(3, ZERO), _row(9, MANY_OPEN)]
    queue, stats = _queue(rows)
    assert [q["numero"] for q in queue] == [9, 11, 1, 3]
    assert [q["_artigos_ia"] for q in queue] == [6, 1, 0, 0]
    assert (stats.fila_com_artigos, stats.fila_sem_artigos) == (2, 2)
    assert stats.na_fila == 4


def test_cli_reocr_dry_run_prints_the_class_sizes_in_the_fila_line(
    tmp_path: Path,
) -> None:
    textos = _write_textos(tmp_path)
    with patch("leizilla.reocr.fetch_published_reocr", return_value=False):
        result = _runner.invoke(app, ["reocr", "--textos", str(textos), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "2 na fila (2 com artigos lidos primeiro · 0 sem artigos)" in result.output


# --- espera por fila cheia do IA -------------------------------------------

QUEUE_FULL = (
    "Please reduce your request rate. - total_tasks_queued exceeds global_limit"
)
BUCKET_FULL = "error: bucket_tasks_queued exceeds rationed amount"
RESET = "connection reset by peer"


def _ia_fail(stderr: str) -> subprocess.CalledProcessError:
    return subprocess.CalledProcessError(1, ["ia", "upload"], stderr=stderr)


def _pub() -> publisher.InternetArchivePublisher:
    pub = publisher.InternetArchivePublisher.__new__(publisher.InternetArchivePublisher)
    pub.access_key, pub.secret_key = "a", "b"
    pub._upload_rate_limiter = MagicMock()
    return pub


def _sleeps(sleep: MagicMock) -> list[float]:
    return [c.args[0] for c in sleep.call_args_list]


def test_queue_full_is_waited_out_within_the_budget() -> None:
    budget = publisher.IaQueueWait(budget_s=3600)
    outcomes = [_ia_fail(QUEUE_FULL), _ia_fail(BUCKET_FULL), MagicMock()]
    with (
        patch("leizilla.publisher.subprocess.run", side_effect=outcomes) as run,
        patch("leizilla.publisher.time.sleep") as sleep,
    ):
        _pub()._run_ia_upload(["ia", "upload", "x"], queue_wait=budget)
    assert run.call_count == 3
    assert _sleeps(sleep) == [60.0, 120.0]
    assert budget.waited_s == 180.0


def test_queue_full_gives_up_when_the_budget_is_exhausted() -> None:
    budget = publisher.IaQueueWait(budget_s=200)
    with (
        patch(
            "leizilla.publisher.subprocess.run", side_effect=_ia_fail(QUEUE_FULL)
        ) as run,
        patch("leizilla.publisher.time.sleep") as sleep,
        pytest.raises(subprocess.CalledProcessError),
    ):
        _pub()._run_ia_upload(["ia", "upload", "x"], queue_wait=budget)
    # 60 + 120 + o que sobra (20) = 200 s; a próxima espera não existe.
    assert _sleeps(sleep) == [60.0, 120.0, 20.0]
    assert run.call_count == 4
    assert budget.remaining_s == 0


def test_other_errors_keep_the_short_retry_even_with_a_budget() -> None:
    budget = publisher.IaQueueWait(budget_s=3600)
    with (
        patch("leizilla.publisher.subprocess.run", side_effect=_ia_fail(RESET)) as run,
        patch("leizilla.publisher.time.sleep") as sleep,
        pytest.raises(subprocess.CalledProcessError),
    ):
        _pub()._run_ia_upload(["ia", "upload", "x"], queue_wait=budget)
    assert run.call_count == publisher._IA_UPLOAD_MAX_ATTEMPTS
    delays = _sleeps(sleep)
    assert len(delays) == publisher._IA_UPLOAD_MAX_ATTEMPTS - 1
    for got, base in zip(delays, [2.0, 4.0, 8.0, 16.0]):
        assert base <= got <= base * 1.25
    assert budget.waited_s == 0


def test_queue_full_without_a_budget_keeps_the_short_retry() -> None:
    with (
        patch(
            "leizilla.publisher.subprocess.run", side_effect=_ia_fail(QUEUE_FULL)
        ) as run,
        patch("leizilla.publisher.time.sleep") as sleep,
        pytest.raises(subprocess.CalledProcessError),
    ):
        _pub()._run_ia_upload(["ia", "upload", "x"])
    assert run.call_count == publisher._IA_UPLOAD_MAX_ATTEMPTS
    assert all(d < 60 for d in _sleeps(sleep))


@pytest.mark.parametrize("throttled_item", [0, 1])
def test_upload_reocr_waits_out_a_throttle_on_either_item(
    tmp_path: Path, throttled_item: int
) -> None:
    parquet = tmp_path / "reocr.parquet"
    reocr.write_reocr_parquet(_accepted_rows(), parquet)
    meta = reocr.build_reocr_meta(parquet, "ro", 0, "20261116t000000z")
    ok = MagicMock()
    outcomes: list[Any] = []
    for i in range(2):  # 0 = datado, 1 = -latest
        if i == throttled_item:
            outcomes.append(_ia_fail(QUEUE_FULL))
        outcomes.append(ok)
    with (
        patch("leizilla.publisher.subprocess.run", side_effect=outcomes) as run,
        patch("leizilla.publisher.time.sleep") as sleep,
    ):
        result = _pub().upload_reocr(parquet, meta, "ro", 0, queue_wait_minutes=45)
    assert result["success"] and result["latest_pointer"]["success"]
    assert run.call_count == len(outcomes)
    assert _sleeps(sleep) == [60.0]


def test_upload_reocr_budget_is_shared_by_both_items(tmp_path: Path) -> None:
    parquet = tmp_path / "reocr.parquet"
    reocr.write_reocr_parquet(_accepted_rows(), parquet)
    meta = reocr.build_reocr_meta(parquet, "ro", 0, "20261116t000000z")
    # Dois itens, cada um com uma fila cheia de 60 s: 120 s no total, não 60 + 60.
    outcomes = [
        _ia_fail(QUEUE_FULL),
        MagicMock(),
        _ia_fail(QUEUE_FULL),
        MagicMock(),
    ]
    with (
        patch("leizilla.publisher.subprocess.run", side_effect=outcomes),
        patch("leizilla.publisher.time.sleep") as sleep,
    ):
        result = _pub().upload_reocr(parquet, meta, "ro", 0, queue_wait_minutes=2)
    assert result["success"] and result["latest_pointer"]["success"]
    assert _sleeps(sleep) == [60.0, 60.0]


def test_upload_reocr_with_zero_wait_keeps_the_old_behaviour(tmp_path: Path) -> None:
    parquet = tmp_path / "reocr.parquet"
    reocr.write_reocr_parquet(_accepted_rows(), parquet)
    meta = reocr.build_reocr_meta(parquet, "ro", 0, "20261116t000000z")
    outcomes = [MagicMock()] + [
        _ia_fail(QUEUE_FULL)
    ] * publisher._IA_UPLOAD_MAX_ATTEMPTS
    with (
        patch("leizilla.publisher.subprocess.run", side_effect=outcomes),
        patch("leizilla.publisher.time.sleep") as sleep,
    ):
        result = _pub().upload_reocr(parquet, meta, "ro", 0, queue_wait_minutes=0)
    # Latest falha depois do recuo curto; a release imutável já existe.
    assert result["success"] and result["latest_pointer"]["success"] is False
    assert all(d < 60 for d in _sleeps(sleep))


def test_cli_reocr_upload_wait_defaults_to_45_and_zero_disables_it(
    tmp_path: Path,
) -> None:
    textos = _write_textos(tmp_path)
    out = tmp_path / "reocr.parquet"
    ok = {
        "success": True,
        "ia_url": "https://archive.org/details/x",
        "latest_pointer": {"success": True, "ia_url": "u"},
    }
    with (
        patch("leizilla.reocr.fetch_published_reocr", return_value=False),
        patch("leizilla.reocr.installed_kreuzberg_version", return_value=KZ),
        patch("leizilla.reocr.ocr_pdf", _ocr_returning(CLOSING)),
        patch("leizilla.textlayer.http_get", lambda url: _pdf(9)),
        patch.object(
            publisher.InternetArchivePublisher, "upload_reocr", return_value=ok
        ) as upload,
    ):
        base = ["reocr", "--textos", str(textos), "--output", str(out), "--upload"]
        assert _runner.invoke(app, base).exit_code == 0
        assert upload.call_args.kwargs["queue_wait_minutes"] == 45.0
        assert _runner.invoke(app, [*base, "--upload-wait-minutes", "0"]).exit_code == 0
        assert upload.call_args.kwargs["queue_wait_minutes"] == 0.0
        bad = _runner.invoke(app, [*base, "--upload-wait-minutes", "-1"])
        assert bad.exit_code == 1


def test_cli_reocr_exits_nonzero_when_only_the_latest_pointer_failed(
    tmp_path: Path,
) -> None:
    textos = _write_textos(tmp_path)
    out = tmp_path / "reocr.parquet"
    partial = {
        "success": True,
        "ia_url": "https://archive.org/details/leizilla-reocr-ro-v0-x",
        "latest_pointer": {"success": False, "error": "total_tasks_queued"},
    }
    with (
        patch("leizilla.reocr.fetch_published_reocr", return_value=False),
        patch("leizilla.reocr.installed_kreuzberg_version", return_value=KZ),
        patch("leizilla.reocr.ocr_pdf", _ocr_returning(CLOSING)),
        patch("leizilla.textlayer.http_get", lambda url: _pdf(9)),
        patch.object(
            publisher.InternetArchivePublisher, "upload_reocr", return_value=partial
        ),
    ):
        result = _runner.invoke(
            app,
            ["reocr", "--textos", str(textos), "--output", str(out), "--upload"],
        )
    assert result.exit_code == 1
    assert "Upload incompleto" in result.output
    assert "leizilla-reocr-ro-v0-x" in result.output
