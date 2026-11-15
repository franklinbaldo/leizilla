"""Camada de texto (ADR-0015): tabela ``textos`` — offline, IA todo mockado."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch

import duckdb
import pytest
from typer.testing import CliRunner

from leizilla import publisher, textlayer
from leizilla.cli import app

_runner = CliRunner()

ITEM = "leizilla_ro_casacivil_lei_0001-1000"
CLOSING = (
    "LEI N. 7, DE 1983\n\nDispõe sobre coisa alguma.\n\n"
    "Art. 1º Fica criada a coisa.\n"
    "Art. 22 A coisa será mantida.\n"  # "2º" lido pelo OCR como "22"
    "Art. 3º Esta Lei entra em vigor na data de sua publicação.\n"
).encode()
OPEN = "LEI N. 9\n\nArt. 1º Primeiro.\nArt. 5º Quinto, sem os do meio.\n".encode()

INDEX = (
    "tipo,numero,rendicao,formato,uuid5,sha256,captured_at,source\n"
    "lei,7,original,pdf,aaaa1111,sha-old,2026-01-01T00:00:00+00:00,u1\n"
    "lei,7,original,pdf,bbbb2222,sha-new,2026-02-01T00:00:00+00:00,u1\n"
    "lei,9,,pdf,cccc3333,sha-9,2026-01-05T00:00:00+00:00,u2\n"
    "lei,11,,pdf,dddd4444,sha-11,2026-01-06T00:00:00+00:00,u3\n"
    "lei,12,,html,eeee5555,sha-12,2026-01-07T00:00:00+00:00,u4\n"
)


def _file(name: str, data: Optional[bytes] = None, **extra: str) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": name, "mtime": "1789245941", **extra}
    if data is not None:
        entry["sha1"] = hashlib.sha1(data).hexdigest()
    return entry


def _metadata(include_new_ocr: bool = True) -> bytes:
    files = [
        _file("lei-00007_aaaa1111.pdf"),
        _file("lei-00007_aaaa1111_djvu.txt", OPEN),
        _file("lei-00007_bbbb2222.pdf"),
        _file("cccc3333.pdf", format="Text PDF"),
        _file("cccc3333_djvu.txt", OPEN),
        _file("history/files/cccc3333_djvu.txt", OPEN),
        _file("dddd4444.pdf"),  # sem OCR ainda: S2 sem S3
    ]
    if include_new_ocr:
        files += [
            _file("lei-00007_bbbb2222_djvu.txt", CLOSING),
            _file(
                "lei-00007_bbbb2222_chocr.html.gz",
                ocr="tesseract 5.3.0-6-g76ae",
                ocr_module_version="0.0.21",
                ocr_parameters="lang-por",
            ),
        ]
    return json.dumps({"files": files}).encode()


class FakeIA:
    """Fetcher determinístico: registra as URLs pedidas."""

    def __init__(self, metadata: bytes, texts: dict[str, Optional[bytes]]) -> None:
        self.metadata = metadata
        self.texts = texts
        self.calls: list[str] = []

    def __call__(self, url: str) -> Optional[bytes]:
        self.calls.append(url)
        if "/metadata/" in url:
            return self.metadata
        return self.texts.get(url.rsplit("/", 1)[-1])


@pytest.fixture(autouse=True)
def _no_network_no_sleep() -> Any:
    with (
        patch("leizilla.textlayer.time.sleep"),
        patch(
            "leizilla.publisher.scrape_identifiers",
            return_value=[ITEM, "leizilla_ro_casacivil_unidentified"],
        ),
        patch("leizilla.publisher.fetch_existing_index", return_value=INDEX),
    ):
        yield


def _build(ia: FakeIA, **kwargs: Any) -> tuple[list[dict[str, Any]], Any]:
    return textlayer.build_textos("ro", ["casacivil"], fetch=ia, **kwargs)


def _default_ia() -> FakeIA:
    return FakeIA(
        _metadata(),
        {"lei-00007_bbbb2222_djvu.txt": CLOSING, "cccc3333_djvu.txt": OPEN},
    )


def test_article_anchors_point_at_verbatim_markers() -> None:
    text = CLOSING.decode()
    anchors, closes, last = textlayer.article_anchors(text)
    assert closes is True and last == 3
    assert [a["n"] for a in anchors] == [1, 2, 3]
    assert [text[a["ini"] : a["fim"]] for a in anchors] == [
        "Art. 1º",
        "Art. 22",
        "Art. 3º",
    ]


def test_build_one_row_per_norm_newest_capture_with_text() -> None:
    ia = _default_ia()
    rows, stats = _build(ia)

    assert [r["texto_id"] for r in rows] == [
        "leizilla-raw-ro-casacivil-lei-00007",
        "leizilla-raw-ro-casacivil-lei-00009",
    ]
    assert stats.complete and stats.identidades == 3 and stats.com_texto == 2
    lei7 = rows[0]
    assert lei7["texto"] == CLOSING.decode()  # verbatim, com o erro de OCR
    assert lei7["sha256_fonte"] == "sha-new"
    assert lei7["capturado_em"] == "2026-02-01T00:00:00+00:00"
    assert lei7["sha256_texto"] == hashlib.sha256(CLOSING).hexdigest()
    assert lei7["pdf_url"] == (
        f"https://archive.org/download/{ITEM}/lei-00007_bbbb2222.pdf"
    )
    assert lei7["ocr_motor"] == "tesseract 5.3.0-6-g76ae"
    assert lei7["ocr_modulo_versao"] == "0.0.21"
    assert lei7["ocr_derivado_em"].startswith("2026-")
    assert lei7["qualidade"] == "texto-nao-estruturado"
    assert lei7["artigos_fecham"] is True and lei7["artigos_ultimo"] == 3
    assert rows[1]["artigos_fecham"] is False
    # Sem _chocr e com PDF "Text PDF": o texto veio da camada embutida, não de OCR.
    assert rows[1]["ocr_motor"] == textlayer.TEXT_LAYER_CONVERSION
    # history/ e a área _unidentified nunca são lidas.
    assert not any("history" in u or "unidentified" in u for u in ia.calls)


def test_build_falls_back_to_older_capture_while_newest_has_no_ocr() -> None:
    ia = FakeIA(
        _metadata(include_new_ocr=False),
        {"lei-00007_aaaa1111_djvu.txt": OPEN, "cccc3333_djvu.txt": OPEN},
    )
    rows, stats = _build(ia)
    assert rows[0]["sha256_fonte"] == "sha-old" and stats.complete


def test_build_reports_failed_download_as_partial() -> None:
    ia = FakeIA(_metadata(), {"cccc3333_djvu.txt": OPEN})
    rows, stats = _build(ia)
    assert [r["numero"] for r in rows] == [9]
    assert not stats.complete
    assert "download falhou" in stats.failures[0]


def test_build_rejects_text_whose_sha1_differs_from_ia() -> None:
    ia = FakeIA(
        _metadata(),
        {"lei-00007_bbbb2222_djvu.txt": b"corrompido", "cccc3333_djvu.txt": OPEN},
    )
    rows, stats = _build(ia)
    assert [r["numero"] for r in rows] == [9]
    assert "sha1 diverge" in stats.failures[0]


def test_build_fails_closed_when_listing_or_metadata_unavailable() -> None:
    with patch("leizilla.publisher.scrape_identifiers", return_value=None):
        rows, stats = _build(_default_ia())
    assert rows == [] and not stats.complete

    ia = _default_ia()
    ia.metadata = b"not json"
    rows, stats = _build(ia)
    assert rows == [] and "metadata indisponível" in stats.failures[0]

    with patch(
        "leizilla.publisher.fetch_existing_index",
        side_effect=publisher.IndexFetchError("boom"),
    ):
        rows, stats = _build(_default_ia())
    assert rows == [] and "index.csv" in stats.failures[0]


def test_limit_marks_result_partial() -> None:
    rows, stats = _build(_default_ia(), limit=1)
    assert len(rows) == 1 and stats.truncated and not stats.complete


def test_previous_rows_are_reused_without_download(tmp_path: Path) -> None:
    rows, _ = _build(_default_ia())
    out = tmp_path / "textos.parquet"
    textlayer.write_textos_parquet(rows, out)
    previous = textlayer.read_textos_parquet(out)

    ia = FakeIA(_metadata(), {})  # nenhum texto disponível para download
    again, stats = _build(ia, previous=previous)
    assert stats.complete and stats.reaproveitados == 2 and stats.baixados == 0
    assert again == rows
    assert all("/metadata/" in u for u in ia.calls)


def test_parquet_roundtrip_and_validation(tmp_path: Path) -> None:
    rows, _ = _build(_default_ia())
    out = tmp_path / "textos.parquet"
    textlayer.write_textos_parquet(rows, out)

    assert textlayer.validate_textos_parquet(out) == []
    conn = duckdb.connect()
    try:
        described = conn.execute(f"DESCRIBE SELECT * FROM '{out}'").fetchall()
        got = conn.execute(
            f"SELECT texto, ancoras FROM '{out}' ORDER BY texto_id"
        ).fetchall()
    finally:
        conn.close()
    assert {r[0]: r[1] for r in described} == textlayer.TEXTOS_SCHEMA
    assert got[0][0] == CLOSING.decode()
    assert [a["n"] for a in json.loads(got[0][1])] == [1, 2, 3]


def test_validation_catches_duplicates_and_bad_anchors(tmp_path: Path) -> None:
    rows, _ = _build(_default_ia())
    broken = dict(rows[1])
    broken["ancoras"] = json.dumps([{"n": 1, "sufixo": None, "ini": 5, "fim": 99999}])
    out = tmp_path / "bad.parquet"
    textlayer.write_textos_parquet([rows[0], rows[0], broken], out)
    problems = textlayer.validate_textos_parquet(out)
    assert any("duplicado" in p for p in problems)
    assert any("âncora" in p for p in problems)


def test_write_refuses_empty() -> None:
    with pytest.raises(ValueError):
        textlayer.write_textos_parquet([], Path("unused.parquet"))


# --- release ---------------------------------------------------------------


def _parquet(tmp_path: Path) -> Path:
    rows, _ = _build(_default_ia())
    out = tmp_path / "textos.parquet"
    textlayer.write_textos_parquet(rows, out)
    return out


def test_meta_describes_textos_table(tmp_path: Path) -> None:
    meta = textlayer.build_textos_meta(
        _parquet(tmp_path), "ro", 0, "20261114t000000z", "abc"
    )
    assert meta["table"] == "textos" and meta["row_count"] == 2
    assert meta["rows_artigos_fecham"] == 1 and meta["git_sha"] == "abc"
    assert meta["hash_parquet"].startswith("sha256:")


def test_floor_reads_textos_latest_item_not_versoes() -> None:
    with patch("leizilla.publisher._dataset_meta_row_count", return_value=7) as m:
        assert publisher.fetch_published_textos_row_count("ro", 0) == 7
    assert m.call_args[0][0] == "leizilla-textos-ro-v0-latest"


def test_upload_textos_publishes_release_and_latest(tmp_path: Path) -> None:
    p = _parquet(tmp_path)
    meta = textlayer.build_textos_meta(p, "ro", 0, "20261114t000000z")
    pub = publisher.InternetArchivePublisher()
    pub.access_key, pub.secret_key = "k", "s"
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> "subprocess.CompletedProcess[str]":
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    with patch.object(pub, "_run_ia_upload", side_effect=fake_run):
        result = pub.upload_textos(p, meta, "ro", 0)

    assert result["success"] and result["latest_pointer"]["success"]
    assert [c[2] for c in calls] == [
        "leizilla-textos-ro-v0-20261114t000000z",
        "leizilla-textos-ro-v0-latest",
    ]
    assert calls[0][3].endswith("textos.parquet")
    assert calls[0][4].endswith("dataset_meta.json")
    assert calls[1][5].endswith("latest.json")
    assert not any("leizilla-dataset" in part for c in calls for part in c)


def test_upload_textos_requires_credentials_and_valid_revision(tmp_path: Path) -> None:
    p = _parquet(tmp_path)
    pub = publisher.InternetArchivePublisher()
    pub.access_key, pub.secret_key = None, None
    assert pub.upload_textos(p, {"revision": "x"}, "ro")["success"] is False
    pub.access_key, pub.secret_key = "k", "s"
    with pytest.raises(ValueError):
        pub.upload_textos(p, {"revision": "latest"}, "ro")


def test_cli_release_rejects_candidate_below_floor(tmp_path: Path) -> None:
    p = _parquet(tmp_path)
    with (
        patch("leizilla.publisher.fetch_published_textos_row_count", return_value=3),
        patch("leizilla.publisher.InternetArchivePublisher.upload_textos") as upload,
    ):
        result = _runner.invoke(app, ["release-textos", str(p)])
    assert result.exit_code == 1
    assert "abaixo do piso publicado de 3" in result.output
    upload.assert_not_called()


def test_cli_release_fails_closed_when_floor_unknown(tmp_path: Path) -> None:
    p = _parquet(tmp_path)
    with (
        patch(
            "leizilla.publisher.fetch_published_textos_row_count",
            side_effect=publisher.DatasetFloorCheckError("HTTP 503"),
        ),
        patch("leizilla.publisher.InternetArchivePublisher.upload_textos") as upload,
    ):
        result = _runner.invoke(app, ["release-textos", str(p)])
    assert result.exit_code == 1
    upload.assert_not_called()


def test_cli_release_uploads_when_floor_holds(tmp_path: Path) -> None:
    p = _parquet(tmp_path)
    with (
        patch("leizilla.publisher.fetch_published_textos_row_count", return_value=2),
        patch(
            "leizilla.publisher.InternetArchivePublisher.upload_textos",
            return_value={
                "success": True,
                "ia_url": "https://x",
                "latest_pointer": {"success": True, "ia_url": "https://y"},
            },
        ) as upload,
        patch("leizilla.publisher.fetch_published_dataset_row_count") as versoes_floor,
    ):
        result = _runner.invoke(app, ["release-textos", str(p)])
    assert result.exit_code == 0, result.output
    upload.assert_called_once()
    versoes_floor.assert_not_called()


def test_cli_release_dry_run_and_contract_gate(tmp_path: Path) -> None:
    p = _parquet(tmp_path)
    with patch("leizilla.publisher.fetch_published_textos_row_count") as floor:
        result = _runner.invoke(app, ["release-textos", str(p), "--dry-run"])
    assert result.exit_code == 0 and "Dry-run" in result.output
    floor.assert_not_called()

    bad = tmp_path / "bad.parquet"
    conn = duckdb.connect()
    try:
        conn.execute(f"COPY (SELECT 1 AS x) TO '{bad}' (FORMAT parquet)")
    finally:
        conn.close()
    result = _runner.invoke(app, ["release-textos", str(bad)])
    assert result.exit_code == 1 and "contrato" in result.output


def test_cli_build_writes_parquet_and_refuses_partial(tmp_path: Path) -> None:
    out = tmp_path / "t.parquet"
    with patch("leizilla.textlayer.http_get", _default_ia()):
        ok = _runner.invoke(
            app, ["build-textos", "--output", str(out), "--fontes", "casacivil"]
        )
    assert ok.exit_code == 0, ok.output
    assert textlayer.validate_textos_parquet(out) == []

    partial_out = tmp_path / "p.parquet"
    with patch("leizilla.textlayer.http_get", FakeIA(_metadata(), {})):
        partial = _runner.invoke(
            app,
            ["build-textos", "--output", str(partial_out), "--fontes", "casacivil"],
        )
    assert partial.exit_code == 1 and not partial_out.exists()
