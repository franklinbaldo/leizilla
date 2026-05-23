"""Testes para publisher.upload_dataset + build_dataset_meta (M4 restante)."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb
import pytest
from typer.testing import CliRunner

from leizilla.cli import app
from leizilla.publisher import (
    InternetArchivePublisher,
    build_dataset_meta,
)

_runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_parquet(tmp_path: Path) -> Path:
    """Cria Parquet mínimo válido para testes (sem precisar de etl.py)."""
    out = tmp_path / "versoes.parquet"
    conn = duckdb.connect()
    try:
        conn.execute(
            "CREATE TABLE t AS SELECT "
            "'leizilla-ro-lei-00001-2000' AS lei_id, "
            "'ro' AS ente, "
            "'art-1' AS dispositivo_path, "
            "'artigo' AS dispositivo_tipo, "
            "NULL::VARCHAR AS texto_normalizado, "
            "NULL::DATE AS ate"
        )
        conn.table("t").write_parquet(str(out), compression="snappy")
    finally:
        conn.close()
    return out


def _publisher(access: str = "key", secret: str = "secret") -> InternetArchivePublisher:
    pub = InternetArchivePublisher.__new__(InternetArchivePublisher)
    pub.access_key = access
    pub.secret_key = secret
    return pub


# ---------------------------------------------------------------------------
# build_dataset_meta — função pura
# ---------------------------------------------------------------------------


class TestBuildDatasetMeta:
    def test_required_fields_present(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        meta = build_dataset_meta(p, "ro", 0, row_count=1, git_sha=None)
        required = {
            "leizilla_meta_version", "schema_version", "ente", "version",
            "table", "generated_at", "row_count", "file_size_bytes", "hash_parquet",
        }
        assert required.issubset(meta.keys())

    def test_ente_and_version(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        meta = build_dataset_meta(p, "federal", 1, row_count=0)
        assert meta["ente"] == "federal"
        assert meta["version"] == 1

    def test_hash_parquet_format(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        meta = build_dataset_meta(p, "ro", 0, row_count=1)
        assert meta["hash_parquet"].startswith("sha256:")
        expected = "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
        assert meta["hash_parquet"] == expected

    def test_row_count_explicit(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        meta = build_dataset_meta(p, "ro", 0, row_count=42)
        assert meta["row_count"] == 42

    def test_row_count_auto_from_parquet(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        meta = build_dataset_meta(p, "ro", 0, row_count=None)
        assert meta["row_count"] == 1  # _make_parquet cria 1 linha

    def test_git_sha_included_when_provided(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        meta = build_dataset_meta(p, "ro", 0, row_count=1, git_sha="abc123")
        assert meta["git_sha"] == "abc123"

    def test_git_sha_absent_when_none_and_no_git(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        err = subprocess.CalledProcessError(128, "git")
        with patch("subprocess.run", side_effect=err):
            meta = build_dataset_meta(p, "ro", 0, row_count=1, git_sha=None)
        assert "git_sha" not in meta

    def test_table_is_versoes(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        meta = build_dataset_meta(p, "ro", 0, row_count=1)
        assert meta["table"] == "versoes"

    def test_schema_version(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        meta = build_dataset_meta(p, "ro", 0, row_count=1)
        assert meta["schema_version"] == "0.1"

    def test_file_size_bytes_correct(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        meta = build_dataset_meta(p, "ro", 0, row_count=1)
        assert meta["file_size_bytes"] == p.stat().st_size


# ---------------------------------------------------------------------------
# InternetArchivePublisher.upload_dataset
# ---------------------------------------------------------------------------


class TestUploadDataset:
    def test_no_creds_returns_error(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        pub = _publisher(access="", secret="")
        result = pub.upload_dataset(p, "ro", 0, row_count=1, git_sha=None)
        assert result["success"] is False
        assert "credentials" in result["error"].lower()

    def test_correct_ia_identifier(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        pub = _publisher()
        mock_cp = MagicMock(returncode=0, stdout="", stderr="")
        with patch("leizilla.publisher._get_git_sha", return_value=None), \
             patch("subprocess.run", return_value=mock_cp) as mock_run:
            pub.upload_dataset(p, "ro", 0, row_count=1, git_sha=None)
        call_args = mock_run.call_args_list[0][0][0]
        assert "leizilla-dataset-ro-v0" in call_args

    def test_success_returns_ia_url(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        pub = _publisher()
        mock_cp = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_cp):
            result = pub.upload_dataset(p, "ro", 0, row_count=1, git_sha=None)
        assert result["success"] is True
        assert result["ia_url"] == "https://archive.org/details/leizilla-dataset-ro-v0"
        assert result["ia_id"] == "leizilla-dataset-ro-v0"

    def test_success_returns_row_count(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        pub = _publisher()
        mock_cp = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_cp):
            result = pub.upload_dataset(p, "ro", 0, row_count=7, git_sha=None)
        assert result["row_count"] == 7

    def test_version_in_identifier(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        pub = _publisher()
        mock_cp = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_cp):
            result = pub.upload_dataset(p, "federal", 2, row_count=0, git_sha=None)
        assert result["ia_id"] == "leizilla-dataset-federal-v2"

    def test_negative_version_raises(self, tmp_path: Path) -> None:
        # P2 fix: upload_dataset API rejects negative versions before constructing ia_id
        p = _make_parquet(tmp_path)
        pub = _publisher()
        with pytest.raises(ValueError, match="version must be >= 0"):
            pub.upload_dataset(p, "ro", -1, row_count=1, git_sha=None)

    def test_invalid_ente_raises(self, tmp_path: Path) -> None:
        # P2 fix: upload_dataset rejects ente values that would violate _DATASET_IDENTIFIER_RE
        p = _make_parquet(tmp_path)
        pub = _publisher()
        for bad_ente in ("RO", "sp_", "ro ro", "", "1ro"):
            with pytest.raises(ValueError, match="ente must match"):
                pub.upload_dataset(p, bad_ente, 0, row_count=1, git_sha=None)

    def test_subprocess_failure_returns_error(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        pub = _publisher()
        err = subprocess.CalledProcessError(1, "ia", stderr="quota exceeded")
        with patch("subprocess.run", side_effect=err):
            result = pub.upload_dataset(p, "ro", 0, row_count=1, git_sha=None)
        assert result["success"] is False
        assert "quota exceeded" in result["error"]

    def test_mediatype_is_data(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        pub = _publisher()
        mock_cp = MagicMock(returncode=0, stdout="", stderr="")
        with patch("leizilla.publisher._get_git_sha", return_value=None), \
             patch("subprocess.run", return_value=mock_cp) as mock_run:
            pub.upload_dataset(p, "ro", 0, row_count=1, git_sha=None)
        call_args = mock_run.call_args_list[0][0][0]
        assert "mediatype:data" in call_args

    def test_sidecar_json_is_uploaded(self, tmp_path: Path) -> None:
        """dataset_meta.json deve estar no comando ia upload."""
        p = _make_parquet(tmp_path)
        pub = _publisher()
        mock_cp = MagicMock(returncode=0, stdout="", stderr="")
        uploaded_files: list[str] = []

        def capture(cmd: list[str], **kwargs: object) -> MagicMock:
            # Collect file paths passed to ia upload (after the ia_id arg)
            uploaded_files.extend(
                f for f in cmd[3:] if not f.startswith("--") and not f.startswith("media")
            )
            return mock_cp

        with patch("subprocess.run", side_effect=capture):
            pub.upload_dataset(p, "ro", 0, row_count=1, git_sha=None)

        assert any("dataset_meta.json" in f for f in uploaded_files)
        assert any("versoes.parquet" in f for f in uploaded_files)

    def test_ia_not_installed_returns_error(self, tmp_path: Path) -> None:
        """FileNotFoundError (ia CLI ausente) deve retornar payload de erro, não raise."""
        p = _make_parquet(tmp_path)
        pub = _publisher()
        with patch("subprocess.run", side_effect=FileNotFoundError("ia not found")):
            result = pub.upload_dataset(p, "ro", 0, row_count=1, git_sha=None)
        assert result["success"] is False
        assert "internetarchive" in result["error"]


class TestReleaseDatasetCli:
    def test_negative_version_rejected(self, tmp_path: Path) -> None:
        """--version negativo deve ser rejeitado com exit 1."""
        p = _make_parquet(tmp_path)
        result = _runner.invoke(app, ["release-dataset", str(p), "--version", "-1"])
        assert result.exit_code == 1
        assert ">= 0" in result.output

    def test_upload_failure_exits_nonzero(self, tmp_path: Path) -> None:
        """CLI deve sair com code 1 quando upload_dataset retorna success=False."""
        p = _make_parquet(tmp_path)
        fail_result = {"success": False, "error": "credenciais inválidas", "ia_id": "leizilla-dataset-ro-v0"}
        with patch(
            "leizilla.publisher.InternetArchivePublisher.upload_dataset",
            return_value=fail_result,
        ):
            result = _runner.invoke(app, ["release-dataset", str(p), "--version", "0"])
        assert result.exit_code == 1
        assert "Upload falhou" in result.output

    def test_invalid_ente_exits_nonzero(self, tmp_path: Path) -> None:
        """ValueError de ente inválido deve ser capturado e sair com exit 1."""
        p = _make_parquet(tmp_path)
        with patch(
            "leizilla.publisher.InternetArchivePublisher.upload_dataset",
            side_effect=ValueError("ente must match ^[a-z]"),
        ):
            result = _runner.invoke(app, ["release-dataset", str(p), "--ente", "RO"])
        assert result.exit_code == 1
        assert "Upload falhou" in result.output


class TestReleaseDatasetBenchmark:
    """Testa benchmark gatilhos §3.4 no cmd_release_dataset (M4.3)."""

    def test_dry_run_reports_stats_line(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        result = _runner.invoke(app, ["release-dataset", str(p), "--dry-run"])
        assert result.exit_code == 0
        assert "Stats:" in result.output
        assert "linhas" in result.output
        assert "MB" in result.output
        assert "ms" in result.output

    def test_no_gatilho_warning_for_small_dataset(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        result = _runner.invoke(app, ["release-dataset", str(p), "--dry-run"])
        assert result.exit_code == 0
        assert "Gatilhos" not in result.output

    def _mock_conn(self, row_count: int) -> MagicMock:
        """Mock duckdb.connect() para controlar row_count e retorno de search."""
        mock_conn = MagicMock()
        count_res = MagicMock()
        count_res.fetchone.return_value = (row_count,)
        search_res = MagicMock()
        search_res.fetchall.return_value = []
        mock_conn.execute.side_effect = [count_res, search_res]
        return mock_conn

    def test_row_count_threshold_warning(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        with patch("duckdb.connect", return_value=self._mock_conn(2_000_001)):
            result = _runner.invoke(app, ["release-dataset", str(p), "--dry-run"])
        assert "rows > 2M" in result.output
        assert "Gatilhos §3.4" in result.output

    def test_search_latency_threshold_warning(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        # perf_counter: t0=0.0, t1=1.5 → search_ms = 1500 > 1000
        with patch("time.perf_counter", side_effect=[0.0, 1.5]):
            result = _runner.invoke(app, ["release-dataset", str(p), "--dry-run"])
        assert "search > 1s" in result.output
        assert "Gatilhos §3.4" in result.output

    def test_file_size_threshold_warning(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        mock_stat = MagicMock()
        mock_stat.st_size = 101 * 1_048_576  # 101 MB
        original_stat = Path.stat

        def patched_stat(self: Path, *args: object, **kwargs: object) -> object:
            if self == p:
                return mock_stat
            return original_stat(self, *args, **kwargs)

        with patch.object(Path, "stat", patched_stat):
            result = _runner.invoke(app, ["release-dataset", str(p), "--dry-run"])
        assert "file > 100 MB" in result.output
        assert "Gatilhos §3.4" in result.output

    def test_two_gatilhos_triggers_rfc_message(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        mock_stat = MagicMock()
        mock_stat.st_size = 101 * 1_048_576
        original_stat = Path.stat

        def patched_stat(self: Path, *args: object, **kwargs: object) -> object:
            if self == p:
                return mock_stat
            return original_stat(self, *args, **kwargs)

        with patch("duckdb.connect", return_value=self._mock_conn(2_000_001)), \
             patch.object(Path, "stat", patched_stat):
            result = _runner.invoke(app, ["release-dataset", str(p), "--dry-run"])
        assert "RFC sobre split" in result.output
        assert "2+" in result.output
