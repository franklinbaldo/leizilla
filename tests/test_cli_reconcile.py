"""CLI wiring for `reconcile`: discovery re-derives identities → publisher promotes."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from leizilla.cli import app

runner = CliRunner()


def test_reconcile_builds_identity_map_and_calls_publisher():
    # Fresh discovery yields one identified (lei-99) and one still-unidentified row.
    resources = [
        {
            "url": "http://alro/leis/99",
            "fonte": "assembleia",
            "chave": "lei-00099",
        },
        {
            "url": "http://alro/leis/77",
            "fonte": "assembleia",
            "chave": "coddoc-00077",  # non-identifying → not in the map
        },
    ]
    pub = MagicMock()
    pub.reconcile_unidentified.return_value = {
        "success": True,
        "promoted": 1,
        "remaining": 1,
        "item_id": "leizilla_ro_assembleia_unidentified",
    }
    with (
        patch("leizilla.discovery.discover_resources", return_value=resources),
        patch("leizilla.publisher.InternetArchivePublisher", return_value=pub),
    ):
        result = runner.invoke(app, ["reconcile", "--ente", "ro"])

    assert result.exit_code == 0
    # Publisher called once for the assembleia fonte with only the identified URL.
    pub.reconcile_unidentified.assert_called_once()
    args = pub.reconcile_unidentified.call_args.args
    assert args[0] == "ro" and args[1] == "assembleia"
    identity_map = args[2]
    assert identity_map == {"http://alro/leis/99": ("lei", 99)}
    assert "1 promovidos" in result.output


def test_reconcile_exits_nonzero_when_a_fonte_fails():
    # A failed reconcile (e.g. holding-index rewrite error) must exit nonzero so
    # automation detects the partial cleanup.
    resources = [
        {"url": "http://alro/leis/99", "fonte": "assembleia", "chave": "lei-00099"},
    ]
    pub = MagicMock()
    pub.reconcile_unidentified.return_value = {
        "success": False,
        "error": "holding index rewrite failed",
        "item_id": "leizilla_ro_assembleia_unidentified",
    }
    with (
        patch("leizilla.discovery.discover_resources", return_value=resources),
        patch("leizilla.publisher.InternetArchivePublisher", return_value=pub),
    ):
        result = runner.invoke(app, ["reconcile", "--ente", "ro"])

    assert result.exit_code == 1
    assert "erro" in result.output.lower()
