"""Trava curta de bucket do IA é transitória (recuo 30/60/120 s) — offline."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from leizilla.publisher import InternetArchivePublisher

LOCK_MSG = (
    " error uploading textos.parquet: We encountered an internal error. Please try "
    "again. - Failed to get necessary short term bucket lock for "
    "leizilla-textos-ro-v0-20261118t061620z, please try again"
)


def _pub() -> InternetArchivePublisher:
    pub = InternetArchivePublisher()
    pub.access_key, pub.secret_key = "k", "s"
    return pub


def _err(stderr: str) -> subprocess.CalledProcessError:
    return subprocess.CalledProcessError(1, "ia", stderr=stderr)


def _delays(mock_sleep: MagicMock) -> list[float]:
    return [c.args[0] for c in mock_sleep.call_args_list]


@patch("random.uniform", return_value=0.0)
@patch("time.sleep")
def test_the_bucket_lock_message_is_retried_with_lock_backoff(sleep, _rand) -> None:
    ok = MagicMock(returncode=0)
    with patch(
        "subprocess.run", side_effect=[_err(LOCK_MSG), _err(LOCK_MSG), ok]
    ) as run:
        assert _pub()._run_ia_upload(["ia", "upload", "x"]) is ok
    assert run.call_count == 3
    assert _delays(sleep) == [30.0, 60.0]


@patch("random.uniform", return_value=0.0)
@patch("time.sleep")
def test_the_read_timeout_then_lock_sequence_of_run_44404993744_recovers(
    sleep, _rand
) -> None:
    ok = MagicMock(returncode=0)
    timeout = _err("ReadTimeoutError: Read timed out. (read timeout=60)")
    with patch("subprocess.run", side_effect=[timeout, _err(LOCK_MSG), ok]) as run:
        _pub()._run_ia_upload(["ia", "upload", "x"])
    assert run.call_count == 3
    assert _delays(sleep) == [2.0, 30.0]  # curto para o timeout, longo para a trava


@patch("random.uniform", return_value=0.0)
@patch("time.sleep")
def test_the_generic_internal_error_is_transient_and_backoff_caps_at_120(
    sleep, _rand
) -> None:
    generic = _err("We encountered an internal error. Please try again.")
    with patch("subprocess.run", side_effect=generic) as run:
        with pytest.raises(subprocess.CalledProcessError):
            _pub()._run_ia_upload(["ia", "upload", "x"], max_attempts=5)
    assert run.call_count == 5  # o mesmo orçamento de tentativas de sempre
    assert _delays(sleep) == [30.0, 60.0, 120.0, 120.0]


@patch("time.sleep")
def test_the_lock_backoff_respects_the_job_deadline(sleep) -> None:
    with patch("subprocess.run", side_effect=_err(LOCK_MSG)) as run:
        with pytest.raises(subprocess.TimeoutExpired):
            _pub()._run_ia_upload(["ia", "upload", "x"], timeout_s=20.0)
    assert run.call_count == 1  # 30 s de recuo não cabem nos 20 s que restam
    sleep.assert_not_called()


@patch("time.sleep")
def test_throttles_and_content_rejections_do_not_get_the_lock_backoff(sleep) -> None:
    # fila de tarefas cheia + a frase genérica: continua sendo throttle (fail-fast)
    throttled = _err(
        "We encountered an internal error. Please try again. - "
        "Please reduce your request rate. - bucket_tasks_queued exceeds bucket_limit"
    )
    with patch("subprocess.run", side_effect=throttled) as run:
        with pytest.raises(subprocess.CalledProcessError):
            _pub()._run_ia_upload(["ia", "upload", "x"], fail_fast_queue=True)
    assert run.call_count == 1
    # recusa de conteúdo nunca é repetida, mesmo com a frase de trava no texto
    rejected = _err(
        "Uploaded content is unacceptable. - pdf file looks like spam "
        "(short term bucket lock)"
    )
    with patch("subprocess.run", side_effect=rejected) as run:
        with pytest.raises(subprocess.CalledProcessError):
            _pub()._run_ia_upload(["ia", "upload", "x"])
    assert run.call_count == 1
    sleep.assert_not_called()
