"""Freshness contract for Casa Civil authoritative index discovery."""

from unittest.mock import MagicMock, patch

from leizilla.discovery import CasacivilIndexDiscovery


INDEX_URL = "https://ditel.casacivil.ro.gov.br/COTEL/Livros/"


def _live_response(html: str) -> MagicMock:
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = html.encode("utf-8")
    return response


@patch("leizilla.scraper.robots.is_allowed", return_value=True)
@patch("time.sleep")
@patch(
    "leizilla.wayback.closest_snapshot",
    return_value=(
        "https://web.archive.org/web/20200101000000/https://ditel.casacivil.ro.gov.br/COTEL/Livros/",
        "20200101000000",
    ),
)
@patch("leizilla.wayback.check_available", return_value=None)
@patch("urllib.request.urlopen")
def test_stale_snapshot_does_not_hide_new_live_law(
    mock_urlopen: MagicMock,
    mock_check_available: MagicMock,
    mock_closest_snapshot: MagicMock,
    _mock_sleep: MagicMock,
    _mock_robots: MagicMock,
) -> None:
    """An old preserved index is provenance, not an authoritative current listing."""
    mock_urlopen.return_value = _live_response(
        '<html><body><a href="Files/L6002.pdf">Lei 6002</a></body></html>'
    )

    resources = CasacivilIndexDiscovery(
        {"strategy": "casacivil-index", "url": INDEX_URL},
        "ro",
        "casacivil",
    ).run()

    assert [resource["chave"] for resource in resources] == ["lei-06002"]
    mock_check_available.assert_called_once_with(INDEX_URL)
    mock_closest_snapshot.assert_not_called()
