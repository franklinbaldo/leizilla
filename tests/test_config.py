"""Testes unitários para leizilla.config.

config.py lê variáveis de ambiente no momento do import, então os testes
recarregam o módulo (importlib.reload) sob um ambiente controlado e
restauram o estado original ao final.
"""

import importlib
import os
import types
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

import leizilla.config as config

ENV_VARS = [
    "DATA_DIR",
    "DUCKDB_PATH",
    "IA_ACCESS_KEY",
    "IAS3_ACCESS_KEY",
    "IA_SECRET_KEY",
    "IAS3_SECRET_KEY",
    "ANTHROPIC_API_KEY",
    "CRAWLER_DELAY",
    "CRAWLER_RETRIES",
    "CRAWLER_TIMEOUT",
]


@pytest.fixture
def reload_config() -> Iterator[Callable[..., types.ModuleType]]:
    """Recarrega config com um ambiente controlado; restaura tudo no teardown."""
    saved = {var: os.environ.get(var) for var in ENV_VARS}

    def _reload(**env: str) -> types.ModuleType:
        for var in ENV_VARS:
            os.environ.pop(var, None)
        for key, value in env.items():
            os.environ[key] = value
        return importlib.reload(config)

    yield _reload

    for var, value in saved.items():
        if value is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = value
    importlib.reload(config)


def test_defaults(reload_config: Callable[..., types.ModuleType]) -> None:
    """Sem env vars, todos os valores assumem os defaults documentados."""
    cfg = reload_config()

    assert cfg.DUCKDB_PATH == cfg.DATA_DIR / "leizilla.duckdb"
    assert cfg.CRAWLER_DELAY == 2000
    assert cfg.CRAWLER_RETRIES == 3
    assert cfg.CRAWLER_TIMEOUT == 30000
    assert cfg.IA_ACCESS_KEY is None
    assert cfg.IA_SECRET_KEY is None
    assert cfg.ANTHROPIC_API_KEY is None


def test_paths_derived_from_project_root(
    reload_config: Callable[..., types.ModuleType],
) -> None:
    """Sem env var, DATA_DIR e TEMP_DIR derivam de PROJECT_ROOT e são criados."""
    cfg = reload_config()

    assert cfg.DATA_DIR == cfg.PROJECT_ROOT / "data"
    assert cfg.TEMP_DIR == cfg.DATA_DIR / "temp"
    assert cfg.DATA_DIR.is_dir()
    assert cfg.TEMP_DIR.is_dir()


def test_data_dir_env_override(
    reload_config: Callable[..., types.ModuleType],
    tmp_path: Path,
) -> None:
    """DATA_DIR respeita a env var documentada; diretórios são criados."""
    custom = tmp_path / "meus-dados"
    cfg = reload_config(DATA_DIR=str(custom))

    assert cfg.DATA_DIR == custom
    assert cfg.TEMP_DIR == custom / "temp"
    assert cfg.DUCKDB_PATH == custom / "leizilla.duckdb"
    assert custom.is_dir()
    assert (custom / "temp").is_dir()


def test_crawler_params_are_ints(
    reload_config: Callable[..., types.ModuleType],
) -> None:
    cfg = reload_config()

    assert isinstance(cfg.CRAWLER_DELAY, int)
    assert isinstance(cfg.CRAWLER_RETRIES, int)
    assert isinstance(cfg.CRAWLER_TIMEOUT, int)


def test_duckdb_path_env_override(
    reload_config: Callable[..., types.ModuleType],
) -> None:
    cfg = reload_config(DUCKDB_PATH="/tmp/custom/leizilla-test.duckdb")

    assert isinstance(cfg.DUCKDB_PATH, Path)
    assert cfg.DUCKDB_PATH == Path("/tmp/custom/leizilla-test.duckdb")


def test_crawler_env_overrides(reload_config: Callable[..., types.ModuleType]) -> None:
    cfg = reload_config(
        CRAWLER_DELAY="500",
        CRAWLER_RETRIES="7",
        CRAWLER_TIMEOUT="60000",
    )

    assert cfg.CRAWLER_DELAY == 500
    assert cfg.CRAWLER_RETRIES == 7
    assert cfg.CRAWLER_TIMEOUT == 60000


def test_api_key_env_overrides(reload_config: Callable[..., types.ModuleType]) -> None:
    cfg = reload_config(
        IA_ACCESS_KEY="ia-access",
        IA_SECRET_KEY="ia-secret",
        ANTHROPIC_API_KEY="sk-ant-test",
    )

    assert cfg.IA_ACCESS_KEY == "ia-access"
    assert cfg.IA_SECRET_KEY == "ia-secret"
    assert cfg.ANTHROPIC_API_KEY == "sk-ant-test"


def test_ia_keys_fall_back_to_ias3_vars(
    reload_config: Callable[..., types.ModuleType],
) -> None:
    """IA_* ausentes caem para as variantes IAS3_* (compat com `ia configure`)."""
    cfg = reload_config(IAS3_ACCESS_KEY="s3-access", IAS3_SECRET_KEY="s3-secret")

    assert cfg.IA_ACCESS_KEY == "s3-access"
    assert cfg.IA_SECRET_KEY == "s3-secret"


def test_ia_keys_prefer_primary_over_ias3(
    reload_config: Callable[..., types.ModuleType],
) -> None:
    cfg = reload_config(
        IA_ACCESS_KEY="primary",
        IAS3_ACCESS_KEY="fallback",
        IA_SECRET_KEY="primary-secret",
        IAS3_SECRET_KEY="fallback-secret",
    )

    assert cfg.IA_ACCESS_KEY == "primary"
    assert cfg.IA_SECRET_KEY == "primary-secret"


def test_invalid_crawler_delay_raises(
    reload_config: Callable[..., types.ModuleType],
) -> None:
    """Comportamento atual: env var não numérica quebra o import com ValueError.

    config.py não trata valores inválidos — um typo em CRAWLER_DELAY vira
    crash no import. Este teste documenta o comportamento vigente.
    """
    with pytest.raises(ValueError):
        reload_config(CRAWLER_DELAY="not-a-number")
