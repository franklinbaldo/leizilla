"""Public-byte confirmation never repairs a partial publication by writing again."""

import io
import subprocess
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from leizilla.publisher import InternetArchivePublisher, _verify_dataset_files


@pytest.mark.parametrize(
    "name", ["versoes.parquet", "dataset_meta.json", "latest.json"]
)
def test_verifies_exact_public_bytes(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_bytes(b"candidate")
    with patch("urllib.request.urlopen", return_value=io.BytesIO(b"candidate")) as get:
        _verify_dataset_files("release", [path])
    assert get.call_count == 1
    assert get.call_args.args[0].full_url.endswith(f"/release/{name}")


def test_stale_bytes_eventually_visible_without_reupload(tmp_path: Path) -> None:
    path = tmp_path / "latest.json"
    path.write_bytes(b"new")
    with (
        patch(
            "urllib.request.urlopen",
            side_effect=[io.BytesIO(b"old"), io.BytesIO(b"new")],
        ) as get,
        patch("time.sleep") as sleep,
    ):
        _verify_dataset_files("latest", [path])
    assert get.call_count == 2
    sleep.assert_called_once_with(30)


@pytest.mark.parametrize("failure", ["stale", 404, 503, "timeout"])
def test_unconfirmed_bytes_fail_after_bounded_reads(tmp_path: Path, failure) -> None:
    path = tmp_path / "versoes.parquet"
    path.write_bytes(b"new")
    if failure == "stale":
        replies = [io.BytesIO(b"old") for _ in range(3)]
    elif failure == "timeout":
        replies = [TimeoutError("timed out")] * 3
    else:
        replies = [urllib.error.HTTPError("url", failure, "unavailable", {}, None)] * 3
    with (
        patch("urllib.request.urlopen", side_effect=replies) as get,
        patch("time.sleep") as sleep,
    ):
        with pytest.raises(ValueError, match="Publication unconfirmed"):
            _verify_dataset_files("latest", [path])
    assert get.call_count == 3
    assert [c.args[0] for c in sleep.call_args_list] == [30, 60]


@pytest.mark.parametrize("status", [401, 403, 429])
def test_read_refusals_are_not_retried(tmp_path: Path, status: int) -> None:
    path = tmp_path / "latest.json"
    path.write_bytes(b"new")
    error = urllib.error.HTTPError("url", status, "refused", {}, None)
    with (
        patch("urllib.request.urlopen", side_effect=error) as get,
        patch("time.sleep") as sleep,
    ):
        with pytest.raises(ValueError, match=f"HTTP {status}"):
            _verify_dataset_files("latest", [path])
    assert get.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize("stage", ["release", "latest"])
def test_partial_publication_fails_and_preserves_candidate(
    tmp_path: Path, stage: str
) -> None:
    path = tmp_path / "candidate.parquet"
    path.write_bytes(b"candidate")
    pub = InternetArchivePublisher()
    pub.access_key, pub.secret_key = "test", "test"
    effects = (
        [ValueError("unconfirmed")]
        if stage == "release"
        else [None, ValueError("unconfirmed")]
    )
    with (
        patch.object(
            pub, "_run_ia_upload", return_value=MagicMock(returncode=0)
        ) as upload,
        patch("leizilla.publisher._verify_dataset_files", side_effect=effects),
    ):
        result = pub.upload_dataset(path, "ro", row_count=1, git_sha="test")
    assert result["success"] is False
    assert upload.call_count == (1 if stage == "release" else 2)
    assert result.get("release_success", False) == (stage == "latest")
    assert path.read_bytes() == b"candidate"


def test_release_refusal_never_attempts_latest(tmp_path: Path) -> None:
    path = tmp_path / "candidate.parquet"
    path.write_bytes(b"candidate")
    pub = InternetArchivePublisher()
    pub.access_key, pub.secret_key = "test", "test"
    error = subprocess.CalledProcessError(1, "ia", stderr="appears to be spam")
    with (
        patch.object(pub, "_run_ia_upload", side_effect=error) as upload,
        patch("leizilla.publisher._verify_dataset_files") as verify,
    ):
        result = pub.upload_dataset(path, "ro", row_count=1, git_sha="test")
    assert result["success"] is False
    upload.assert_called_once()
    verify.assert_not_called()
