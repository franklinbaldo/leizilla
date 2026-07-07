"""Testes do `leizilla doctor` (RFC-0004 §2) — 100% offline, checks injetados."""

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from leizilla.cli import app
from leizilla.doctor import (
    STATUS_AVISO,
    STATUS_FALHA,
    STATUS_OK,
    check_env_var,
    format_results,
    run_doctor,
)

runner = CliRunner()

ENV_OK = {
    "IA_ACCESS_KEY": "ia-access-sigiloso-123",
    "IA_SECRET_KEY": "ia-secret-sigiloso-456",
    "ANTHROPIC_API_KEY": "sk-ant-sigiloso-789",
}

ALL_ENV_VARS = [
    "IA_ACCESS_KEY",
    "IA_SECRET_KEY",
    "IAS3_ACCESS_KEY",
    "IAS3_SECRET_KEY",
    "ANTHROPIC_API_KEY",
]


def _ok_write(path: Path) -> tuple[bool, str]:
    return True, f"{path} gravável"


def _ok_db(path: Path) -> tuple[bool, str]:
    return True, f"{path} abre"


def _http_ok(url: str) -> bool:
    return True


def _run(env: dict[str, str], **overrides):
    """run_doctor com todos os colaboradores injetados (nenhuma rede/disco)."""
    kwargs = {
        "env": env,
        "data_dir": Path("/fake/data"),
        "duckdb_path": Path("/fake/data/leizilla.duckdb"),
        "http_check_fn": _http_ok,
        "write_check_fn": _ok_write,
        "db_check_fn": _ok_db,
    }
    kwargs.update(overrides)
    return run_doctor(**kwargs)


# --- run_doctor (função pura) ---


def test_all_essentials_ok():
    results, essencial_ok = _run(ENV_OK)
    assert essencial_ok is True
    assert all(r.status == STATUS_OK for r in results)
    # 3 env vars + data dir + duckdb essenciais, 2 conectividades informativas.
    assert sum(r.essencial for r in results) == 5
    assert sum(not r.essencial for r in results) == 2


def test_missing_ia_keys_fails_essentials():
    env = {"ANTHROPIC_API_KEY": "sk-ant-x"}
    results, essencial_ok = _run(env)
    assert essencial_ok is False
    by_name = {r.nome: r for r in results}
    assert by_name["variável IA_ACCESS_KEY"].status == STATUS_FALHA
    assert by_name["variável IA_SECRET_KEY"].status == STATUS_FALHA
    assert by_name["variável ANTHROPIC_API_KEY"].status == STATUS_OK


def test_missing_anthropic_key_fails_essentials():
    env = {k: v for k, v in ENV_OK.items() if k != "ANTHROPIC_API_KEY"}
    results, essencial_ok = _run(env)
    assert essencial_ok is False
    by_name = {r.nome: r for r in results}
    assert by_name["variável ANTHROPIC_API_KEY"].status == STATUS_FALHA


def test_empty_value_counts_as_missing():
    env = dict(ENV_OK, IA_SECRET_KEY="   ")
    _, essencial_ok = _run(env)
    assert essencial_ok is False


def test_ias3_fallback_satisfies_ia_keys():
    # config.py aceita IAS3_ACCESS_KEY/IAS3_SECRET_KEY; o doctor espelha isso.
    env = {
        "IAS3_ACCESS_KEY": "a",
        "IAS3_SECRET_KEY": "b",
        "ANTHROPIC_API_KEY": "c",
    }
    _, essencial_ok = _run(env)
    assert essencial_ok is True


def test_http_failure_is_warning_not_error():
    results, essencial_ok = _run(ENV_OK, http_check_fn=lambda url: False)
    assert essencial_ok is True  # conectividade nunca afeta o essencial
    avisos = [r for r in results if r.status == STATUS_AVISO]
    assert len(avisos) == 2
    assert all(not r.essencial for r in avisos)


def test_http_exception_is_warning_fail_open():
    def _boom(url: str) -> bool:
        raise ConnectionError("sem rede")

    results, essencial_ok = _run(ENV_OK, http_check_fn=_boom)
    assert essencial_ok is True
    avisos = [r for r in results if r.status == STATUS_AVISO]
    assert len(avisos) == 2
    assert any("sem rede" in r.detalhe for r in avisos)


def test_unwritable_data_dir_fails_essentials():
    def _no_write(path: Path) -> tuple[bool, str]:
        return False, f"{path}: Permission denied"

    results, essencial_ok = _run(ENV_OK, write_check_fn=_no_write)
    assert essencial_ok is False
    by_name = {r.nome: r for r in results}
    assert by_name["diretório de dados gravável"].status == STATUS_FALHA


def test_duckdb_failure_fails_essentials():
    def _no_db(path: Path) -> tuple[bool, str]:
        return False, f"{path}: IO Error"

    results, essencial_ok = _run(ENV_OK, db_check_fn=_no_db)
    assert essencial_ok is False
    by_name = {r.nome: r for r in results}
    assert by_name["DuckDB local abre"].status == STATUS_FALHA


def test_check_env_var_never_reads_beyond_presence():
    assert check_env_var({"X": "value"}, ["X"]) is True
    assert check_env_var({}, ["X"]) is False
    assert check_env_var({"X": ""}, ["X"]) is False
    assert check_env_var({"Y": "v"}, ["X", "Y"]) is True  # alias/fallback


def test_format_results_summary_lines():
    results, essencial_ok = _run(ENV_OK)
    lines = format_results(results, essencial_ok)
    assert lines[-1] == "Pronto para produção."

    results, essencial_ok = _run({})
    lines = format_results(results, essencial_ok)
    assert "essencial(is) faltando" in lines[-1]
    assert "docs/rfc/0004-go-live-rondonia.md" in lines[-1]


# --- CLI (`leizilla doctor`) ---


@pytest.fixture
def offline_checks(monkeypatch):
    """Neutraliza os defaults do doctor: sem rede, sem disco, env controlado."""
    for var in ALL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    with (
        patch("leizilla.doctor.default_http_check", _http_ok),
        patch("leizilla.doctor.check_data_dir_writable", _ok_write),
        patch("leizilla.doctor.check_duckdb_opens", _ok_db),
    ):
        yield monkeypatch


def test_cli_all_ok_exits_zero(offline_checks):
    for var, value in ENV_OK.items():
        offline_checks.setenv(var, value)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Pronto para produção." in result.output
    assert "FALHA" not in result.output


def test_cli_never_leaks_secret_values(offline_checks):
    for var, value in ENV_OK.items():
        offline_checks.setenv(var, value)

    result = runner.invoke(app, ["doctor"])

    for value in ENV_OK.values():
        assert value not in result.output
    assert "presente" in result.output


def test_cli_missing_ia_keys_exits_one(offline_checks):
    offline_checks.setenv("ANTHROPIC_API_KEY", "sk-ant-x")

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "IA_ACCESS_KEY" in result.output
    assert "ausente" in result.output
    assert "faltando" in result.output


def test_cli_missing_anthropic_key_exits_one(offline_checks):
    offline_checks.setenv("IA_ACCESS_KEY", "a")
    offline_checks.setenv("IA_SECRET_KEY", "b")

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY" in result.output


def test_cli_connectivity_failure_is_warning_exit_zero(offline_checks):
    for var, value in ENV_OK.items():
        offline_checks.setenv(var, value)

    def _boom(url: str) -> bool:
        raise ConnectionError("offline")

    with patch("leizilla.doctor.default_http_check", _boom):
        result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "AVISO" in result.output
    assert "Pronto para produção." in result.output


def test_cli_unwritable_data_dir_exits_one(offline_checks):
    for var, value in ENV_OK.items():
        offline_checks.setenv(var, value)

    def _no_write(path: Path) -> tuple[bool, str]:
        return False, f"{path}: Permission denied"

    with patch("leizilla.doctor.check_data_dir_writable", _no_write):
        result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "diretório de dados" in result.output
