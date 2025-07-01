"""
Módulo de publicação para Internet Archive.

Gerencia upload de PDFs para IA e exportação de datasets.
"""

import subprocess
import json
from pathlib import Path
from typing import Dict, Any, Optional  # List e tempfile removidos
from datetime import datetime

# import tempfile # Removido
import hashlib

import config
import storage

try:
    import internetarchive
except ImportError:
    internetarchive = None  # Para lidar com a ausência opcional da biblioteca


class InternetArchivePublisher:
    """Gerenciador de publicação no Internet Archive."""

    def __init__(self):
        self.access_key = config.IA_ACCESS_KEY
        self.secret_key = config.IA_SECRET_KEY

        if not self.access_key or not self.secret_key:
            # Permitir inicialização para outros métodos que não usam upload, como export
            print(
                "⚠️  IA_ACCESS_KEY ou IA_SECRET_KEY não configurados. Uploads para o IA serão desabilitados."
            )
            # raise ValueError("IA_ACCESS_KEY e IA_SECRET_KEY são obrigatórias para upload")

        if internetarchive is None:
            print(
                "⚠️  Biblioteca 'internetarchive' não instalada. Funcionalidades de metadados do IA podem ser limitadas."
            )
            print("   Para instalar: uv pip install internetarchive")

    def get_ia_item_metadata(self, identifier: str) -> Optional[Dict[str, Any]]:
        """Busca metadados de um item no Internet Archive."""
        if internetarchive is None:
            print(
                "❌ get_ia_item_metadata: Biblioteca 'internetarchive' não disponível."
            )
            return None
        try:
            # Configurar sessão com credenciais se necessário para acesso a metadados
            # Embora para metadados públicos geralmente não seja estritamente necessário,
            # pode ajudar com rate limits ou acesso a itens restritos (não é o caso aqui).
            # session = internetarchive.get_session(config={'s3': {'access': self.access_key, 'secret': self.secret_key}})
            # item = internetarchive.get_item(identifier, session=session)

            # Para metadados públicos, geralmente não precisa de sessão autenticada.
            item = internetarchive.get_item(identifier)

            if item and item.metadata:
                # O objeto item.files já contém informações detalhadas sobre cada arquivo.
                # Precisamos converter para um formato que inclua 'files' como o CLI `ia metadata --json` faz.

                files_metadata = []
                if item.files:
                    for f_entry in item.files:
                        # f_entry é um dict com chaves como 'name', 'source', 'format', 'md5', etc.
                        files_metadata.append(f_entry)

                # Montar um dicionário similar ao que `ia metadata <id> --json` retornaria
                # O objeto item já tem um atributo `metadata` que é o principal.
                # E `item.files` para a lista de arquivos.
                # `item.reviews` para reviews, etc.
                # A estrutura exata pode variar, mas `item.metadata` e `item.files` são chave.

                # Para simular a estrutura que esperamos (com 'files' dentro do dict principal):
                full_metadata = dict(item.metadata)  # Copia os metadados principais
                full_metadata["files"] = files_metadata
                full_metadata["identifier"] = (
                    item.identifier
                )  # Garante que o identificador está presente
                # Adicionar outros campos de alto nível do objeto Item se necessário
                # full_metadata['item_size'] = item.item_size
                # full_metadata['dir'] = item.dir

                return full_metadata
            else:
                print(f"⚠️  Metadados não encontrados para o item IA: {identifier}")
                return None
        except Exception as e:
            print(f"❌ Erro ao buscar metadados do IA para {identifier}: {e}")
            return None

    def upload_pdf(
        self, pdf_path: Path, lei_metadata: Dict[str, Any], collection: str = "leizilla"
    ) -> Dict[str, Any]:
        """
        Upload de PDF para Internet Archive.

        Args:
            pdf_path: Caminho para o arquivo PDF
            lei_metadata: Metadados da lei
            collection: Coleção no IA

        Returns:
            Metadados do upload incluindo URLs do IA
        """
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF não encontrado: {pdf_path}")

        # Gerar identificador único para o IA
        identifier = self._generate_ia_identifier(lei_metadata)

        # Preparar metadados para o IA
        ia_metadata = self._prepare_ia_metadata(lei_metadata, collection)

        try:
            # Executar upload via ia command
            upload_cli_result = self._execute_ia_upload(
                pdf_path, identifier, ia_metadata
            )

            if upload_cli_result["success"]:
                print(
                    f"✅ Upload CLI para IA bem-sucedido: {identifier}. Buscando metadados adicionais..."
                )

                # URLs básicas
                base_url = f"https://archive.org/details/{identifier}"
                # O nome do arquivo no IA pode ser sanitizado, então é melhor pegar dos metadados do item.
                # pdf_url_on_ia = f"https://archive.org/download/{identifier}/{pdf_path.name}" # Pode não ser confiável

                # Tentar obter metadados do item para links de torrent e nome de arquivo real
                ia_item_metadata_dict = self.get_ia_item_metadata(identifier)

                actual_pdf_filename_in_ia = pdf_path.name  # Fallback
                torrent_url = None
                magnet_link = None  # Placeholder para magnet link

                if ia_item_metadata_dict:
                    # Encontrar o nome do arquivo PDF no IA (pode ter sido sanitizado)
                    for f_info in ia_item_metadata_dict.get("files", []):
                        if (
                            f_info.get("name", "").lower() == pdf_path.name.lower()
                        ):  # Compara insensível a maiúsculas/minúsculas
                            actual_pdf_filename_in_ia = f_info.get("name")
                            break
                        # Fallback para o primeiro PDF encontrado se o nome exato não bater (ex: sanitização)
                        elif (
                            f_info.get("format") == "Portable Document Format"
                            and not actual_pdf_filename_in_ia
                        ):
                            actual_pdf_filename_in_ia = f_info.get("name")

                    # Encontrar o torrent principal
                    for f_info in ia_item_metadata_dict.get("files", []):
                        if f_info.get("format") == "Archive BitTorrent":
                            # O torrent principal geralmente NÃO inclui o nome do arquivo original,
                            # mas sim o identificador do item. Ex: "identifier_archive.torrent"
                            # Ou pode ser o nome do arquivo original com _archive.torrent
                            # Vamos procurar por um que contenha "_archive.torrent"
                            fname = f_info.get("name", "")
                            if fname.endswith("_archive.torrent"):  # Heurística comum
                                torrent_url = (
                                    f"https://archive.org/download/{identifier}/{fname}"
                                )
                                # Tentar extrair infohash para magnet link (simplificado)
                                # Magnet = magnet:?xt=urn:btih:{infohash}&dn={nome_do_item}
                                # O infohash está no arquivo .torrent ou às vezes nos metadados do arquivo.
                                # A biblioteca `internetarchive` não expõe o infohash facilmente.
                                # Para uma solução robusta, precisaríamos de um parser de torrent.
                                # Por enquanto, vamos deixar o magnet_link como None ou construir um parcial se possível.
                                if f_info.get(
                                    "btih"
                                ):  # Check se 'btih' (BitTorrent Info Hash) está nos metadados do arquivo
                                    magnet_link = f"magnet:?xt=urn:btih:{f_info['btih']}&dn={identifier}"
                                break  # Pega o primeiro encontrado

                pdf_url_on_ia = f"https://archive.org/download/{identifier}/{actual_pdf_filename_in_ia}"

                upload_result = {
                    "identifier": identifier,
                    "ia_item_id": identifier,  # Alias para consistência com outros campos
                    "ia_detail_url": base_url,
                    "url": pdf_url_on_ia,  # Campo 'url' para compatibilidade com o que o DB espera para url_pdf_ia
                    "ia_pdf_url": pdf_url_on_ia,  # Mais explícito
                    "ia_ocr_url": f"https://archive.org/download/{identifier}/{Path(actual_pdf_filename_in_ia).stem}_djvu.txt",
                    "ia_torrent_url": torrent_url,
                    "ia_magnet_link": magnet_link,
                    "upload_timestamp": datetime.now().isoformat(),
                    "success": True,
                }

                print(
                    f"✅ Metadados IA recuperados. PDF URL: {pdf_url_on_ia}, Torrent URL: {torrent_url}"
                )
                return upload_result

            else:
                print(
                    f"❌ Falha no upload CLI para IA: {upload_cli_result.get('error', 'Erro desconhecido')}"
                )
                return {
                    "success": False,
                    "error": upload_cli_result.get("error"),
                }  # Corrigido para upload_cli_result

        except Exception as e:
            print(f"❌ Erro no upload IA: {e}")
            return {"success": False, "error": str(e)}

    def _generate_ia_identifier(self, lei_metadata: Dict[str, Any]) -> str:
        """Gera identificador único para o IA."""
        # Formato: leizilla-{origem}-{tipo}-{ano}-{numero}
        origem = lei_metadata.get("origem", "brasil")
        tipo = lei_metadata.get("tipo_lei", "lei")
        ano = lei_metadata.get("ano", datetime.now().year)
        numero = lei_metadata.get("numero", "unknown")

        # Sanitizar para identificador válido do IA
        identifier = f"leizilla-{origem}-{tipo}-{ano}-{numero}"
        identifier = identifier.lower().replace(" ", "-").replace("_", "-")

        # Garantir que é único adicionando hash se necessário
        if len(identifier) > 80:  # Limite do IA
            content_hash = hashlib.md5(str(lei_metadata).encode()).hexdigest()[:8]
            identifier = f"leizilla-{origem}-{ano}-{content_hash}"

        return identifier

    def _prepare_ia_metadata(
        self, lei_metadata: Dict[str, Any], collection: str
    ) -> Dict[str, str]:
        """Prepara metadados para upload no IA."""
        metadata = {
            "collection": collection,
            "mediatype": "texts",
            "title": lei_metadata.get("titulo", "Lei Brasileira"),
            "creator": "Leizilla Project",
            "subject": f"lei; brasil; {lei_metadata.get('origem', '')}; jurídico",
            "description": f"Lei brasileira indexada pelo projeto Leizilla. "
            f"Origem: {lei_metadata.get('origem', 'N/A')}, "
            f"Ano: {lei_metadata.get('ano', 'N/A')}",
            "date": str(lei_metadata.get("ano", datetime.now().year)),
            "language": "Portuguese",
            "licenseurl": "https://creativecommons.org/publicdomain/mark/1.0/",
            "source": lei_metadata.get("url_original", ""),
            # Metadados específicos do Leizilla
            "leizilla-origem": lei_metadata.get("origem", ""),
            "leizilla-tipo": lei_metadata.get("tipo_lei", ""),
            "leizilla-numero": str(lei_metadata.get("numero", "")),
            "leizilla-ano": str(lei_metadata.get("ano", "")),
            "leizilla-version": "1.0",
        }

        # Adicionar metadados extras se existirem
        if "metadados" in lei_metadata and isinstance(lei_metadata["metadados"], dict):
            for key, value in lei_metadata["metadados"].items():
                if isinstance(value, (str, int, float)):
                    metadata[f"leizilla-{key}"] = str(value)

        return metadata

    def _execute_ia_upload(
        self, pdf_path: Path, identifier: str, metadata: Dict[str, str]
    ) -> Dict[str, Any]:
        """Executa upload via comando ia."""

        # Preparar comando ia
        cmd = [
            "ia",
            "upload",
            identifier,
            str(pdf_path),
            "--checksum",  # Verificar integridade
        ]

        # Adicionar metadados
        for key, value in metadata.items():
            cmd.extend(["--metadata", f"{key}:{value}"])

        # Configurar ambiente com credenciais
        env = {"IA_ACCESS_KEY": self.access_key, "IA_SECRET_KEY": self.secret_key}

        try:
            # Executar comando
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutos timeout
            )

            if result.returncode == 0:
                return {"success": True, "output": result.stdout}
            else:
                return {
                    "success": False,
                    "error": result.stderr or result.stdout,
                    "returncode": result.returncode,
                }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Upload timeout (5 minutos)"}
        except FileNotFoundError:
            return {
                "success": False,
                "error": 'Comando "ia" não encontrado. Instale: pip install internetarchive',
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def export_dataset_parquet(
        self, origem: str, output_dir: Path, ano: Optional[int] = None
    ) -> Path:
        """
        Exporta dataset de leis para Parquet.

        Args:
            origem: Origem das leis (ex: 'rondonia')
            output_dir: Diretório de saída
            ano: Ano específico (opcional)

        Returns:
            Caminho do arquivo Parquet gerado
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Nome do arquivo
        if ano:
            filename = f"leis_{origem}_{ano}.parquet"
        else:
            filename = f"leis_{origem}_completo.parquet"

        output_path = output_dir / filename

        # Exportar via DuckDB
        storage.storage.export_parquet(output_path, origem=origem, ano=ano)

        print(f"✅ Dataset exportado: {output_path}")
        return output_path

    def upload_dataset(
        self, parquet_path: Path, origem: str, ano: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Upload de dataset para Internet Archive.

        Args:
            parquet_path: Caminho do arquivo Parquet
            origem: Origem das leis
            ano: Ano específico (opcional)

        Returns:
            Resultado do upload
        """
        # Metadados do dataset
        dataset_metadata = {
            "titulo": f"Dataset de Leis - {origem.title()}"
            + (f" ({ano})" if ano else ""),
            "origem": origem,
            "tipo_lei": "dataset",
            "ano": ano or datetime.now().year,
            "numero": "dataset",
            "metadados": {
                "tipo": "dataset_parquet",
                "formato": "parquet",
                "origem_dados": origem,
                "ano_dados": ano,
                "gerado_em": datetime.now().isoformat(),
                "versao_leizilla": "1.0",
            },
        }

        return self.upload_pdf(
            parquet_path, dataset_metadata, collection="leizilla-datasets"
        )

    def generate_dataset_manifest(
        self, origem: str, output_dir: Path, ano: Optional[int] = None
    ) -> Path:
        """
        Gera um manifest.json para um dataset específico, buscando os metadados
        mais recentes do banco de dados para popular os links de torrent/magnet.
        A URL do Parquet é construída de forma preditiva.
        """
        # Correção: Usar a instância global 'storage' diretamente, não DatabaseManager
        # db = storage.DatabaseManager() # Incorreto
        db = storage.storage  # Correto, usando a instância global de DuckDBStorage

        # Define o ID e o nome do arquivo do dataset
        if ano:
            dataset_id = f"leis_{origem}_{ano}"
            # Para o IA, o identificador do item do dataset pode ser diferente do nome do arquivo Parquet.
            # Vamos assumir que o item no IA para o dataset Parquet é nomeado consistentemente.
            # Ex: leizilla-dataset-rondonia-2023
            ia_dataset_identifier = f"leizilla-dataset-{origem}-{ano}"
        else:
            dataset_id = f"leis_{origem}_completo"
            ia_dataset_identifier = f"leizilla-dataset-{origem}-completo"

        # O nome do arquivo Parquet dentro do item do IA.
        # Assumindo que o nome do arquivo Parquet no IA é o mesmo que dataset_id + .parquet
        parquet_file_on_ia = f"{dataset_id}.parquet"
        manifest_path = output_dir / f"{dataset_id}.manifest.json"

        # Busca a lei mais recente do dataset que tenha sido publicada no IA
        # para usar como representante dos links do dataset.
        # Esta é uma simplificação: o ideal seria que o próprio dataset no IA tivesse seu .torrent.
        # Se o dataset em si (o arquivo parquet) é um item no IA, ele terá seu próprio torrent.
        # Por agora, estamos usando o torrent de UMA lei como proxy.
        # Vamos refinar isso: o ideal é obter o torrent do PRÓPRIO DATASET se ele for upado para o IA.
        # A URL do Parquet será a URL direta para o arquivo Parquet no IA.

        # Tentativa de obter metadados do item do *dataset* no IA
        dataset_item_metadata = self.get_ia_item_metadata(ia_dataset_identifier)

        dataset_torrent_url = None
        dataset_magnet_link = None

        if dataset_item_metadata:
            for f_info in dataset_item_metadata.get("files", []):
                if f_info.get("name", "").endswith("_archive.torrent"):
                    dataset_torrent_url = f"https://archive.org/download/{ia_dataset_identifier}/{f_info['name']}"
                    if f_info.get("btih"):
                        dataset_magnet_link = f"magnet:?xt=urn:btih:{f_info['btih']}&dn={ia_dataset_identifier}"
                    break
        else:
            # Fallback: Se não acharmos metadados do item do dataset (ex: não foi upado ainda ou identificador errado),
            # usar a lei mais recente como proxy, conforme o plano original.
            print(
                f"⚠️  Metadados do item do dataset '{ia_dataset_identifier}' não encontrados no IA. Tentando fallback para última lei publicada."
            )
            latest_published_law = db.get_latest_published_law(origem=origem, ano=ano)
            if latest_published_law:
                dataset_torrent_url = latest_published_law.get("url_torrent_ia")
                dataset_magnet_link = latest_published_law.get("magnet_link_ia")
                print(
                    f"ℹ️  Usando torrent/magnet da lei '{latest_published_law.get('id')}' como proxy para o dataset '{dataset_id}'."
                )

        manifest_data = {
            "dataset_id": dataset_id,
            "generated_at": datetime.now().isoformat(),
            "origem": origem,
            "ano": ano,  # Pode ser None
            "files": {
                # URL Preditiva para o Parquet no item do dataset no IA
                "parquet": f"https://archive.org/download/{ia_dataset_identifier}/{parquet_file_on_ia}",
                "torrent": dataset_torrent_url,  # URL do .torrent do *item do dataset* no IA
                "magnet": dataset_magnet_link,  # Magnet link do *item do dataset* no IA
            },
            "comment": "O torrent e magnet link referem-se ao item completo do dataset no Internet Archive, que contém o arquivo Parquet.",
        }

        manifest_path.parent.mkdir(
            parents=True, exist_ok=True
        )  # Garante que o diretório de saída existe
        manifest_path.write_text(
            json.dumps(manifest_data, indent=2, ensure_ascii=False)
        )
        print(f"✅ Manifesto do dataset gerado: {manifest_path}")
        return manifest_path


def upload_lei_to_ia(pdf_path: Path, lei_metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Função utilitária para upload de lei para IA.

    Args:
        pdf_path: Caminho do PDF
        lei_metadata: Metadados da lei

    Returns:
        Resultado do upload
    """
    publisher = InternetArchivePublisher()
    return publisher.upload_pdf(pdf_path, lei_metadata)


def export_and_upload_dataset(origem: str, ano: Optional[int] = None) -> Dict[str, Any]:
    """
    Função utilitária para exportar e fazer upload de dataset.

    Args:
        origem: Origem das leis
        ano: Ano específico (opcional)

    Returns:
        Resultado do processo
    """
    publisher = InternetArchivePublisher()

    # Exportar dataset
    export_dir = config.DATA_DIR / "exports"
    parquet_path = publisher.export_dataset_parquet(origem, export_dir, ano)

    # Upload para IA
    upload_result = publisher.upload_dataset(parquet_path, origem, ano)

    return {"export_path": str(parquet_path), "upload_result": upload_result}
