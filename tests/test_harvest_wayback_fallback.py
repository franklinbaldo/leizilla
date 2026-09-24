"""Regression: an HTML Wayback response falls back to direct PDF fetch."""

from unittest.mock import MagicMock, patch

from leizilla.storage import DuckDBStorage


def test_wayback_html_response_triggers_direct_fallback(tmp_path):
    from leizilla.scraper import harvest_pending_resources

    db = DuckDBStorage(tmp_path / "test.duckdb")
    try:
        db.insert_resource({
            "url": "http://example.com/lei.pdf",
            "ente": "ro",
            "fonte": "casacivil",
            "tipo_documento": "lei",
            "chave": "lei-00001",
            "status": "pending",
        })
        pub = MagicMock()
        pub.upload_raw.return_value = {"success": True, "ia_url": "ok"}
        with (
            patch("leizilla.scraper.robots.is_allowed", return_value=True),
            patch(
                "leizilla.scraper.wayback.ensure_archived",
                return_value=("snapshot", "2026"),
            ),
            patch(
                "leizilla.scraper.wayback.fetch_bytes",
                side_effect=[
                    b"<html>error</html>",
                    b"%PDF-1.4 content",
                ],
            ),
        ):
            stats = harvest_pending_resources(db, pub, limit=10)

        assert stats["success"] == 1
        assert pub.upload_raw.call_args.args[1]["wayback_timestamp"] is None
    finally:
        db.close()
