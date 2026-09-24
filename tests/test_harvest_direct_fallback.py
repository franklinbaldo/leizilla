"""Regression: harvest rejects a non-PDF direct fallback."""

from unittest.mock import MagicMock, patch

from leizilla.storage import DuckDBStorage


def test_direct_fallback_rejects_non_pdf(tmp_path):
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
        with (
            patch("leizilla.scraper.robots.is_allowed", return_value=True),
            patch("leizilla.scraper.wayback.ensure_archived", return_value=None),
            patch(
                "leizilla.scraper.wayback.fetch_bytes",
                return_value=b"<html>error</html>",
            ),
        ):
            stats = harvest_pending_resources(db, pub, limit=10)

        assert stats["failed"] == 1
        assert stats["items"][0]["reason"] == "not-pdf"
        pub.upload_raw.assert_not_called()
    finally:
        db.close()
