"""Offline tests of credential transport, redaction, and renewal lifecycle."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest

spec = importlib.util.spec_from_file_location(
    "anthropic_wif", Path(__file__).parents[1] / "scripts" / "anthropic_wif.py"
)
assert spec and spec.loader
wif = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wif)


def test_identity_uses_only_generate_id_token(monkeypatch):
    for key, value in {
        "ANTHROPIC_GOOGLE_WIF_PROVIDER": "projects/1/locations/global/workloadIdentityPools/p/providers/g",
        "ANTHROPIC_GOOGLE_SERVICE_ACCOUNT": "test@example.iam.gserviceaccount.com",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.test/oidc?job=1",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "fictional-github-request-token",
    }.items():
        monkeypatch.setenv(key, value)
    request = Mock(
        side_effect=[
            {"value": "fictional-github-jwt"},
            {"access_token": "fictional-federated-token"},
            {"token": "fictional-google-id-token"},
        ]
    )
    monkeypatch.setattr(wif, "request_json", request)
    assert wif.google_identity() == "fictional-google-id-token"
    calls = request.call_args_list
    assert "&audience=" in calls[0].args[0]
    assert calls[1].kwargs["data"]["subjectToken"] == "fictional-github-jwt"
    assert calls[2].args[0].endswith(":generateIdToken")
    assert calls[2].kwargs["data"]["audience"] == "https://api.anthropic.com"
    assert all("generateAccessToken" not in c.args[0] for c in calls)


def test_http_errors_never_include_body_url_or_token(monkeypatch):
    error = HTTPError("https://example.test/secret", 403, "secret", {}, None)
    monkeypatch.setattr(wif, "urlopen", Mock(side_effect=error))
    with pytest.raises(wif.AuthenticationError) as caught:
        wif.request_json("https://example.test/secret", "Google STS", bearer="secret")
    assert str(caught.value) == "Google STS: HTTP 403"


def test_refresh_preserves_previous_identity_on_failure(monkeypatch, tmp_path):
    path = tmp_path / "identity.jwt"
    path.write_text("old-fictional-token")
    monkeypatch.setattr(
        wif, "google_identity", Mock(side_effect=wif.AuthenticationError("failed"))
    )
    with pytest.raises(wif.AuthenticationError):
        wif.refresh(path)
    assert path.read_text() == "old-fictional-token"
    monkeypatch.setattr(wif, "google_identity", lambda: "new-fictional-token")
    wif.refresh(path)
    assert path.read_text() == "new-fictional-token"
    assert not path.with_suffix(".tmp").exists()


def test_child_renews_and_returns_exit_status(monkeypatch, tmp_path):
    child = Mock(returncode=3)
    child.poll.side_effect = [None, 3, 3]
    monkeypatch.setattr(wif.subprocess, "Popen", Mock(return_value=child))
    monkeypatch.setattr(wif.time, "monotonic", Mock(side_effect=[0, 2401, 2402]))
    monkeypatch.setattr(wif.time, "sleep", Mock())
    refresh = Mock()
    monkeypatch.setattr(wif, "refresh", refresh)
    assert wif.run_child(["-m", "example"], tmp_path / "jwt") == 3
    refresh.assert_called_once()
    child.terminate.assert_not_called()


def test_failed_renewal_terminates_child(monkeypatch, tmp_path):
    child = Mock()
    child.poll.return_value = None
    monkeypatch.setattr(wif.subprocess, "Popen", Mock(return_value=child))
    monkeypatch.setattr(wif.time, "monotonic", Mock(side_effect=[0, 2401]))
    monkeypatch.setattr(
        wif, "refresh", Mock(side_effect=wif.AuthenticationError("failed"))
    )
    with pytest.raises(wif.AuthenticationError):
        wif.run_child(["-m", "example"], tmp_path / "jwt")
    child.terminate.assert_called_once()


def test_json_post_uses_bearer_header(monkeypatch):
    response = Mock()
    response.read.return_value = json.dumps({"ok": True}).encode()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    opener = Mock(return_value=response)
    monkeypatch.setattr(wif, "urlopen", opener)
    assert wif.request_json(
        "https://example.test", "test", bearer="fictional", data={"x": 1}
    ) == {"ok": True}
    request = opener.call_args.args[0]
    assert request.headers["Authorization"] == "Bearer fictional"
    assert json.loads(request.data) == {"x": 1}
