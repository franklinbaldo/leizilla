"""Testes unitários para leizilla.entes (catálogo de entes federativos)."""

import re

import pytest

from leizilla.entes import ENTES, Ente, get_ente, list_slugs

# 26 estados + DF (ISO 3166-2:BR)
EXPECTED_UFS = {
    "AC",
    "AL",
    "AM",
    "AP",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MG",
    "MS",
    "MT",
    "PA",
    "PB",
    "PE",
    "PI",
    "PR",
    "RJ",
    "RN",
    "RO",
    "RR",
    "RS",
    "SC",
    "SE",
    "SP",
    "TO",
}

KEBAB_CASE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def test_catalog_has_27_ufs_plus_federal() -> None:
    assert len(ENTES) == 28

    estaduais = [e for e in ENTES if e.tipo == "estadual"]
    assert len(estaduais) == 27
    assert {e.uf for e in estaduais} == EXPECTED_UFS

    federais = [e for e in ENTES if e.tipo == "federal"]
    assert len(federais) == 1
    assert federais[0].slug == "federal"
    assert federais[0].uf == "BR"


def test_slugs_are_kebab_case_lowercase() -> None:
    for ente in ENTES:
        assert KEBAB_CASE.fullmatch(ente.slug), f"Slug inválido: {ente.slug!r}"
        assert ente.slug == ente.slug.lower()


def test_slugs_are_unique() -> None:
    slugs = [e.slug for e in ENTES]
    assert len(slugs) == len(set(slugs))


def test_state_slugs_match_lowercase_uf() -> None:
    for ente in ENTES:
        if ente.tipo == "estadual":
            assert ente.slug == ente.uf.lower()


def test_get_ente_valid_slug() -> None:
    ro = get_ente("ro")
    assert isinstance(ro, Ente)
    assert ro.nome == "Rondônia"
    assert ro.tipo == "estadual"
    assert ro.uf == "RO"

    federal = get_ente("federal")
    assert federal.nome == "União Federal"
    assert federal.tipo == "federal"


def test_get_ente_invalid_slug_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        get_ente("xx")
    with pytest.raises(KeyError):
        get_ente("RO")  # lookup é case-sensitive; slugs são minúsculos


def test_list_slugs_matches_catalog() -> None:
    slugs = list_slugs()
    assert slugs == [e.slug for e in ENTES]
    assert "ro" in slugs
    assert "federal" in slugs
