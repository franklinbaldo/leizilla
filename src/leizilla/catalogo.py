"""Catálogo oficial como produto público — campos derivados do índice (ADR-0017).

O catálogo **não é uma tabela nova**: é o livro-razão de completude
(``completeness.py``, docs/SCHEMA.md §3.6) estendido com colunas derivadas só do que o
índice oficial da Casa Civil já traz — título, data, ementa e os arquivos com suas
rendições. Este módulo reúne o que é puro e determinístico:

- ``normalizar_busca`` — o texto de busca (minúsculas, sem acento, pontuação
  colapsada), o **mesmo algoritmo** que o portal aplica à consulta;
- ``situacao_da_norma`` — a situação lida do índice (revogada / retificada /
  tem-compilada / sem indicação), com as evidências que a sustentam;
- ``links`` — o melhor link público da norma.

Nada aqui afirma vigência. ``sem-indicacao-de-revogacao`` quer dizer só que o índice
não traz marca de revogação para a norma — não que ela esteja em vigor.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Optional

from leizilla import relacoes

# Situação da norma segundo o índice oficial (docs/SCHEMA.md §3.6).
SITUACAO_REVOGADA = "revogada"
SITUACAO_RETIFICADA = "retificada"
SITUACAO_TEM_COMPILADA = "tem-compilada"
SITUACAO_SEM_INDICACAO = "sem-indicacao-de-revogacao"
SITUACOES_NORMA = (
    SITUACAO_REVOGADA,
    SITUACAO_RETIFICADA,
    SITUACAO_TEM_COMPILADA,
    SITUACAO_SEM_INDICACAO,
)

# Evidências que o índice dá (valores de ``situacao_evidencias``).
EV_RENDICAO_REVOGADO = "rendicao-revogado"
EV_RENDICAO_RETIFICADO = "rendicao-retificado"
EV_RENDICAO_COMPILADA = "rendicao-compilada"
EV_ANOTACAO_REVOGADO = "anotacao-na-ementa"


def normalizar_busca(texto: str) -> str:
    """Minúsculas, sem acentos, tudo que não é ``a-z0-9`` vira um espaço, sem bordas.

    ``"Lei nº 1.234 — Crédito Suplementar"`` → ``"lei n 1 234 credito suplementar"``.
    O portal (``web/src/lib/catalogo.ts``) implementa exatamente o mesmo algoritmo
    na consulta; os dois lados têm testes com os mesmos casos.
    """
    decomposed = unicodedata.normalize("NFD", texto)
    sem_marcas = "".join(
        c for c in decomposed if not unicodedata.category(c).startswith("M")
    )
    return re.sub(r"[^a-z0-9]+", " ", sem_marcas.lower()).strip()


def campo_busca(titulo: str, ementa: str) -> str:
    """O campo ``busca`` de uma norma: título + ementa normalizados."""
    return normalizar_busca(f"{titulo} {ementa}")


def _tem_anotacao_revogada(ementa: str) -> bool:
    """A ementa traz a anotação do índice "REVOGADO PELO …" (total, não parcial)."""
    folded = relacoes.fold(ementa)
    for m in relacoes._ANOTACAO.finditer(folded):
        if (
            m.group("acao").startswith("revogad")
            and "parcialmente" not in folded[m.start() : m.end()]
        ):
            return True
    return False


def situacao_da_norma(rendicoes: Iterable[str], ementa: str) -> tuple[str, list[str]]:
    """``(situacao, evidencias)`` da norma, lidas **só do índice oficial**.

    Prioridade quando há mais de uma marca: ``revogada`` > ``retificada`` >
    ``tem-compilada`` > ``sem-indicacao-de-revogacao``. ``evidencias`` lista todas
    as marcas encontradas, mesmo as que perderam na prioridade.

    - ``revogada``: o índice lista um arquivo de rendição ``revogado`` (nome com
      "REVOGADO"/"REVOGADA") **ou** a ementa traz a anotação "REVOGADO PELO …".
    - ``retificada``: o índice lista um arquivo ``retificado``.
    - ``tem-compilada``: o índice lista uma versão compilada/consolidada.
    - ``sem-indicacao-de-revogacao``: nenhuma das marcas acima. Não é "vigente".
    """
    kinds = set(rendicoes)
    evidencias: list[str] = []
    if "revogado" in kinds:
        evidencias.append(EV_RENDICAO_REVOGADO)
    if _tem_anotacao_revogada(ementa or ""):
        evidencias.append(EV_ANOTACAO_REVOGADO)
    if "retificado" in kinds:
        evidencias.append(EV_RENDICAO_RETIFICADO)
    if "compilada" in kinds:
        evidencias.append(EV_RENDICAO_COMPILADA)
    if EV_RENDICAO_REVOGADO in evidencias or EV_ANOTACAO_REVOGADO in evidencias:
        return SITUACAO_REVOGADA, evidencias
    if EV_RENDICAO_RETIFICADO in evidencias:
        return SITUACAO_RETIFICADA, evidencias
    if EV_RENDICAO_COMPILADA in evidencias:
        return SITUACAO_TEM_COMPILADA, evidencias
    return SITUACAO_SEM_INDICACAO, evidencias


def rendicoes_distintas(arquivos: list[dict[str, Any]]) -> str:
    """Rendições dos arquivos listados, sem repetição, em ordem alfabética, ``,``-separadas."""
    return ",".join(sorted({str(a.get("rendicao") or "outra") for a in arquivos}))


def url_oficial(arquivos: list[dict[str, Any]]) -> Optional[str]:
    """URL do arquivo oficial: o ``original`` se houver, senão o primeiro listado."""
    for a in arquivos:
        if a.get("rendicao") == "original" and a.get("url"):
            return str(a["url"])
    for a in arquivos:
        if a.get("url"):
            return str(a["url"])
    return None


# ---------------------------------------------------------------------------
# Resumo e gates de publicação
# ---------------------------------------------------------------------------


def resumo_relacoes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Contagens das relações para o ``completeness.json``: por verbo e confiança."""
    por_verbo: dict[str, dict[str, int]] = {}
    for r in rows:
        bucket = por_verbo.setdefault(
            str(r["verbo"]), {c: 0 for c in relacoes.CONFIANCAS}
        )
        bucket[str(r["confianca"])] += 1
    return {
        "versao": relacoes.RELACOES_VERSION,
        "total": len(rows),
        "por_verbo": {v: por_verbo[v] for v in relacoes.VERBOS if v in por_verbo},
        "por_confianca": {
            c: sum(1 for r in rows if r["confianca"] == c) for c in relacoes.CONFIANCAS
        },
        "arquivo": relacoes.RELACOES_FILENAME,
    }


def validate_catalogo_files(ledger_path: Any, relacoes_path: Any) -> list[str]:
    """Violações do contrato dos dois Parquets publicados (lista vazia = aprovado).

    Gate de ``leizilla release-catalogo``, no espírito de ``validate_textos_parquet``:
    colunas do contrato, unicidade das chaves, domínios fechados, integridade
    referencial das relações e coerência entre ``confianca`` e ``alvo_id``.
    """
    import duckdb

    from leizilla.completeness import LEDGER_SCHEMA, SITUACAO_LISTADA

    problems: list[str] = []
    conn = duckdb.connect()
    try:
        for path, schema, label in (
            (ledger_path, LEDGER_SCHEMA, "catalogo"),
            (relacoes_path, relacoes.RELACOES_SCHEMA, "relacoes"),
        ):
            cols = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM parquet_schema(?) WHERE name <> 'duckdb_schema'",
                    [str(path)],
                ).fetchall()
            ]
            missing = [c for c in schema if c not in cols]
            if missing:
                problems.append(f"{label}: colunas ausentes: {', '.join(missing)}")
        if problems:
            return problems

        led = f"read_parquet('{str(ledger_path)}')".replace("\\", "/")
        rel = f"read_parquet('{str(relacoes_path)}')".replace("\\", "/")

        def scalar(sql: str) -> int:
            return int(conn.execute(sql).fetchone()[0])  # type: ignore[index]

        if scalar(f"SELECT COUNT(*) - COUNT(DISTINCT norma_id) FROM {led}"):
            problems.append("catalogo: norma_id duplicado")
        listed = f"{led} WHERE situacao = '{SITUACAO_LISTADA}'"
        n_listed = scalar(f"SELECT COUNT(*) FROM {listed}")
        if n_listed == 0:
            problems.append("catalogo: nenhuma norma listada")
        for col in ("titulo", "busca"):
            n = scalar(
                f"SELECT COUNT(*) FROM {listed} AND ({col} IS NULL OR {col} = '')"
            )
            if n:
                problems.append(f"catalogo: {n} norma(s) listada(s) sem {col}")
        quoted = ", ".join(f"'{s}'" for s in SITUACOES_NORMA)
        n = scalar(
            f"SELECT COUNT(*) FROM {listed} AND "
            f"(situacao_norma IS NULL OR situacao_norma NOT IN ({quoted}))"
        )
        if n:
            problems.append(f"catalogo: {n} situacao_norma fora do domínio")

        if scalar(f"SELECT COUNT(*) - COUNT(DISTINCT relacao_id) FROM {rel}"):
            problems.append("relacoes: relacao_id duplicado")
        quoted_v = ", ".join(f"'{v}'" for v in relacoes.VERBOS)
        if scalar(f"SELECT COUNT(*) FROM {rel} WHERE verbo NOT IN ({quoted_v})"):
            problems.append("relacoes: verbo fora do conjunto canônico")
        quoted_c = ", ".join(f"'{c}'" for c in relacoes.CONFIANCAS)
        if scalar(f"SELECT COUNT(*) FROM {rel} WHERE confianca NOT IN ({quoted_c})"):
            problems.append("relacoes: confianca fora do domínio")
        n = scalar(
            f"SELECT COUNT(*) FROM {rel} WHERE origem_id NOT IN "
            f"(SELECT norma_id FROM {led})"
        )
        if n:
            problems.append(f"relacoes: {n} origem_id fora do catálogo")
        n = scalar(
            f"SELECT COUNT(*) FROM {rel} WHERE alvo_id IS NOT NULL AND alvo_id NOT IN "
            f"(SELECT norma_id FROM {led})"
        )
        if n:
            problems.append(f"relacoes: {n} alvo_id fora do catálogo")
        n = scalar(
            f"SELECT COUNT(*) FROM {rel} WHERE (confianca = 'resolvida' AND alvo_id IS NULL) "
            "OR (confianca = 'nao-resolvida' AND alvo_id IS NOT NULL)"
        )
        if n:
            problems.append(
                f"relacoes: {n} linha(s) com confianca incoerente com alvo_id"
            )
        n = scalar(f"SELECT COUNT(*) FROM {rel} WHERE origem_id = alvo_id")
        if n:
            problems.append(f"relacoes: {n} autorreferência(s)")
    finally:
        conn.close()
    return problems


def published_floor(summary: dict[str, Any]) -> Optional[int]:
    """Quantas normas listadas um ``completeness.json`` publicado declara."""
    if isinstance(summary.get("normas_listadas"), int):
        return int(summary["normas_listadas"])
    tipos = summary.get("tipos")
    if not isinstance(tipos, list):
        return None
    values = [t.get("listadas") for t in tipos if isinstance(t, dict)]
    ints = [v for v in values if isinstance(v, int)]
    return sum(ints) if ints else None


def fetch_published_floor(
    ente: str, version: int, *, timeout: int = 20
) -> Optional[int]:
    """Piso publicado: normas listadas no ``completeness.json`` do ponteiro latest.

    ``None`` se nunca foi publicado (404). Qualquer outra falha **levanta**
    ``RuntimeError`` (fail-closed, como o piso de ``versoes`` e de ``textos``): sem
    saber o piso não se publica.
    """
    import json
    import urllib.error
    import urllib.request

    url = (
        f"https://archive.org/download/leizilla-dataset-{ente}-v{version}-latest/"
        "completeness.json"
    )
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "leizilla-crawler/0.1"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise RuntimeError(f"HTTP {e.code} em {url}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError(f"{url}: {e}") from e
    return published_floor(data) if isinstance(data, dict) else None
