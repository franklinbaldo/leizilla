"""Verificação de pré-requisitos de produção (`leizilla doctor`, RFC-0004 §2).

Checks essenciais (faltando ⇒ exit 1 no CLI):
- credenciais IA (`IA_ACCESS_KEY`/`IA_SECRET_KEY`, com fallback `IAS3_*` como
  em `config.py`) e `ANTHROPIC_API_KEY` presentes — sem nunca imprimir valores;
- diretório de dados existente/criável e gravável;
- DuckDB local abre no caminho configurado.

Checks informativos (fail-open, nunca afetam o exit code):
- conectividade com archive.org e web.archive.org.

A lógica é injetável (env, funções de check) para permitir testes 100% offline.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional

STATUS_OK = "ok"
STATUS_FALHA = "falha"
STATUS_AVISO = "aviso"

IA_URL = "https://archive.org"
WAYBACK_URL = "https://web.archive.org"
HTTP_TIMEOUT_SECONDS = 5.0

RFC_DOC = "docs/rfc/0004-go-live-rondonia.md"

# (nome exibido, [env vars aceitas — a primeira presente e não-vazia satisfaz])
_ENV_CHECKS: list[tuple[str, list[str]]] = [
    ("IA_ACCESS_KEY", ["IA_ACCESS_KEY", "IAS3_ACCESS_KEY"]),
    ("IA_SECRET_KEY", ["IA_SECRET_KEY", "IAS3_SECRET_KEY"]),
    ("ANTHROPIC_API_KEY", ["ANTHROPIC_API_KEY"]),
]


@dataclass(frozen=True)
class CheckResult:
    """Resultado de um check individual do doctor."""

    nome: str
    status: str  # STATUS_OK | STATUS_FALHA | STATUS_AVISO
    essencial: bool
    detalhe: str = ""


def check_env_var(env: Mapping[str, str], nomes: list[str]) -> bool:
    """True se alguma das variáveis está presente e não-vazia (nunca lê o valor além disso)."""
    return any(env.get(nome, "").strip() for nome in nomes)


def check_data_dir_writable(data_dir: Path) -> tuple[bool, str]:
    """Verifica que o diretório de dados existe (ou é criável) e é gravável."""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / f".doctor-probe-{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        probe.unlink()
        return True, f"{data_dir} gravável"
    except OSError as e:
        return False, f"{data_dir}: {e}"


def check_duckdb_opens(db_path: Path) -> tuple[bool, str]:
    """Verifica que o DuckDB local abre (e fecha) no caminho configurado."""
    try:
        from leizilla.storage import DuckDBStorage

        db = DuckDBStorage(db_path=db_path)
        db.connect()
        db.close()
        return True, f"{db_path} abre"
    except Exception as e:
        return False, f"{db_path}: {e}"


def default_http_check(url: str, timeout: float = HTTP_TIMEOUT_SECONDS) -> bool:
    """HEAD leve; qualquer resposta do servidor (<500) conta como conectividade."""
    import requests

    resp = requests.head(url, timeout=timeout, allow_redirects=True)
    return resp.status_code < 500


def run_doctor(
    env: Optional[Mapping[str, str]] = None,
    data_dir: Optional[Path] = None,
    duckdb_path: Optional[Path] = None,
    http_check_fn: Optional[Callable[[str], bool]] = None,
    write_check_fn: Optional[Callable[[Path], tuple[bool, str]]] = None,
    db_check_fn: Optional[Callable[[Path], tuple[bool, str]]] = None,
) -> tuple[list[CheckResult], bool]:
    """Roda todos os checks e retorna (resultados, essencial_ok).

    Todos os colaboradores são injetáveis para testes offline; os defaults
    usam `os.environ`, `leizilla.config` e a rede de verdade.
    """
    from leizilla import config

    if env is None:
        env = os.environ
    if data_dir is None:
        data_dir = config.DATA_DIR
    if duckdb_path is None:
        duckdb_path = config.DUCKDB_PATH
    if http_check_fn is None:
        http_check_fn = default_http_check
    if write_check_fn is None:
        write_check_fn = check_data_dir_writable
    if db_check_fn is None:
        db_check_fn = check_duckdb_opens

    results: list[CheckResult] = []

    # 1. Variáveis de ambiente essenciais (sem vazar valores).
    for nome, aliases in _ENV_CHECKS:
        presente = check_env_var(env, aliases)
        results.append(
            CheckResult(
                nome=f"variável {nome}",
                status=STATUS_OK if presente else STATUS_FALHA,
                essencial=True,
                detalhe="presente" if presente else "ausente ou vazia",
            )
        )

    # 2. Diretório de dados gravável.
    ok, detalhe = write_check_fn(data_dir)
    results.append(
        CheckResult(
            nome="diretório de dados gravável",
            status=STATUS_OK if ok else STATUS_FALHA,
            essencial=True,
            detalhe=detalhe,
        )
    )

    # 3. DuckDB local abre.
    ok, detalhe = db_check_fn(duckdb_path)
    results.append(
        CheckResult(
            nome="DuckDB local abre",
            status=STATUS_OK if ok else STATUS_FALHA,
            essencial=True,
            detalhe=detalhe,
        )
    )

    # 4. Conectividade (informativo, fail-open: falha vira aviso).
    for nome, url in (
        ("conectividade archive.org", IA_URL),
        ("conectividade web.archive.org", WAYBACK_URL),
    ):
        try:
            reachable = http_check_fn(url)
        except Exception as e:
            reachable = False
            detalhe = f"{url}: {e}"
        else:
            detalhe = url if reachable else f"{url} inacessível"
        results.append(
            CheckResult(
                nome=nome,
                status=STATUS_OK if reachable else STATUS_AVISO,
                essencial=False,
                detalhe=detalhe,
            )
        )

    essencial_ok = all(r.status == STATUS_OK for r in results if r.essencial)
    return results, essencial_ok


def format_results(results: list[CheckResult], essencial_ok: bool) -> list[str]:
    """Formata o checklist linha a linha + resumo final (para o CLI)."""
    marcadores = {STATUS_OK: "OK", STATUS_FALHA: "FALHA", STATUS_AVISO: "AVISO"}
    lines = [f"[{marcadores[r.status]:>5}] {r.nome} — {r.detalhe}" for r in results]
    faltando = sum(1 for r in results if r.essencial and r.status != STATUS_OK)
    if essencial_ok:
        lines.append("Pronto para produção.")
    else:
        lines.append(
            f"{faltando} pré-requisito(s) essencial(is) faltando — ver {RFC_DOC}"
        )
    return lines
