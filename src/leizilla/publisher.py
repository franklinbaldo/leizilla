"""Publicação no Internet Archive e exportação de datasets."""

import hashlib
import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from leizilla import config
from leizilla import storage as storage_module


class InternetArchivePublisher:
    """Upload para IA e geração de datasets Parquet."""

    def __init__(self) -> None:
        self.access_key = config.IA_ACCESS_KEY
        self.secret_key = config.IA_SECRET_KEY

    def upload_pdf(self, pdf_path: Path, lei_data: Dict[str, Any]) -> Dict[str, Any]:
        """Faz upload de PDF para Internet Archive.

        Retorna dict com 'success', 'url', 'ia_id'.
        """
        if not self.access_key or not self.secret_key:
            return {"success": False, "error": "IA credentials not configured"}

        ente = lei_data.get("ente", "unknown")
        lei_id = lei_data.get("id", "unknown")
        ia_id = f"leizilla-raw-{ente}-casacivil-{lei_id}"

        try:
            result = subprocess.run(
                [
                    "ia",
                    "upload",
                    ia_id,
                    str(pdf_path),
                    "--metadata",
                    f"title:{lei_data.get('titulo', 'Lei')}",
                    "--metadata",
                    "mediatype:texts",
                    "--metadata",
                    f"subject:leis;{ente}",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            ia_url = f"https://archive.org/details/{ia_id}"
            return {"success": True, "url": ia_url, "ia_id": ia_id}
        except subprocess.CalledProcessError as e:
            return {"success": False, "error": e.stderr}

    def export_dataset_parquet(
        self,
        ente: str,
        output_dir: Path,
        ano: Optional[int] = None,
    ) -> Path:
        """Exporta dataset Parquet para o ente."""
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"leizilla-{ente}"
        if ano:
            filename += f"-{ano}"
        filename += ".parquet"
        output_path = output_dir / filename

        db = storage_module.DuckDBStorage()
        db.export_parquet(output_path, ente=ente, ano=ano)
        db.close()
        return output_path
