"""Test pipeline validation specifically for Rondônia Leis Complementares and UUIDv5 manifest.csv."""

import hashlib
import uuid
import csv
from unittest.mock import patch, MagicMock


from leizilla.publisher import InternetArchivePublisher, update_ia_manifest
from leizilla.ia_utils import (
    get_range_identifier,
    get_ia_filename,
    resolve_ia_id_to_url,
)


class TestRondoniaLCManifestPipeline:
    """Valida o pipeline completo de upload, nomenclatura e manifest.csv para Leis Complementares de Rondônia."""

    def test_rondonia_lc_nomenclature_and_range(self):
        # Dado uma Lei Complementar nº 42 de Rondônia Casa Civil (descoberta via Files/LC42.pdf)
        ente = "ro"
        fonte = "casacivil"
        tipo = "lc"
        num = 42

        # 1. Valida a geração do range do IA (segregado por tipo 'lc')
        range_id = get_range_identifier(ente, fonte, tipo, num)
        assert range_id == "leizilla_ro_casacivil_lc_0001-1000"

        # 2. Valida a geração do filename baseado em UUIDv5 do conteúdo dos bytes
        dummy_content = b"PDF content of Lei Complementar 42"
        from leizilla.ia_utils import get_uuid5_hash

        hash_8 = get_uuid5_hash(dummy_content)

        filename = get_ia_filename(num, ".pdf", hash_8=hash_8)
        # O arquivo físico omite o tipo 'lc' e anexa o hash determinístico da versão
        assert filename == f"000042_{hash_8}.pdf"

        # 3. Valida a resolução transparente da URL de download direto a partir do ID bruto DuckDB legado
        legacy_ia_id = "leizilla-raw-ro-casacivil-lc-00042"
        resolved_url = resolve_ia_id_to_url(legacy_ia_id, ".pdf", hash_8=hash_8)
        expected_url = f"https://archive.org/download/leizilla_ro_casacivil_lc_0001-1000/000042_{hash_8}.pdf"
        assert resolved_url == expected_url

    def test_incremental_manifest_csv_generation(self, tmp_path):
        range_id = "leizilla_ro_casacivil_lc_0001-1000"
        filename = "000042_a1b2c3d4.pdf"
        url_original = "http://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/LC42.pdf"

        import urllib.error

        # Simula o upload idempotente do manifest.csv
        # Como o IA ainda não tem o manifest (retorna 404), começamos com um manifest limpo
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("404")):
            manifest_path = update_ia_manifest(
                range_id, filename, url_original, tmp_path
            )

        assert manifest_path.exists()

        # Lê e valida os dados do CSV gerado
        with open(manifest_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            row = next(reader)

        assert header == ["filename", "url"]
        assert row == [filename, url_original]

    @patch("subprocess.run")
    def test_complete_upload_raw_lc_rondonia(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)

        pub = InternetArchivePublisher()
        pub.access_key = "fake-key"
        pub.secret_key = "fake-secret"

        pdf_path = tmp_path / "LC42.pdf"
        pdf_bytes = b"PDF content for LC 42"
        pdf_path.write_bytes(pdf_bytes)

        lei_data = {
            "ente": "ro",
            "fonte": "casacivil",
            "chave": "lc-00042",
            "url_original": "http://ditel.casacivil.ro.gov.br/COTEL/Livros/Files/LC42.pdf",
        }

        import urllib.error

        # Mock de rede do update_ia_manifest
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("404")):
            res = pub.upload_raw(pdf_path, lei_data, pdf_bytes, fetched_from="wayback")

        assert res["success"] is True
        assert (
            res["ia_url"]
            == "https://archive.org/details/leizilla_ro_casacivil_lc_0001-1000"
        )

        # Verifica que o subprocess.run chamou a CLI do IA com os metadados corretos
        args = mock_run.call_args[0][0]
        assert "ia" in args
        assert "upload" in args
        assert "leizilla_ro_casacivil_lc_0001-1000" in args

        # O arquivo PDF no upload deve conter o hash determinístico baseado em UUIDv5
        sha256 = hashlib.sha256(pdf_bytes).hexdigest()
        hash_8 = str(uuid.uuid5(uuid.NAMESPACE_DNS, sha256))[:8]
        expected_pdf_name = f"000042_{hash_8}.pdf"

        # Verifica que o PDF renomeado temporariamente com UUIDv5 foi incluído no upload
        pdf_arg = next((a for a in args if a.endswith(expected_pdf_name)), None)
        assert pdf_arg is not None
