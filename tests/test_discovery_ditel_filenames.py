"""Regressões para identidade DITEL em filenames com descritores editoriais."""

import pytest

from leizilla.discovery import parse_filename


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("LC432 COMPILADA REVOGADA.pdf", ("lc", "lc-00432")),
        ("LC1076 - COMPILADO.pdf", ("lc", "lc-01076")),
        ("LC1056 - COMPILADA.pdf", ("lc", "lc-01056")),
        ("LC1078 REVOGADA.pdf", ("lc", "lc-01078")),
        ("L123 REVOGADO.pdf", ("lei", "lei-00123")),
    ],
)
def test_parse_filename_accepts_verified_ditel_editorial_suffixes(
    filename: str, expected: tuple[str, str]
) -> None:
    assert parse_filename(filename) == expected


@pytest.mark.parametrize(
    "filename",
    [
        "LC432 - PL.pdf",
        "LC432 ANEXO.pdf",
        "LC432 COMPILADA ANEXO.pdf",
        "L123 QUALQUER-COISA.pdf",
    ],
)
def test_parse_filename_rejects_unverified_suffixes(filename: str) -> None:
    assert parse_filename(filename) == (None, None)
