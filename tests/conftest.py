"""Shared pytest configuration."""

from typing import Iterator

import pytest


@pytest.fixture(autouse=True)
def _offline_casacivil_year_index(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep the Casa Civil year-index strategy off the network in every test.

    Tests that run the real RO manifest mock the strategies they know about; this
    strategy would otherwise make one paced live request per year and norm type.
    Tests of the strategy itself override ``_fetch`` on their own instance.
    """
    monkeypatch.setattr("leizilla.discovery._YEAR_INDEX_RATE_LIMIT_S", 0.0)
    monkeypatch.setattr(
        "leizilla.discovery.CasacivilYearIndexDiscovery._allowed",
        lambda self, url: True,
    )
    monkeypatch.setattr(
        "leizilla.discovery.CasacivilYearIndexDiscovery._fetch",
        lambda self, url: None,
    )
    yield
