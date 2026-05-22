"""Publicação no Internet Archive e exportação de datasets."""

import hashlib
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from leizilla import config
from leizilla import storage as storage_module

_DATASET_IDENTIFIER_RE = r"^leizilla-dataset-(?P<ente>[a-z][a-z0-9-]*)-v(?P<version>\d+)$"

_USER_AGENT = "leizilla-crawler/0.1"


def _raw_identifier(ente: str, fonte: str, chave: str) -> str:
    """Constrói IA identifier para raw item conforme SCHEMA.md §1.2."""
    return f"leizilla-raw-{ente}-{fonte}-{chave}"


def _bundle_identifier(ente: str, fonte: str, dt: Optional[datetime] = None) -> str:
    """Constrói IA identifier para bundle semanal conforme SCHEMA.md §1.2."""
    d = dt or datetime.now(tz=timezone.utc)
    iso = d.isocalendar()
    return f"leizilla-bundle-{ente}-{fonte}-{iso[0]}-W{iso[1]:02d}"


def build_raw_meta(
    lei_data: Dict[str, Any],
    pdf_bytes: bytes,
    fetched_from: str,
    wayback_url: Optional[str] = None,
    wayback_blocked_robots: bool = False,
) -> Dict[str, Any]:
    """Constrói raw_meta.json conforme SCHEMA.md §2.1."""
    ente = str(lei_data.get("ente", "unknown"))
    fonte = str(lei_data.get("fonte", "casacivil"))
    chave = str(lei_data.get("chave") or lei_data.get("id", "unknown"))
    return {
        "leizilla_meta_version": "0.1",
        "ente": ente,
        "fonte": fonte,
        "chave": chave,
        "fonte_url": lei_data.get("url_original"),
        "data_captura": datetime.now(tz=timezone.utc).isoformat(),
        "hash_pdf": f"sha256:{hashlib.sha256(pdf_bytes).hexdigest()}",
        "user_agent": _USER_AGENT,
        "ia_id_bundle": _bundle_identifier(ente, fonte),
        "provenance_wayback": {
            "fetched_from": fetched_from,
            "wayback_url": wayback_url,
            "wayback_blocked_robots": wayback_blocked_robots,
        },
    }


def _get_git_sha() -> Optional[str]:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None


def build_dataset_meta(
    parquet_path: Path,
    ente: str,
    version: int,
    row_count: Optional[int] = None,
    git_sha: Optional[str] = None,
) -> Dict[str, Any]:
    """Constrói dataset_meta.json para IA dataset item (SCHEMA.md §3.3).

    KV footer no Parquet (PyArrow) é deferido para M5; por agora o metadata
    vai num sidecar JSON no mesmo IA item.
    """
    parquet_bytes = parquet_path.read_bytes()
    if row_count is None:
        import duckdb
        conn = duckdb.connect()
        try:
            row_count = conn.execute(
                "SELECT count(*) FROM read_parquet(?)", [str(parquet_path)]
            ).fetchone()[0]  # type: ignore[index]
        finally:
            conn.close()
    effective_git_sha = git_sha if git_sha is not None else _get_git_sha()
    meta: Dict[str, Any] = {
        "leizilla_meta_version": "0.1",
        "schema_version": "0.1",
        "ente": ente,
        "version": version,
        "table": "versoes",
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "row_count": row_count,
        "file_size_bytes": parquet_path.stat().st_size,
        "hash_parquet": f"sha256:{hashlib.sha256(parquet_bytes).hexdigest()}",
    }
    if effective_git_sha:
        meta["git_sha"] = effective_git_sha
    return meta


class InternetArchivePublisher:
    """Upload para IA e geração de datasets Parquet."""

    def __init__(self) -> None:
        self.access_key = config.IA_ACCESS_KEY
        self.secret_key = config.IA_SECRET_KEY

    def upload_raw(
        self,
        pdf_path: Path,
        lei_data: Dict[str, Any],
        pdf_bytes: bytes,
        fetched_from: str = "source-fallback",
        wayback_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload raw PDF + raw_meta.json sidecar para IA.

        Identifier: leizilla-raw-{ente}-{fonte}-{chave} (SCHEMA.md §1.2).
        Retorna dict com 'success', 'ia_id', 'ia_url'.
        """
        if not self.access_key or not self.secret_key:
            return {"success": False, "error": "IA credentials not configured"}

        ente = str(lei_data.get("ente", "unknown"))
        fonte = str(lei_data.get("fonte", "casacivil"))
        chave = str(lei_data.get("chave") or lei_data.get("id", "unknown"))
        ia_id = _raw_identifier(ente, fonte, chave)

        raw_meta = build_raw_meta(lei_data, pdf_bytes, fetched_from, wayback_url)

        with tempfile.TemporaryDirectory() as tmp:
            # Rename PDF to {ia_id}.pdf so IA OCR output is {ia_id}_djvu.txt,
            # matching the URL template used by parser.fetch_ocr().
            pdf_dst = Path(tmp) / f"{ia_id}.pdf"
            shutil.copy2(str(pdf_path), str(pdf_dst))
            meta_path = Path(tmp) / "raw_meta.json"
            meta_path.write_text(json.dumps(raw_meta, indent=2, ensure_ascii=False))

            try:
                subprocess.run(
                    [
                        "ia", "upload", ia_id,
                        str(pdf_dst), str(meta_path),
                        "--metadata", f"title:{lei_data.get('titulo', 'Lei')}",
                        "--metadata", "mediatype:texts",
                        "--metadata", f"subject:leis;leizilla;{ente}",
                        "--metadata", f"creator:leizilla-crawler",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return {
                    "success": True,
                    "ia_id": ia_id,
                    "ia_url": f"https://archive.org/details/{ia_id}",
                }
            except subprocess.CalledProcessError as e:
                return {"success": False, "error": e.stderr, "ia_id": ia_id}

    def upload_parsed(
        self,
        ia_id_parsed: str,
        xml_content: str,
        parsed_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Upload law.xml + parsed_meta.json para IA parsed item.

        Identifier: leizilla-{ente}-{tipo}-{numero:05d}-{ano} (SCHEMA.md §1.3).
        Retorna dict com 'success', 'ia_id', 'ia_url'.
        """
        if not self.access_key or not self.secret_key:
            return {"success": False, "error": "IA credentials not configured"}

        ente = str(parsed_meta.get("ente", "unknown"))
        tipo = str(parsed_meta.get("tipo", "lei"))
        titulo = f"Leizilla parsed {ia_id_parsed}"

        with tempfile.TemporaryDirectory() as tmp:
            xml_path = Path(tmp) / "law.xml"
            xml_path.write_text(xml_content, encoding="utf-8")
            meta_path = Path(tmp) / "parsed_meta.json"
            meta_path.write_text(
                json.dumps(parsed_meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            try:
                subprocess.run(
                    [
                        "ia", "upload", ia_id_parsed,
                        str(xml_path), str(meta_path),
                        "--metadata", f"title:{titulo}",
                        "--metadata", "mediatype:texts",
                        "--metadata", f"subject:leis;leizilla;{ente};{tipo}",
                        "--metadata", "creator:leizilla-parser",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return {
                    "success": True,
                    "ia_id": ia_id_parsed,
                    "ia_url": f"https://archive.org/details/{ia_id_parsed}",
                }
            except subprocess.CalledProcessError as e:
                return {"success": False, "error": e.stderr, "ia_id": ia_id_parsed}

    def upload_dataset(
        self,
        parquet_path: Path,
        ente: str,
        version: int = 0,
        row_count: Optional[int] = None,
        git_sha: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload versoes.parquet + dataset_meta.json para IA.

        Identifier: leizilla-dataset-{ente}-v{version} (SCHEMA.md §1.4, §3.5).
        row_count e git_sha são opcionais — caller passa se já os computou.
        """
        if not self.access_key or not self.secret_key:
            return {"success": False, "error": "IA credentials not configured"}

        ia_id = f"leizilla-dataset-{ente}-v{version}"
        dataset_meta = build_dataset_meta(parquet_path, ente, version, row_count, git_sha)
        effective_row_count = dataset_meta["row_count"]

        with tempfile.TemporaryDirectory() as tmp:
            parquet_dst = Path(tmp) / "versoes.parquet"
            shutil.copy2(str(parquet_path), str(parquet_dst))
            meta_path = Path(tmp) / "dataset_meta.json"
            meta_path.write_text(
                json.dumps(dataset_meta, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            try:
                subprocess.run(
                    [
                        "ia", "upload", ia_id,
                        str(parquet_dst), str(meta_path),
                        "--metadata", f"title:Leizilla Dataset {ente.upper()} v{version}",
                        "--metadata", "mediatype:data",
                        "--metadata", f"subject:leis;leizilla;{ente};parquet;versoes",
                        "--metadata", "creator:leizilla-etl",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return {
                    "success": True,
                    "ia_id": ia_id,
                    "ia_url": f"https://archive.org/details/{ia_id}",
                    "row_count": effective_row_count,
                }
            except subprocess.CalledProcessError as e:
                return {"success": False, "error": e.stderr, "ia_id": ia_id}

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
