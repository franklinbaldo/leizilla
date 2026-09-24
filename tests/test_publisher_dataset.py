"""Testes para publisher.upload_dataset + build_dataset_meta (M4 restante)."""

from __future__ import annotations

import hashlib
import json
import re
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
    # __init__ real (não __new__) -- precisamos do _upload_rate_limiter que ele
    # cria; sobrescrever access_key/secret_key depois é só pra controlar o teste
    # sem depender de config.IA_ACCESS_KEY/IA_SECRET_KEY do ambiente.
    pub = InternetArchivePublisher()
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
            "leizilla_meta_version",
            "schema_version",
            "ente",
            "version",
            "table",
            "generated_at",
            "row_count",
            "file_size_bytes",
            "hash_parquet",
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

    def test_revision_defaults_when_omitted(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        meta = build_dataset_meta(p, "ro", 0, row_count=1)
        assert re.match(r"^\d{8}t\d{6}z$", meta["revision"])

    def test_revision_explicit(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        meta = build_dataset_meta(p, "ro", 0, row_count=1, revision="20260101t000000z")
        assert meta["revision"] == "20260101t000000z"


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
        with (
            patch("leizilla.publisher._get_git_sha", return_value=None),
            patch("subprocess.run", return_value=mock_cp) as mock_run,
        ):
            pub.upload_dataset(
                p, "ro", 0, row_count=1, git_sha=None, revision="20260101t000000z"
            )
        call_args = mock_run.call_args_list[0][0][0]
        assert "leizilla-dataset-ro-v0-20260101t000000z" in call_args

    def test_success_returns_ia_url(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        pub = _publisher()
        mock_cp = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_cp):
            result = pub.upload_dataset(
                p, "ro", 0, row_count=1, git_sha=None, revision="20260101t000000z"
            )
        assert result["success"] is True
        assert (
            result["ia_url"]
            == "https://archive.org/details/leizilla-dataset-ro-v0-20260101t000000z"
        )
        assert result["ia_id"] == "leizilla-dataset-ro-v0-20260101t000000z"

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
            result = pub.upload_dataset(
                p,
                "federal",
                2,
                row_count=0,
                git_sha=None,
                revision="20260101t000000z",
            )
        assert result["ia_id"] == "leizilla-dataset-federal-v2-20260101t000000z"

    def test_revision_defaults_to_utc_timestamp_format(self, tmp_path: Path) -> None:
        """Sem --revision explícito, o identifier embute um timestamp UTC (issue #175)."""
        p = _make_parquet(tmp_path)
        pub = _publisher()
        mock_cp = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_cp):
            result = pub.upload_dataset(p, "ro", 0, row_count=1, git_sha=None)
        assert re.match(r"^leizilla-dataset-ro-v0-\d{8}t\d{6}z$", result["ia_id"]), (
            result["ia_id"]
        )
        assert result["revision"] == result["ia_id"].rsplit("-", 1)[-1]

    def test_repeated_calls_never_reuse_identifier(self, tmp_path: Path) -> None:
        """Cada publicação é um item imutável novo — nunca sobrescreve a anterior."""
        p = _make_parquet(tmp_path)
        pub = _publisher()
        mock_cp = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_cp):
            first = pub.upload_dataset(
                p, "ro", 0, row_count=1, git_sha=None, revision="20260101t000000z"
            )
            second = pub.upload_dataset(
                p, "ro", 0, row_count=1, git_sha=None, revision="20260102t000000z"
            )
        assert first["ia_id"] != second["ia_id"]

    def test_invalid_revision_raises(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        pub = _publisher()
        with pytest.raises(ValueError, match="revision must match"):
            pub.upload_dataset(p, "ro", 0, row_count=1, revision="2026-01-01")

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
        with (
            patch("leizilla.publisher._get_git_sha", return_value=None),
            patch("subprocess.run", return_value=mock_cp) as mock_run,
        ):
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
                f
                for f in cmd[3:]
                if not f.startswith("--") and not f.startswith("media")
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



class TestUploadDatasetLatestPointer:
    """Ponteiro mutável leizilla-dataset-{ente}-v{version}-latest (issue #175)."""

    def test_latest_pointer_published_by_default(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        pub = _publisher()
        mock_cp = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("leizilla.publisher._get_git_sha", return_value=None),
            patch("subprocess.run", return_value=mock_cp) as mock_run,
        ):
            result = pub.upload_dataset(
                p, "ro", 0, row_count=1, git_sha=None, revision="20260101t000000z"
            )
        assert mock_run.call_count == 2
        latest_call_args = mock_run.call_args_list[1][0][0]
        assert "leizilla-dataset-ro-v0-latest" in latest_call_args
        assert result["latest_pointer"]["success"] is True
        assert result["latest_pointer"]["ia_id"] == "leizilla-dataset-ro-v0-latest"
        assert result["latest_pointer"]["points_to"] == result["ia_id"]

    def test_latest_pointer_can_be_disabled(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        pub = _publisher()
        mock_cp = MagicMock(returncode=0, stdout="", stderr="")
        with (
            patch("leizilla.publisher._get_git_sha", return_value=None),
            patch("subprocess.run", return_value=mock_cp) as mock_run,
        ):
            result = pub.upload_dataset(
                p, "ro", 0, row_count=1, git_sha=None, publish_latest=False
            )
        assert mock_run.call_count == 1
        assert "latest_pointer" not in result

    def test_latest_json_points_to_immutable_release(self, tmp_path: Path) -> None:
        """latest.json enviado ao IA referencia o identifier imutável do release."""
        p = _make_parquet(tmp_path)
        pub = _publisher()
        mock_cp = MagicMock(returncode=0, stdout="", stderr="")
        captured: dict[str, object] = {}

        def capture(cmd: list[str], **kwargs: object) -> MagicMock:
            for f in cmd:
                if isinstance(f, str) and f.endswith("latest.json"):
                    captured["payload"] = json.loads(Path(f).read_text())
            return mock_cp

        with patch("subprocess.run", side_effect=capture):
            result = pub.upload_dataset(
                p, "ro", 0, row_count=1, git_sha="deadbeef", revision="20260101t000000z"
            )

        payload = captured["payload"]
        assert (
            payload["identifier"]
            == result["ia_id"]
            == "leizilla-dataset-ro-v0-20260101t000000z"
        )
        assert payload["revision"] == "20260101t000000z"
        assert payload["git_sha"] == "deadbeef"
        assert payload["row_count"] == 1
        assert payload["parquet_url"].endswith(f"/{result['ia_id']}/versoes.parquet")

    def test_latest_pointer_failure_does_not_fail_release(self, tmp_path: Path) -> None:
        """Falha no ponteiro é fail-open: a release imutável já publicou com sucesso."""
        p = _make_parquet(tmp_path)
        pub = _publisher()
        mock_cp = MagicMock(returncode=0, stdout="", stderr="")
        err = subprocess.CalledProcessError(1, "ia", stderr="rate limited")
        with (
            patch("leizilla.publisher._get_git_sha", return_value=None),
            patch("subprocess.run", side_effect=[mock_cp, err]),
        ):
            result = pub.upload_dataset(p, "ro", 0, row_count=1, git_sha=None)
        assert result["success"] is True
        assert result["latest_pointer"]["success"] is False
        assert "rate limited" in result["latest_pointer"]["error"]


class TestUploadCoverage:
    """coverage.json (issue #174) publicado no ponteiro mutável `-latest`.

    upload_dataset (issue #175) parou de publicar em `leizilla-dataset-{ente}-v{version}`
    — esse identifier agora é sempre imutável e sufixado com `-{revision}`. O frontend
    (`web/src/lib/db.ts`'s `DATASET_IA_ITEM`/`COVERAGE_JSON_URL`) resolve coverage.json
    a partir do item que `PUBLIC_PARQUET_URL` de fato aponta — por padrão o ponteiro
    `-latest`. `upload_coverage` precisa mirar o mesmo item, não o identifier antigo
    sem sufixo (que nada mais publica).
    """

    def test_uploads_to_latest_pointer_identifier(self, tmp_path: Path) -> None:
        pub = _publisher()
        mock_cp = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_cp) as mock_run:
            result = pub.upload_coverage({"ente": "ro"}, "ro", 0)
        call_args = mock_run.call_args_list[0][0][0]
        assert "leizilla-dataset-ro-v0-latest" in call_args
        assert result["ia_id"] == "leizilla-dataset-ro-v0-latest"
        assert (
            result["ia_url"]
            == "https://archive.org/details/leizilla-dataset-ro-v0-latest"
        )

    def test_no_creds_returns_error(self) -> None:
        pub = _publisher(access="", secret="")
        result = pub.upload_coverage({"ente": "ro"}, "ro", 0)
        assert result["success"] is False
        assert "credentials" in result["error"].lower()


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
        fail_result = {
            "success": False,
            "error": "credenciais inválidas",
            "ia_id": "leizilla-dataset-ro-v0",
        }
        with (
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_dataset",
                return_value=fail_result,
            ),
            patch(
                "leizilla.publisher.fetch_published_dataset_row_count",
                return_value=None,
            ),
        ):
            result = _runner.invoke(app, ["release-dataset", str(p), "--version", "0"])
        assert result.exit_code == 1
        assert "Upload falhou" in result.output

    def test_invalid_ente_exits_nonzero(self, tmp_path: Path) -> None:
        """ValueError de ente inválido deve ser capturado e sair com exit 1."""
        p = _make_parquet(tmp_path)
        with (
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_dataset",
                side_effect=ValueError("ente must match ^[a-z]"),
            ),
            patch(
                "leizilla.publisher.fetch_published_dataset_row_count",
                return_value=None,
            ),
        ):
            result = _runner.invoke(app, ["release-dataset", str(p), "--ente", "RO"])
        assert result.exit_code == 1
        assert "Upload falhou" in result.output

    def test_echoes_latest_pointer_url_on_success(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        ok_result = {
            "success": True,
            "ia_id": "leizilla-dataset-ro-v0-20260101t000000z",
            "ia_url": "https://archive.org/details/leizilla-dataset-ro-v0-20260101t000000z",
            "row_count": 1,
            "revision": "20260101t000000z",
            "latest_pointer": {
                "success": True,
                "ia_id": "leizilla-dataset-ro-v0-latest",
                "ia_url": "https://archive.org/details/leizilla-dataset-ro-v0-latest",
                "points_to": "leizilla-dataset-ro-v0-20260101t000000z",
            },
        }
        with (
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_dataset",
                return_value=ok_result,
            ),
            patch(
                "leizilla.publisher.fetch_published_dataset_row_count",
                return_value=None,
            ),
        ):
            result = _runner.invoke(app, ["release-dataset", str(p), "--version", "0"])
        assert result.exit_code == 0
        assert "Ponteiro latest atualizado" in result.output
        assert "leizilla-dataset-ro-v0-latest" in result.output

    def test_echoes_warning_when_latest_pointer_fails(self, tmp_path: Path) -> None:
        p = _make_parquet(tmp_path)
        ok_result = {
            "success": True,
            "ia_id": "leizilla-dataset-ro-v0-20260101t000000z",
            "ia_url": "https://archive.org/details/leizilla-dataset-ro-v0-20260101t000000z",
            "row_count": 1,
            "revision": "20260101t000000z",
            "latest_pointer": {
                "success": False,
                "error": "rate limited",
                "ia_id": "leizilla-dataset-ro-v0-latest",
            },
        }
        with (
            patch(
                "leizilla.publisher.InternetArchivePublisher.upload_dataset",
                return_value=ok_result,
            ),
            patch(
                "leizilla.publisher.fetch_published_dataset_row_count",
                return_value=None,
            ),
        ):
            result = _runner.invoke(app, ["release-dataset", str(p), "--version", "0"])
        assert result.exit_code == 0
        assert "Aviso" in result.output
        assert "rate limited" in result.output


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

        with (
            patch("duckdb.connect", return_value=self._mock_conn(2_000_001)),
            patch.object(Path, "stat", patched_stat),
        ):
            result = _runner.invoke(app, ["release-dataset", str(p), "--dry-run"])
        assert "RFC sobre split" in result.output
        assert "2+" in result.output
