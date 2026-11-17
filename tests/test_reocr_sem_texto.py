"""Fila ``sem-texto`` do re-OCR (ADR-0019) — offline; Kreuzberg nunca é importado."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch

import duckdb
import pytest
from typer.testing import CliRunner

from leizilla import publisher, reocr, textlayer
from leizilla.cli import app
from test_reocr import CLOSING, KZ, MANY_OPEN, OPEN, SHORT_CLOSING
from test_textlayer import INDEX, ITEM, FakeIA, _default_ia, _file, _metadata

import json

_runner = CliRunner()

LEI_11 = "leizilla-raw-ro-casacivil-lei-00011"


@pytest.fixture(autouse=True)
def _no_network_no_sleep() -> Any:
    with (
        patch("leizilla.reocr.time.sleep"),
        patch("leizilla.textlayer.time.sleep"),
        patch("leizilla.publisher.scrape_identifiers", return_value=[ITEM]),
        patch("leizilla.publisher.fetch_existing_index", return_value=INDEX),
    ):
        yield


def _fetch_ia() -> FakeIA:
    return FakeIA(_metadata(), {})


def _cand(n: int, tipo: str = "lei", **extra: Any) -> dict[str, Any]:
    pdf = f"%PDF sem-texto {tipo} {n}".encode()
    return {
        "texto_id": f"leizilla-raw-ro-casacivil-{tipo}-{n:05d}",
        "ente": "ro",
        "fonte": "casacivil",
        "tipo": tipo,
        "numero": n,
        "ia_item": ITEM,
        "pdf_url": f"https://archive.org/download/{ITEM}/{tipo}-{n}.pdf",
        "sha256_fonte": hashlib.sha256(pdf).hexdigest(),
        "capturado_em": "2026-01-01T00:00:00+00:00",
        "rendicao": "",
        **extra,
    }


def _fetch_pdf(url: str) -> Optional[bytes]:
    name = url.rsplit("/", 1)[-1][:-4]
    tipo, n = name.rsplit("-", 1)
    return f"%PDF sem-texto {tipo} {n}".encode()


def _ocr_returning(text: str, pages: int = 2) -> Any:
    def _ocr(pdf: bytes, max_pages: int) -> reocr.OcrOutcome:
        return reocr.OcrOutcome(text=text, pages=pages, kreuzberg_version=KZ)

    return _ocr


# --- enumeração ----------------------------------------------------------------


def test_collect_sem_texto_lists_only_preserved_pdfs_without_any_text() -> None:
    stats = textlayer.BuildStats()
    found = textlayer.collect_sem_texto(
        "ro", "casacivil", stats=stats, com_texto=set(), fetch=_fetch_ia()
    )
    # lei 7 e 9 têm _djvu.txt; lei 12 é html (sem PDF); só a 11 é PDF sem texto
    assert [f["texto_id"] for f in found] == [LEI_11]
    item = found[0]
    assert item["pdf_url"].endswith(f"{ITEM}/dddd4444.pdf")
    assert item["sha256_fonte"] == "sha-11"
    assert item["capturado_em"] == "2026-01-06T00:00:00+00:00"
    assert not stats.failures


def test_collect_sem_texto_skips_norms_already_in_textos() -> None:
    found = textlayer.collect_sem_texto(
        "ro",
        "casacivil",
        stats=textlayer.BuildStats(),
        com_texto={LEI_11},
        fetch=_fetch_ia(),
    )
    assert found == []


def test_enumerate_sem_texto_counts_only_rows_with_text_as_covered() -> None:
    covered = {"texto_id": LEI_11, "texto": "algo"}
    empty = {"texto_id": LEI_11, "texto": ""}
    with patch("leizilla.textlayer.http_get", _fetch_ia()):
        none, _ = reocr.enumerate_sem_texto("ro", ["casacivil"], [covered])
        some, _ = reocr.enumerate_sem_texto("ro", ["casacivil"], [empty])
    assert none == [] and [s["texto_id"] for s in some] == [LEI_11]


# --- fila: ordem e tentativas ----------------------------------------------------


def test_sem_texto_queue_is_newest_first_and_deterministic() -> None:
    cands = [
        _cand(5),
        _cand(9),
        _cand(300, "lc"),
        _cand(2),
        _cand(1000, "decreto"),  # sem ano no livro-razão: vai para o fim
    ]
    years = {
        _cand(5)["texto_id"]: 2020,
        _cand(9)["texto_id"]: 2020,
        _cand(300, "lc")["texto_id"]: 2024,
        _cand(2)["texto_id"]: 1985,
    }
    stats = reocr.ReocrStats()
    queue = reocr.select_sem_texto(
        cands, [], kreuzberg_version=KZ, years=years, stats=stats
    )
    assert [(q["tipo"], q["numero"]) for q in queue] == [
        ("lc", 300),
        ("lei", 9),  # mesmo ano: número maior primeiro
        ("lei", 5),
        ("lei", 2),
        ("decreto", 1000),
    ]
    assert all(q["_fila"] == "sem-texto" for q in queue)
    again = reocr.select_sem_texto(
        list(reversed(cands)), [], kreuzberg_version=KZ, years=years
    )
    assert [q["texto_id"] for q in again] == [q["texto_id"] for q in queue]
    assert (stats.sem_texto_enumeradas, stats.sem_texto_na_fila) == (5, 5)


def test_sem_texto_queue_without_catalog_orders_by_number_desc() -> None:
    queue = reocr.select_sem_texto(
        [_cand(3), _cand(30), _cand(10)], [], kreuzberg_version=KZ
    )
    assert [q["numero"] for q in queue] == [30, 10, 3]


def test_sem_texto_queue_skips_same_pdf_and_engine_only() -> None:
    cand = _cand(4)
    done = [
        {
            **reocr._base_row(cand, KZ),
            "fila": "sem-texto",
            "motivo": reocr.TEXTO_TRIVIAL,
        }
    ]
    stats = reocr.ReocrStats()
    assert reocr.select_sem_texto([cand], done, kreuzberg_version=KZ, stats=stats) == []
    assert stats.sem_texto_ja_tentadas == 1
    # outro Kreuzberg ou outro PDF: tenta de novo
    assert reocr.select_sem_texto([cand], done, kreuzberg_version="4.11.0")
    other = {**cand, "sha256_fonte": "outro-pdf"}
    assert reocr.select_sem_texto([other], done, kreuzberg_version=KZ)


def test_attempt_of_one_queue_blocks_the_same_pdf_in_the_other() -> None:
    # a chave de tentativa é (PDF, motor): o mesmo OCR não se repete por fila
    row = {
        "texto_id": _cand(4)["texto_id"],
        "pdf_url": "u",
        "sha256_fonte": _cand(4)["sha256_fonte"],
        "texto": MANY_OPEN,
    }
    done = [{**reocr._base_row(row, KZ), "fila": "sem-texto", "aceito": True}]
    queue = reocr.select_queue([row], done, kreuzberg_version=KZ)
    assert queue == []


# --- divisão do limite -----------------------------------------------------------


@pytest.mark.parametrize(
    ("limit", "n_sem", "n_nao", "expected"),
    [
        (None, 5, 7, (5, 7)),
        (6, 10, 10, (4, 2)),  # 2/3 para sem-texto
        (100, 1000, 1000, (66, 34)),
        (6, 1, 10, (1, 5)),  # sobra de sem-texto flui para nao-fecha
        (6, 10, 1, (5, 1)),  # sobra de nao-fecha flui para sem-texto
        (6, 0, 10, (0, 6)),
        (6, 10, 0, (6, 0)),
        (1, 3, 3, (1, 0)),
        (2, 3, 3, (1, 1)),  # nenhuma fila é zerada com limite >= 2
        (3, 3, 3, (2, 1)),
        (5, 0, 0, (0, 0)),
    ],
)
def test_split_limit(
    limit: Optional[int], n_sem: int, n_nao: int, expected: tuple[int, int]
) -> None:
    assert reocr.split_limit(limit, n_sem, n_nao) == expected
    if limit is not None:
        assert sum(expected) <= limit


def test_run_queues_runs_sem_texto_first_and_hands_unused_share_over() -> None:
    sem = [{**_cand(n), "_fila": "sem-texto"} for n in (1, 2)]
    nao = [
        {
            "texto_id": f"leizilla-raw-ro-casacivil-lei-{n:05d}",
            "ente": "ro",
            "fonte": "casacivil",
            "tipo": "lei",
            "numero": n,
            "ia_item": ITEM,
            "pdf_url": f"https://archive.org/download/{ITEM}/lei-{n}.pdf",
            "sha256_fonte": hashlib.sha256(
                f"%PDF sem-texto lei {n}".encode()
            ).hexdigest(),
            "texto": OPEN,
            "_artigos_ia": 1,
            "_fecha_ia": False,
        }
        for n in (50, 51, 52, 53, 54)
    ]
    stats = reocr.ReocrStats()
    rows = reocr.run_queues(
        sem,
        nao,
        stats=stats,
        limit=6,
        fetch=_fetch_pdf,
        ocr=_ocr_returning(CLOSING * 3),
        kreuzberg_version=KZ,
    )
    # 6 de limite: sem-texto teria 4 mas só tem 2; nao-fecha leva as outras 4
    assert [r["fila"] for r in rows] == ["sem-texto"] * 2 + ["nao-fecha"] * 4
    assert stats.tentadas == 6


# --- fatias ----------------------------------------------------------------------


def test_shards_are_disjoint_complete_and_stable() -> None:
    queue = [_cand(n) for n in range(1, 401)]
    parts = [reocr.in_shard(queue, (i, 4)) for i in range(4)]
    ids = [q["texto_id"] for part in parts for q in part]
    assert sorted(ids) == sorted(q["texto_id"] for q in queue)  # completa
    assert len(set(ids)) == len(ids)  # disjunta
    assert all(60 < len(p) < 140 for p in parts)  # equilibrada o bastante
    assert reocr.in_shard(queue, (0, 4)) == parts[0]  # estável
    # a fatia de uma norma não depende do resto da fila
    assert reocr.in_shard(queue[:10], (1, 4)) == [
        q for q in parts[1] if q in queue[:10]
    ]
    assert reocr.in_shard(queue, None) is queue


def test_parse_shard() -> None:
    assert reocr.parse_shard("2/4") == (2, 4)
    for bad in ("4/4", "a/b", "1", "-1/3", "0/0"):
        with pytest.raises(ValueError):
            reocr.parse_shard(bad)


# --- portão da fila sem-texto ----------------------------------------------------


def test_sem_texto_bar_accepts_legible_and_rejects_unreadable_text() -> None:
    good = reocr.judge_sem_texto("Art. 1º " + "palavra " * 60, pages=2)  # ~ 250/pág.
    assert good["aceito"] and good["motivo"] == reocr.ACEITO
    # piloto: página girada/ilegível (26 a 41 caracteres/página) é recusada
    junk = reocr.judge_sem_texto("e s - n\n\nn  e  rr e e r\n\n7..\n\no  0  8 o", 2)
    assert not junk["aceito"] and junk["motivo"] == reocr.TEXTO_TRIVIAL
    blank = reocr.judge_sem_texto(" \n\t  ", 3)
    assert not blank["aceito"] and blank["motivo"] == reocr.OCR_VAZIO


def test_sem_texto_bar_is_chars_per_page_not_total() -> None:
    text = "x" * 400
    assert reocr.judge_sem_texto(text, pages=2)["aceito"]  # 200/pág.
    assert not reocr.judge_sem_texto(text, pages=3)["aceito"]  # 133/pág.
    edge = "x" * (reocr.MIN_CHARS_POR_PAGINA * 2)
    assert reocr.judge_sem_texto(edge, pages=2)["aceito"]
    # espaços e quebras não contam
    assert not reocr.judge_sem_texto("x \n" * 200, pages=4)["aceito"]


def test_sem_texto_records_closure_but_does_not_require_it() -> None:
    padded = OPEN + "\n" + "texto corrido " * 40
    verdict = reocr.judge_sem_texto(padded, pages=1)
    assert verdict["aceito"] is True
    assert verdict["fecha_novo"] is False and verdict["artigos_novo"] == 1
    closing = reocr.judge_sem_texto(CLOSING + "texto corrido " * 40, pages=1)
    assert closing["aceito"] and closing["fecha_novo"] is True
    assert closing["artigos_novo"] == 3


def test_run_reocr_sem_texto_rows_carry_fila_text_and_closure() -> None:
    cands = [
        {**_cand(21), "_fila": "sem-texto"},
        {**_cand(22), "_fila": "sem-texto"},
    ]
    texts = {"21": CLOSING + "corpo do ato " * 30, "22": "e s n"}

    def ocr(pdf: bytes, max_pages: int) -> reocr.OcrOutcome:
        n = pdf.decode().rsplit(" ", 1)[-1]
        return reocr.OcrOutcome(texts[n], 1, KZ)

    stats = reocr.ReocrStats()
    rows = reocr.run_reocr(
        cands, stats=stats, fetch=_fetch_pdf, ocr=ocr, kreuzberg_version=KZ
    )
    ok, bad = rows
    assert ok["fila"] == "sem-texto" and ok["aceito"] is True
    assert ok["motivo"] == reocr.ACEITO and ok["texto"].startswith("LEI N. 7")
    assert ok["fecha_novo"] is True and ok["artigos_novo"] == 3
    assert ok["artigos_ia"] is None and ok["fecha_ia"] is None
    assert bad["aceito"] is False and bad["motivo"] == reocr.TEXTO_TRIVIAL
    assert bad["texto"] is None and bad["fecha_novo"] is False
    assert (stats.aceitas, stats.rejeitadas) == (1, 1)


def test_sem_texto_rows_round_trip_and_pass_the_release_gate(tmp_path: Path) -> None:
    cands = [{**_cand(21), "_fila": "sem-texto"}, {**_cand(22), "_fila": "sem-texto"}]
    rows = reocr.run_reocr(
        cands,
        stats=reocr.ReocrStats(),
        fetch=_fetch_pdf,
        ocr=_ocr_returning(CLOSING + "corpo do ato " * 30),
        kreuzberg_version=KZ,
    )
    out = tmp_path / "reocr.parquet"
    reocr.write_reocr_parquet(rows, out)
    assert reocr.validate_reocr_parquet(out) == []
    back = reocr.read_reocr_parquet(out)
    assert {r["fila"] for r in back} == {"sem-texto"}
    accepted = reocr.load_accepted(out)
    assert set(accepted) == {c["texto_id"] for c in cands}


# --- compatibilidade com o parquet já publicado (sem a coluna fila) ---------------


def _write_old_parquet(path: Path) -> None:
    """Parquet no contrato anterior: sem ``fila``."""
    old_schema = {c: t for c, t in reocr.REOCR_SCHEMA.items() if c != "fila"}
    text = CLOSING
    row: dict[str, Any] = {c: None for c in old_schema}
    row.update(
        texto_id="leizilla-raw-ro-casacivil-lei-00009",
        ente="ro",
        fonte="casacivil",
        tipo="lei",
        numero=9,
        ia_item=ITEM,
        pdf_url="u",
        sha256_fonte="sha-9",
        sha256_pdf="sha-9",
        paginas=1,
        engine=reocr.ENGINE,
        engine_version=reocr.ENGINE_VERSION,
        kreuzberg_version=KZ,
        parametros="p",
        aceito=True,
        motivo=reocr.ACEITO,
        artigos_ia=1,
        artigos_novo=3,
        fecha_ia=False,
        fecha_novo=True,
        segundos=1.0,
        tentado_em="2026-11-16T10:00:00+00:00",
        sha256_texto=hashlib.sha256(text.encode()).hexdigest(),
        num_caracteres=len(text),
        texto=text,
    )
    conn = duckdb.connect()
    try:
        conn.execute(
            "CREATE TABLE r ("
            + ", ".join(f"{c} {t}" for c, t in old_schema.items())
            + ")"
        )
        conn.execute(
            f"INSERT INTO r VALUES ({', '.join('?' for _ in old_schema)})",
            [row[c] for c in old_schema],
        )
        conn.execute(f"COPY r TO '{path}' (FORMAT parquet)")
    finally:
        conn.close()


def test_old_parquet_without_fila_loads_as_nao_fecha(tmp_path: Path) -> None:
    old = tmp_path / "old.parquet"
    _write_old_parquet(old)
    rows = reocr.read_reocr_parquet(old)
    assert [r["fila"] for r in rows] == ["nao-fecha"]
    accepted = reocr.load_accepted(old)
    assert accepted["leizilla-raw-ro-casacivil-lei-00009"]["fila"] == "nao-fecha"
    # histórico antigo + tentativa nova: o parquet unido cumpre o contrato novo
    new = reocr.run_reocr(
        [{**_cand(21), "_fila": "sem-texto"}],
        stats=reocr.ReocrStats(),
        fetch=_fetch_pdf,
        ocr=_ocr_returning(CLOSING + "corpo " * 50),
        kreuzberg_version=KZ,
    )
    merged = reocr.merge_attempts(rows, new)
    out = tmp_path / "merged.parquet"
    reocr.write_reocr_parquet(merged, out)
    assert reocr.validate_reocr_parquet(out) == []
    assert sorted(r["fila"] for r in reocr.read_reocr_parquet(out)) == [
        "nao-fecha",
        "sem-texto",
    ]


# --- IA vs. OCR próprio: as quatro combinações ------------------------------------

#  (IA fecha?, nosso fecha?) -> quem vale
_IA_FECHA, _IA_ABERTO = CLOSING, OPEN
_NOSSO_FECHA, _NOSSO_ABERTO = SHORT_CLOSING, MANY_OPEN


@pytest.mark.parametrize(
    ("ia_text", "own_text", "expected"),
    [
        (_IA_FECHA, _NOSSO_FECHA, textlayer.FONTE_IA),
        (_IA_FECHA, _NOSSO_ABERTO, textlayer.FONTE_IA),
        (_IA_ABERTO, _NOSSO_ABERTO, textlayer.FONTE_IA),
        (_IA_ABERTO, _NOSSO_FECHA, textlayer.FONTE_PROPRIA),
    ],
)
def test_choose_text_source_four_combinations(
    ia_text: str, own_text: str, expected: str
) -> None:
    assert textlayer.choose_text_source(ia_text, own_text) == expected


def _ia_row(text: str) -> dict[str, Any]:
    return textlayer.build_row(
        ente="ro",
        fonte="casacivil",
        tipo="lei",
        numero=11,
        rendicao="",
        sha256_fonte="sha-11",
        capturado_em="2026-01-06",
        ia_item=ITEM,
        pdf_name="dddd4444.pdf",
        texto_name="dddd4444_djvu.txt",
        text_bytes=text.encode(),
        ocr_motor="tesseract 5.3.0",
        sha1_texto_ia="abc",
    )


def _own_hit(text: str, fila: str = "sem-texto") -> dict[str, dict[str, Any]]:
    row = {
        **reocr._base_row(_cand(11), KZ),
        "texto_id": LEI_11,
        "fila": fila,
        "sha256_fonte": "sha-11",
        "aceito": True,
        "motivo": reocr.ACEITO,
        "texto": text,
        "sha256_texto": hashlib.sha256(text.encode()).hexdigest(),
    }
    return {LEI_11: row}


@pytest.mark.parametrize(
    ("ia_text", "own_text", "own_wins"),
    [
        (_IA_FECHA, _NOSSO_FECHA, False),
        (_IA_FECHA, _NOSSO_ABERTO, False),
        (_IA_ABERTO, _NOSSO_ABERTO, False),
        (_IA_ABERTO, _NOSSO_FECHA, True),
    ],
)
def test_overlay_sem_texto_hit_follows_the_decision_function(
    ia_text: str, own_text: str, own_wins: bool
) -> None:
    row = _ia_row(ia_text)
    applied = textlayer.apply_reocr_overlay([row], _own_hit(own_text))
    assert applied == int(own_wins)
    winner = own_text if own_wins else ia_text
    assert row["texto"] == winner
    assert (row["ocr_motor"] == textlayer.REOCR_MOTOR) is own_wins
    assert (row["sha1_texto_ia"] is None) is own_wins
    if own_wins:
        assert row["ocr_modulo_versao"] == KZ  # origem registrada como no overlay atual
        assert row["texto_url"].endswith("dddd4444_djvu.txt")


def test_overlay_nao_fecha_hit_still_replaces_without_the_decision() -> None:
    # a fila nao-fecha já passou no portão contra o texto do IA: comportamento de sempre
    row = _ia_row(_IA_ABERTO)
    assert (
        textlayer.apply_reocr_overlay([row], _own_hit(_NOSSO_ABERTO, "nao-fecha")) == 1
    )
    assert row["texto"] == _NOSSO_ABERTO


# --- camada de texto: linhas de sem-texto ---------------------------------------


def _build(reocr_rows: dict[str, dict[str, Any]], **kwargs: Any) -> Any:
    return textlayer.build_textos(
        "ro", ["casacivil"], fetch=_default_ia(), reocr=reocr_rows, **kwargs
    )


def test_text_layer_adds_a_row_for_an_accepted_sem_texto_ocr(tmp_path: Path) -> None:
    rows, stats = _build(_own_hit(CLOSING))
    by_id = {r["texto_id"]: r for r in rows}
    assert set(by_id) >= {LEI_11}
    own = by_id[LEI_11]
    assert own["texto"] == CLOSING and own["artigos_fecham"] is True
    assert own["ocr_motor"] == textlayer.REOCR_MOTOR
    assert own["ocr_modulo_versao"] == KZ
    assert own["texto_url"] is None and own["sha1_texto_ia"] is None
    assert own["pdf_url"].endswith(f"{ITEM}/dddd4444.pdf")
    assert own["sha256_fonte"] == "sha-11" and own["capturado_em"].startswith(
        "2026-01-06"
    )
    assert stats.reocr_sem_texto == 1 and stats.complete
    # a linha cumpre o gate de release da camada de texto
    out = tmp_path / "textos.parquet"
    textlayer.write_textos_parquet(rows, out)
    assert textlayer.validate_textos_parquet(out) == []


def test_text_layer_ignores_hits_that_do_not_apply() -> None:
    baseline, _ = _build({})
    assert LEI_11 not in {r["texto_id"] for r in baseline}
    # fila nao-fecha não cria linha onde o IA não tem texto
    nao_fecha, st = _build(_own_hit(CLOSING, "nao-fecha"))
    assert nao_fecha == baseline and st.reocr_sem_texto == 0
    # PDF diferente do preservado
    hit = _own_hit(CLOSING)
    hit[LEI_11]["sha256_fonte"] = "outro"
    other, st = _build(hit)
    assert other == baseline and st.reocr_sem_texto == 0


def test_own_row_is_kept_across_builds_without_the_reocr_dataset() -> None:
    first, _ = _build(_own_hit(CLOSING))
    previous = {r["texto_id"]: r for r in first}
    again, stats = _build({}, previous=previous)  # sem reocr.parquet agora
    assert LEI_11 in {r["texto_id"] for r in again}
    assert stats.mantidos == 1


@pytest.mark.parametrize(
    ("ia_text", "own_text", "own_wins"),
    [
        (CLOSING.encode(), SHORT_CLOSING, False),
        (CLOSING.encode(), MANY_OPEN, False),
        (OPEN.encode(), MANY_OPEN, False),
        (OPEN.encode(), SHORT_CLOSING, True),
    ],
)
def test_ia_text_arriving_later_wins_unless_only_ours_closes(
    ia_text: bytes, own_text: str, own_wins: bool
) -> None:
    first, _ = _build(_own_hit(own_text))
    previous = {r["texto_id"]: r for r in first}
    meta = json.loads(_metadata())
    meta["files"].append(_file("dddd4444_djvu.txt", ia_text))
    ia = FakeIA(
        json.dumps(meta).encode(),
        {
            "dddd4444_djvu.txt": ia_text,
            "lei-00007_bbbb2222_djvu.txt": CLOSING.encode(),
            "cccc3333_djvu.txt": OPEN.encode(),
        },
    )
    rows, stats = textlayer.build_textos(
        "ro", ["casacivil"], fetch=ia, previous=previous, reocr=_own_hit(own_text)
    )
    row = {r["texto_id"]: r for r in rows}[LEI_11]
    assert (row["ocr_motor"] == textlayer.REOCR_MOTOR) is own_wins
    assert row["texto"] == (own_text if own_wins else ia_text.decode())
    assert row["texto_url"].endswith("dddd4444_djvu.txt")  # há _djvu.txt agora
    assert stats.reocr_sem_texto == 0


# --- CLI -------------------------------------------------------------------------


def _textos_file(tmp_path: Path) -> Path:
    path = tmp_path / "textos.parquet"
    textlayer.write_textos_parquet(
        [_ia_row(CLOSING) | {"texto_id": "leizilla-raw-ro-casacivil-lei-00007"}],
        path,
    )
    return path


def test_cli_reocr_queue_sem_texto_end_to_end(tmp_path: Path) -> None:
    out = tmp_path / "reocr.parquet"
    cands = [_cand(21), _cand(22)]
    with (
        patch("leizilla.reocr.enumerate_sem_texto", return_value=(cands, [])),
        patch("leizilla.reocr.fetch_published_reocr", return_value=False),
        patch("leizilla.reocr.installed_kreuzberg_version", return_value=KZ),
        patch("leizilla.reocr.ocr_pdf", _ocr_returning(CLOSING * 40)),
        patch("leizilla.textlayer.http_get", _fetch_pdf),
    ):
        result = _runner.invoke(
            app,
            [
                "reocr",
                "--queue",
                "sem-texto",
                "--textos",
                str(_textos_file(tmp_path)),
                "--output",
                str(out),
                "--limit",
                "1",
            ],
        )
    assert result.exit_code == 0, result.output
    assert "Fila sem-texto" in result.output and "Fila nao-fecha" not in result.output
    rows = reocr.read_reocr_parquet(out)
    assert [(r["fila"], r["aceito"]) for r in rows] == [("sem-texto", True)]
    assert rows[0]["numero"] == 22  # sem ano: número maior primeiro
    assert reocr.validate_reocr_parquet(out) == []


def test_cli_reocr_rejects_bad_queue_and_shard_with_upload(tmp_path: Path) -> None:
    textos = str(_textos_file(tmp_path))
    bad_queue = _runner.invoke(app, ["reocr", "--textos", textos, "--queue", "x"])
    assert bad_queue.exit_code == 1 and "--queue" in bad_queue.output
    bad_shard = _runner.invoke(app, ["reocr", "--textos", textos, "--shard", "4/4"])
    assert bad_shard.exit_code == 1 and "--shard" in bad_shard.output
    upload = _runner.invoke(
        app, ["reocr", "--textos", textos, "--shard", "0/2", "--upload"]
    )
    assert upload.exit_code == 1 and "reocr-merge" in upload.output


def test_cli_reocr_shard_writes_only_its_own_new_attempts(tmp_path: Path) -> None:
    cands = [_cand(n) for n in range(1, 41)]
    textos = str(_textos_file(tmp_path))
    previous = tmp_path / "prev.parquet"
    _write_old_parquet(previous)
    expected = {c["texto_id"] for c in reocr.in_shard(cands, (1, 2))}
    out = tmp_path / "shard.parquet"
    with (
        patch("leizilla.reocr.enumerate_sem_texto", return_value=(cands, [])),
        patch("leizilla.reocr.installed_kreuzberg_version", return_value=KZ),
        patch("leizilla.reocr.ocr_pdf", _ocr_returning(CLOSING * 40)),
        patch("leizilla.textlayer.http_get", _fetch_pdf),
    ):
        result = _runner.invoke(
            app,
            [
                "reocr", "--queue", "sem-texto", "--shard", "1/2",
                "--textos", textos, "--previous", str(previous),
                "--output", str(out),
            ],
        )  # fmt: skip
    assert result.exit_code == 0, result.output
    rows = reocr.read_reocr_parquet(out)
    assert {r["texto_id"] for r in rows} == expected  # só as novas; sem o histórico


def test_cli_reocr_merge_joins_shards_with_previous_and_uploads_once(
    tmp_path: Path,
) -> None:
    previous = tmp_path / "prev.parquet"
    _write_old_parquet(previous)
    shard_files = []
    for i, ns in enumerate(([21, 22], [23])):
        rows = reocr.run_reocr(
            [{**_cand(n), "_fila": "sem-texto"} for n in ns],
            stats=reocr.ReocrStats(),
            fetch=_fetch_pdf,
            ocr=_ocr_returning(CLOSING * 40),
            kreuzberg_version=KZ,
        )
        path = tmp_path / f"shard-{i}.parquet"
        reocr.write_reocr_parquet(rows, path)
        shard_files.append(str(path))
    out = tmp_path / "merged.parquet"
    with patch.object(
        publisher.InternetArchivePublisher,
        "upload_reocr",
        return_value={
            "success": True,
            "ia_url": "https://archive.org/details/x",
            "latest_pointer": {"success": True, "ia_url": "u"},
        },
    ) as upload:
        result = _runner.invoke(
            app,
            [
                "reocr-merge", *shard_files,
                "--previous", str(previous),
                "--output", str(out), "--upload",
            ],
        )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert upload.call_count == 1
    merged = reocr.read_reocr_parquet(out)
    assert sorted((r["fila"], r["numero"]) for r in merged) == [
        ("nao-fecha", 9),
        ("sem-texto", 21),
        ("sem-texto", 22),
        ("sem-texto", 23),
    ]
    assert reocr.validate_reocr_parquet(out) == []


def test_cli_reocr_merge_aborts_when_previous_cannot_be_read(tmp_path: Path) -> None:
    shard = tmp_path / "s.parquet"
    reocr.write_reocr_parquet(
        reocr.run_reocr(
            [{**_cand(21), "_fila": "sem-texto"}],
            stats=reocr.ReocrStats(),
            fetch=_fetch_pdf,
            ocr=_ocr_returning(CLOSING * 40),
            kreuzberg_version=KZ,
        ),
        shard,
    )
    with patch("leizilla.reocr.fetch_published_reocr", side_effect=OSError("rede")):
        result = _runner.invoke(app, ["reocr-merge", str(shard)])
    assert result.exit_code == 1 and "abortando" in result.output


def test_kreuzberg_is_not_imported() -> None:
    assert "kreuzberg" not in sys.modules
