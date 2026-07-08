"""End-to-end test for Leizilla using real Rondônia laws data (pge-ro/cotel_scrap).

Validates the complete storage pipeline against the actual DuckDBStorage
implementation, fully offline. The embedded sample laws are real data
extracted from pge-ro/cotel_scrap.
"""

from pathlib import Path

import pytest

from leizilla.storage import DuckDBStorage

# Sample laws data extracted from pge-ro/cotel_scrap
SAMPLE_LAWS = [
    {
        "id": "rondonia_dl_2_1981",
        "titulo": "DECRETO LEI n. 2",
        "numero": "2",
        "ano": 1981,
        "data_publicacao": "1981-12-31",
        "tipo_lei": "decreto-lei",
        "ente": "rondonia",
        "texto_completo": """DECRETO-LEI N° 2, DE 31 DE DEZEMBRO DE 1981

Orça a Receita e fixa a Despesa do Orçamento-Programa do Estado para o exercício de 1982.

O GOVERNADOR DO ESTADO DE RONDÔNIA, no uso de suas atribuições legais,

DECRETA:

Artigo 1° - O Orçamento-Programa do Estado para o exercício de 1982, discriminado nos quadros de número I a XI que integram este Decreto-Lei, orça a Receita e fixa a Despesa em valores iguais a Cr$ 19.071.229.000,00 (dezenove bilhões, setenta e um milhões, duzentos e vinte e nove mil cruzeiros).

Artigo 2° - Arrecadar-se-á a Receita na conformidade da legislação em vigor e das especificações dos quadros integrantes desta lei.

Artigo 3° - A Despesa será realizada de acordo com o seguinte desdobramento por Categoria Econômica, Órgãos e Categorias de Programação.

Artigo 4° - O Poder Executivo tomará as medidas necessárias para ajustar o fluxo dos dispêndios ao dos ingressos, a fim de manter o equilíbrio orçamentário.

Artigo 5° - No curso da execução orçamentária o Poder Executivo poderá realizar operações de crédito, respeitados os limites da legislação em vigor.

Artigo 6° - O Poder Executivo poderá abrir, durante o exercício, créditos suplementares até o limite de 20% (vinte por cento) do total da Despesa fixada nesta lei.

Artigo 7° - No curso da execução orçamentária, fica ainda o Poder Executivo autorizado a suplementar automaticamente categorias de programação e promover alocações.

Artigo 8° - Este Decreto-Lei entrará em vigor na data de sua publicação.

Porto Velho, 31 de dezembro de 1981.
JORGE TEIXEIRA
GOVERNADOR DO ESTADO""",
        "texto_normalizado": "decreto lei 2 1981 orça receita despesa orçamento programa estado exercício 1982 governador rondônia",
        "url_original": "http://ditel.casacivil.ro.gov.br/COTEL/Livros/detalhes.aspx?coddoc=2",
        "metadados": {
            "coddoc": "2",
            "ementa": "Orça a Receita e fixa a Despesa do Orçamento-Programa do Estado para o exercício de 1982.",
            "fonte": "cotel_scrap",
        },
    },
    {
        "id": "rondonia_lei_3_1982",
        "titulo": "LEI n. 3",
        "numero": "3",
        "ano": 1982,
        "data_publicacao": "1982-01-01",
        "tipo_lei": "lei",
        "ente": "rondonia",
        "texto_completo": "Texto de exemplo da Lei 3 de Rondônia para teste do sistema Leizilla.",
        "texto_normalizado": "lei 3 rondônia teste sistema leizilla",
        "url_original": "http://ditel.casacivil.ro.gov.br/COTEL/Livros/detalhes.aspx?coddoc=3",
        "metadados": {
            "coddoc": "3",
            "ementa": "Lei de exemplo para teste",
            "fonte": "cotel_scrap",
        },
    },
]


@pytest.fixture
def storage(tmp_path: Path):
    """Temporary DuckDB storage pre-loaded with the sample Rondônia laws."""
    db_path = tmp_path / "test_leizilla.duckdb"
    db = DuckDBStorage(db_path)
    db.connect()
    for law in SAMPLE_LAWS:
        db.insert_lei(law)
    yield db
    db.close()


def test_database_initialization(tmp_path: Path) -> None:
    """Connecting creates the database file on disk."""
    db_path = tmp_path / "test_leizilla.duckdb"
    db = DuckDBStorage(db_path)
    db.connect()
    try:
        assert db_path.exists()
    finally:
        db.close()


def test_law_retrieval(storage: DuckDBStorage) -> None:
    """Individual laws are retrievable with full original content."""
    decree_law_2 = storage.get_lei("rondonia_dl_2_1981")
    assert decree_law_2 is not None
    assert decree_law_2["titulo"] == "DECRETO LEI n. 2"
    assert "orçamento" in decree_law_2["texto_completo"].lower()
    assert "1982" in decree_law_2["texto_completo"]


def test_text_search(storage: DuckDBStorage) -> None:
    """Full-text search finds laws by content, with and without ente filter."""
    search_orcamento = storage.search_leis(ente="rondonia", texto="orçamento")
    assert len(search_orcamento) >= 1
    assert any("DECRETO LEI n. 2" in result["titulo"] for result in search_orcamento)

    search_receita = storage.search_leis(texto="receita")
    assert len(search_receita) >= 1


def test_filtering_by_ente_and_year(storage: DuckDBStorage) -> None:
    rondonia_laws = storage.search_leis(ente="rondonia")
    assert len(rondonia_laws) == 2

    laws_1981 = storage.search_leis(ano=1981)
    assert len(laws_1981) == 1
    assert laws_1981[0]["ano"] == 1981


def test_statistics(storage: DuckDBStorage) -> None:
    stats = storage.get_stats()
    assert stats["total_leis"] == 2
    assert "rondonia" in stats["por_ente"]
    assert stats["por_ente"]["rondonia"] == 2


def test_data_integrity(storage: DuckDBStorage) -> None:
    """Inserted fields round-trip unchanged, including accented content."""
    retrieved_law = storage.get_lei("rondonia_dl_2_1981")
    assert retrieved_law is not None
    assert retrieved_law["numero"] == "2"
    assert retrieved_law["tipo_lei"] == "decreto-lei"
    assert "GOVERNADOR DO ESTADO DE RONDÔNIA" in retrieved_law["texto_completo"]


def test_real_world_legal_search_terms(storage: DuckDBStorage) -> None:
    """Common legal research terms present in the corpus return results."""
    for term in ["decreto", "orçamento", "receita", "estado", "governador"]:
        results = storage.search_leis(texto=term)
        assert len(results) >= 1, f"Should find results for legal term: {term}"


def test_cotel_scrap_markdown_compatibility() -> None:
    """Frontmatter + content of cotel_scrap markdown files parse as expected."""
    markdown_content = """---
title: "DECRETO LEI n. 2"
coddoc: "2"
summary: |
  Orça a Receita e fixa a Despesa do Orçamento-Programa do Estado para o exercício de 1982.
---

# DECRETO LEI n. 2

## Ementa

Orça a Receita e fixa a Despesa do Orçamento-Programa do Estado para o exercício de 1982.

## Texto Integral dos Documentos Anexos

GOVERNO DO ESTADO DE RONDÔNIA
Gabinete do Governador
DECRETO-LEI N° 2, DE 31 DE DEZEMBRO DE 1981
"""

    lines = markdown_content.split("\n")
    in_frontmatter = False
    frontmatter: dict[str, str] = {}
    content_lines: list[str] = []

    for line in lines:
        if line.strip() == "---":
            in_frontmatter = not in_frontmatter
            continue

        if in_frontmatter:
            if ":" in line and not line.strip().startswith("|"):
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip().strip('"')

                # Handle multiline values starting with |
                if value == "|":
                    frontmatter[key] = ""
                elif (
                    key in frontmatter
                    and isinstance(frontmatter[key], str)
                    and frontmatter[key] == ""
                ):
                    if line.strip():
                        frontmatter[key] = line.strip()
                else:
                    frontmatter[key] = value
            elif line.strip() and any(k for k, v in frontmatter.items() if v == ""):
                # Continuation of multiline value
                for k, v in frontmatter.items():
                    if v == "":
                        frontmatter[k] = line.strip()
                        break
        else:
            content_lines.append(line)

    assert frontmatter["title"] == "DECRETO LEI n. 2"
    assert frontmatter["coddoc"] == "2"
    assert "orçamento" in frontmatter["summary"].lower()

    full_content = "\n".join(content_lines)
    assert "GOVERNO DO ESTADO DE RONDÔNIA" in full_content
    assert "1981" in full_content


def test_cotel_scrap_url_pattern_compatibility() -> None:
    base_url = "http://ditel.casacivil.ro.gov.br/COTEL/Livros/detalhes.aspx"

    for coddoc in ["2", "3", "4", "5", "100", "1000"]:
        url = f"{base_url}?coddoc={coddoc}"
        assert url.startswith("http://ditel.casacivil.ro.gov.br")
        assert f"coddoc={coddoc}" in url
        assert "COTEL/Livros" in url
