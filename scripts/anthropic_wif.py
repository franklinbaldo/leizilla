"""Run a Python command with renewable GitHub -> Google -> Anthropic identity.

Only Google ID-token creation is required on the service account, never Google
access-token impersonation. Credentials stay in memory or a private temp file.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class AuthenticationError(RuntimeError):
    """A deliberately credential-free authentication error."""


def request_json(
    url: str, stage: str, *, bearer: str = "", data: dict[str, Any] | None = None
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    request = Request(
        url, headers=headers, data=json.dumps(data).encode() if data else None
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as exc:
        # Never log response bodies, request headers, or a credential-bearing URL.
        raise AuthenticationError(f"{stage}: HTTP {exc.code}") from None
    except (URLError, TimeoutError, ValueError):
        raise AuthenticationError(f"{stage}: transport or JSON failure") from None
    if not isinstance(result, dict):
        raise AuthenticationError(f"{stage}: invalid response")
    return result


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise AuthenticationError(f"Missing configuration: {name}")
    return value


def field(payload: dict[str, Any], key: str, stage: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise AuthenticationError(f"{stage}: missing {key}")
    return value


def google_identity() -> str:
    provider = required("ANTHROPIC_GOOGLE_WIF_PROVIDER")
    service_account = required("ANTHROPIC_GOOGLE_SERVICE_ACCOUNT")
    audience = f"//iam.googleapis.com/{provider}"
    github_url = required("ACTIONS_ID_TOKEN_REQUEST_URL")
    separator = "&" if "?" in github_url else "?"
    github = request_json(
        github_url + separator + urlencode({"audience": audience}),
        "GitHub OIDC",
        bearer=required("ACTIONS_ID_TOKEN_REQUEST_TOKEN"),
    )
    sts = request_json(
        "https://sts.googleapis.com/v1/token",
        "Google STS",
        data={
            "audience": audience,
            "grantType": "urn:ietf:params:oauth:grant-type:token-exchange",
            "requestedTokenType": "urn:ietf:params:oauth:token-type:access_token",
            "scope": "https://www.googleapis.com/auth/cloud-platform",
            "subjectTokenType": "urn:ietf:params:oauth:token-type:jwt",
            "subjectToken": field(github, "value", "GitHub OIDC"),
        },
    )
    identity = request_json(
        "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
        f"{service_account}:generateIdToken",
        "Google ID token",
        bearer=field(sts, "access_token", "Google STS"),
        data={"audience": "https://api.anthropic.com", "includeEmail": True},
    )
    return field(identity, "token", "Google ID token")


def refresh(path: Path) -> None:
    token = google_identity()
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(token)
    temporary.replace(path)


def check(path: Path) -> None:
    import anthropic

    # A fresh client after each Google identity refresh also forces a fresh
    # Anthropic exchange. Both calls are read-only; count_tokens is free.
    for attempt in range(2):
        if attempt:
            refresh(path)
        with anthropic.Anthropic() as client:
            client.models.list(limit=1)
            count = client.messages.count_tokens(
                model="claude-haiku-5-5",
                messages=[{"role": "user", "content": "Authentication check."}],
            )
        print(
            f"Authentication pass {attempt + 1}: models OK, tokens={count.input_tokens}"
        )


def run_child(arguments: list[str], path: Path) -> int:
    # Google JWTs last one hour; Anthropic SDK rereads this file as it renews
    # its own short-lived token. Polling avoids an orphaned background watcher.
    child = subprocess.Popen([sys.executable, *arguments])
    renewal = time.monotonic() + 2400
    try:
        while child.poll() is None:
            if time.monotonic() >= renewal:
                refresh(path)
                renewal = time.monotonic() + 2400
                print("Google identity renewed", flush=True)
            time.sleep(1)
        return int(child.returncode)
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["check", "run"])
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    arguments = args.arguments
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    if args.mode == "run" and not arguments:
        parser.error("run requires Python arguments after --")
    for name in (
        "ANTHROPIC_ORGANIZATION_ID",
        "ANTHROPIC_FEDERATION_RULE_ID",
        "ANTHROPIC_SERVICE_ACCOUNT_ID",
    ):
        required(name)
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_IDENTITY_TOKEN",
    ):
        os.environ.pop(name, None)
    with tempfile.TemporaryDirectory(prefix="leizilla-identity-") as directory:
        path = Path(directory) / "identity.jwt"
        os.environ["ANTHROPIC_IDENTITY_TOKEN_FILE"] = str(path)
        refresh(path)
        if args.mode == "check":
            check(path)
            return 0
        return run_child(arguments, path)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # SDK exceptions may include response details. Report only the type,
        # except for our deliberately sanitized errors.
        message = (
            str(exc) if isinstance(exc, AuthenticationError) else type(exc).__name__
        )
        print(f"Authentication failed: {message}", file=sys.stderr)
        raise SystemExit(1) from None
