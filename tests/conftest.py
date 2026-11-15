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


@pytest.fixture(autouse=True)
def _offline_wayback_background_save(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep the harvest's background Save Page Now off the network in every test.

    ``harvest_pending_resources`` starts a ``wayback.BackgroundSaver`` thread by
    default (ADR-0016). Tests of that path pass their own saver explicitly; and
    even then the single network exit point is stubbed here, so a forgotten mock
    can never reach web.archive.org.
    """
    monkeypatch.setattr("leizilla.config.HARVEST_WAYBACK_SAVE", False)
    monkeypatch.setattr(
        "leizilla.wayback._background_save",
        lambda url, access_key, secret_key, timeout: None,
    )
    yield
