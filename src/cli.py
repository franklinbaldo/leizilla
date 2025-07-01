#!/usr/bin/env python3
"""
Leizilla CLI - Interface de linha de comando para o sistema de indexação de leis.
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional, Dict, List, Any  # Type e tempfile removidos
import importlib
import inspect
from datetime import datetime

# import tempfile # Removido
import json  # Adicionado para o torrent_get e manifest.json


import typer
from typer import echo, style

# Adicionando o diretório src ao sys.path para importações de módulos locais
# Isso é importante para que `from connectors.base import BaseConnector` funcione
# ao carregar conectores dinamicamente.
# E também para outros módulos como `storage` e `publisher`.
# __file__ é o path de cli.py, .parent é src/, .parent.parent é a raiz do projeto.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # src/

# Importações de módulos do projeto Leizilla
# Estes agora devem funcionar devido às manipulações de sys.path acima
try:
    from connectors.base import BaseConnector
    from storage import storage as db_storage_instance
    from publisher import InternetArchivePublisher
    import config
    from logging_utils import StructuredLogger  # Adicionado
except ImportError as e:
    print(
        f"Erro crítico: Não foi possível importar módulos essenciais do Leizilla: {e}"
    )
    print(
        "Verifique se o PYTHONPATH está configurado corretamente ou se você está executando o CLI a partir do diretório raiz do projeto."
    )
    sys.exit(1)


# Configure app
app = typer.Typer(
    name="leizilla",
    help="🦖 O dinossauro que devora PDFs jurídicos e cospe dados abertos",
    add_completion=False,
    pretty_exceptions_show_locals=False,  # Para não mostrar variáveis locais em tracebacks do Typer
)

# Create subcommands
dev_app = typer.Typer(name="dev", help="🛠️ Comandos de desenvolvimento")
app.add_typer(dev_app, name="dev")

# --- Gerenciamento de Conectores ---
_LOADED_CONNECTORS: Dict[str, BaseConnector] = {}
_CONNECTORS_PATH = Path(__file__).resolve().parent / "connectors"


def load_connectors(force_reload: bool = False):
    """Carrega dinamicamente todos os conectores da pasta src/connectors."""
    if _LOADED_CONNECTORS and not force_reload:
        return

    if force_reload:
        _LOADED_CONNECTORS.clear()

    if not _CONNECTORS_PATH.is_dir():
        echo(
            style(
                f"⚠️  Diretório de conectores não encontrado em {_CONNECTORS_PATH}",
                fg=typer.colors.YELLOW,
            )
        )
        return

    echo(f"🔍 Carregando conectores de: {_CONNECTORS_PATH}")
    for f_path in _CONNECTORS_PATH.glob("*.py"):
        if f_path.name.startswith("_") or f_path.name == "base.py":
            continue

        module_name = f"connectors.{f_path.stem}"
        try:
            module = importlib.import_module(module_name)
            importlib.reload(
                module
            )  # Para garantir que mudanças sejam pegas durante desenvolvimento

            for name, obj_type in inspect.getmembers(module, inspect.isclass):
                if (
                    issubclass(obj_type, BaseConnector)
                    and obj_type is not BaseConnector
                ):
                    try:
                        # Verifica se o construtor espera argumentos (além de self)
                        sig = inspect.signature(obj_type.__init__)
                        num_params = len(sig.parameters) - 1  # -1 para self
                        if num_params > 0:
                            echo(
                                style(
                                    f"⚠️ Conector {name} em {f_path.name} tem {num_params} parâmetros no construtor. Conectores devem ser instanciáveis sem argumentos.",
                                    fg=typer.colors.YELLOW,
                                )
                            )
                            continue

                        connector_instance = obj_type()
                        if (
                            not hasattr(connector_instance, "ORIGEM")
                            or connector_instance.ORIGEM == "base_connector"
                        ):
                            echo(
                                style(
                                    f"⚠️  Conector {name} em {f_path.name} não definiu um atributo 'ORIGEM' válido. Pulando.",
                                    fg=typer.colors.YELLOW,
                                )
                            )
                            continue
                        if connector_instance.ORIGEM in _LOADED_CONNECTORS:
                            echo(
                                style(
                                    f"⚠️  Conector duplicado para ORIGEM '{connector_instance.ORIGEM}'. Usando o primeiro carregado: {_LOADED_CONNECTORS[connector_instance.ORIGEM].__class__.__name__}",
                                    fg=typer.colors.YELLOW,
                                )
                            )
                            continue

                        _LOADED_CONNECTORS[connector_instance.ORIGEM] = (
                            connector_instance
                        )
                        echo(
                            style(
                                f"🔌 Conector '{connector_instance.ORIGEM}' ({name}) carregado com sucesso.",
                                fg=typer.colors.GREEN,
                            )
                        )
                    except Exception as e:
                        echo(
                            style(
                                f"❌ Erro ao instanciar conector {name} de {f_path.name}: {e}",
                                fg=typer.colors.RED,
                            )
                        )
        except ImportError as e:
            echo(
                style(
                    f"❌ Erro ao importar o módulo conector {module_name}: {e}",
                    fg=typer.colors.RED,
                )
            )
        except Exception as e:
            echo(
                style(
                    f"❌ Erro desconhecido ao carregar {module_name}: {e}",
                    fg=typer.colors.RED,
                )
            )


def get_connector(origem: str) -> Optional[BaseConnector]:
    """Retorna uma instância de conector para a origem especificada."""
    if not _LOADED_CONNECTORS:
        load_connectors()

    connector = _LOADED_CONNECTORS.get(origem)
    if not connector:
        echo(
            style(
                f"❌ Conector para origem '{origem}' não encontrado ou não carregado.",
                fg=typer.colors.RED,
            )
        )
        echo(f"Conectores disponíveis: {list(_LOADED_CONNECTORS.keys())}")
    return connector


async def close_all_connectors():
    """Fecha todos os conectores carregados que possuem o método close."""
    closed_any = False
    for origem, connector in list(
        _LOADED_CONNECTORS.items()
    ):  # Usar list para permitir modificação no dict
        if hasattr(connector, "close") and inspect.iscoroutinefunction(connector.close):
            try:
                echo(f"⏳ Fechando conector '{origem}'...")
                await connector.close()
                echo(
                    style(
                        f"🔌 Conector '{origem}' fechado.", fg=typer.colors.BRIGHT_BLACK
                    )
                )
                closed_any = True
            except Exception as e:
                echo(
                    style(
                        f"⚠️ Erro ao fechar conector '{origem}': {e}",
                        fg=typer.colors.YELLOW,
                    )
                )
        # Remover o conector do dicionário após fechar para permitir recarregamento limpo se necessário
        # del _LOADED_CONNECTORS[origem]
    if closed_any:
        echo("🧹 Limpeza de conectores concluída.")
    _LOADED_CONNECTORS.clear()  # Limpa todos após tentativas de fechamento


# Hook para carregar conectores na inicialização do CLI e fechar na saída
@app.callback()
def main_callback(ctx: typer.Context):
    """
    Callback principal do Typer. Carrega conectores antes de qualquer comando.
    """
    if (
        ctx.invoked_subcommand == "connector" or ctx.invoked_subcommand == "torrent"
    ):  # Não carregar para subcomandos de connector ou torrent
        return
    load_connectors()


# --- Comandos Principais Atualizados ---


@app.command("discover")
def cmd_discover(
    ctx: typer.Context,
    origem: str = typer.Option(
        ...,
        help="Origem das leis (ex: rondonia). Use 'leizilla connector list' para ver as disponíveis.",
    ),
    # Parâmetros específicos do conector como start_coddoc serão passados como kwargs
    # O usuário precisará saber quais parâmetros seu conector alvo aceita.
    # Poderíamos ter uma forma de listar params de um conector específico no futuro.
    extra_params: Optional[List[str]] = typer.Option(
        None,
        "--extra-params",
        "-p",
        help="Parâmetros extras para o conector no formato key=value. Ex: -p start_coddoc=100 -p end_coddoc=200",
    ),
):
    """🔍 Descobrir leis nos portais oficiais usando conectores."""
    logger = StructuredLogger(command_name="discover")
    logger.info(
        f"Iniciando descoberta para origem: {origem}",
        origem=origem,
        extra_params=extra_params,
    )
    echo(style(f"🔍 Descobrindo leis de '{origem}'...", bold=True))

    connector = get_connector(origem)
    if not connector:
        raise typer.Exit(1)

    db = db_storage_instance  # Alterado para usar a instância global

    discover_kwargs: Dict[str, Any] = {}
    if extra_params:
        for param in extra_params:
            if "=" not in param:
                echo(
                    style(
                        f"⚠️ Parâmetro extra '{param}' ignorado. Use o formato key=value.",
                        fg=typer.colors.YELLOW,
                    )
                )
                continue
            key, value = param.split("=", 1)
            # Tentar converter para int ou float se aplicável
            if value.isdigit():
                discover_kwargs[key] = int(value)
            else:
                try:
                    discover_kwargs[key] = float(value)
                except ValueError:
                    discover_kwargs[key] = value
        echo(f"⚙️  Parâmetros extras para o conector: {discover_kwargs}")

    async def run_discover():
        nonlocal connector  # Para permitir reatribuição em caso de __aenter__
        processed_laws_count = 0
        saved_laws_count = 0
        try:
            sig = inspect.signature(connector.discover_laws)
            valid_kwargs = {
                k: v for k, v in discover_kwargs.items() if k in sig.parameters
            }
            invalid_kwargs = {
                k: v for k, v in discover_kwargs.items() if k not in sig.parameters
            }
            if invalid_kwargs:
                echo(
                    style(
                        f"⚠️ Parâmetros extras ignorados (não aceitos por {origem}.discover_laws): {invalid_kwargs}",
                        fg=typer.colors.YELLOW,
                    )
                )

            laws_metadata: Optional[List[Dict[str, Any]]] = None
            if hasattr(connector, "__aenter__") and hasattr(connector, "__aexit__"):
                echo(f"ℹ️  Usando context manager para o conector '{origem}'")
                async with connector as conn_instance:  # type: ignore
                    laws_metadata = await conn_instance.discover_laws(**valid_kwargs)
            else:
                laws_metadata = await connector.discover_laws(**valid_kwargs)

            if laws_metadata is None:
                echo(
                    style(
                        f"⚠️  Conector '{origem}' não retornou nenhuma lista de leis (retornou None). Verifique os logs do conector.",
                        fg=typer.colors.YELLOW,
                    )
                )
                return

            processed_laws_count = len(laws_metadata)
            if not laws_metadata:
                echo(
                    style(
                        f"✅ Nenhuma nova lei descoberta por '{origem}'.",
                        fg=typer.colors.GREEN,
                    )
                )
                return

            for law_meta in laws_metadata:
                if not isinstance(law_meta, dict):
                    echo(
                        style(
                            f"⚠️  Item inválido retornado pelo conector '{origem}': não é um dicionário. Pulando. Item: {law_meta}",
                            fg=typer.colors.YELLOW,
                        )
                    )
                    continue

                required_keys = ["id", "origem", "titulo"]
                if not all(key in law_meta for key in required_keys):
                    echo(
                        style(
                            f"⚠️  Metadados da lei incompletos retornados por '{origem}': Faltando chaves {required_keys}. Pulando. Metadados: {law_meta.get('id', 'ID ausente')}",
                            fg=typer.colors.YELLOW,
                        )
                    )
                    continue

                law_meta["descoberto_em_cli"] = datetime.now().isoformat()
                law_meta["status_geral"] = "descoberto"  # Novo status

                # Garantir que a origem no metadado é a mesma do conector
                if law_meta.get("origem") != origem:
                    echo(
                        style(
                            f"⚠️  Origem nos metadados ('{law_meta.get('origem')}') difere da origem do conector ('{origem}'). Corrigindo para '{origem}'. ID: {law_meta['id']}",
                            fg=typer.colors.YELLOW,
                        )
                    )
                    law_meta["origem"] = origem

                db.insert_lei(law_meta)
                # log_msg = f"Metadados da lei salvos no DB: ID {law_meta.get('id')}" # Removido F841
                # logger.log("law_metadata_saved", message=log_msg, law_id=law_meta.get('id'), title=law_meta.get('titulo'))
                echo(
                    f"💾 Salvo no DB: {law_meta.get('id')} - {law_meta.get('titulo', 'N/A')[:50]}..."
                )
                saved_laws_count += 1

            final_message = f"Descobertas {processed_laws_count} leis, {saved_laws_count} salvas/atualizadas de '{origem}'."
            echo(style(f"🎉 {final_message}", fg=typer.colors.GREEN, bold=True))
            logger.info(
                final_message,
                origem=origem,
                processed_count=processed_laws_count,
                saved_count=saved_laws_count,
                status="success",
            )

        except NotImplementedError:
            error_msg = (
                f"Método 'discover_laws' não implementado para o conector '{origem}'."
            )
            echo(style(f"❌ {error_msg}", fg=typer.colors.RED))
            logger.error(error_msg, origem=origem, status="failure")
            raise typer.Exit(code=1)
        except Exception as e:
            error_msg = (
                f"Erro crítico durante a descoberta com o conector '{origem}': {e}"
            )
            echo(style(f"❌ {error_msg}", fg=typer.colors.RED))
            logger.critical(
                error_msg, origem=origem, error_details=str(e), status="failure"
            )
            import traceback

            traceback.print_exc()
            raise typer.Exit(code=1)

    try:
        asyncio.run(run_discover())
    except Exception:
        # O erro já foi logado, apenas sair.
        raise typer.Exit(code=1)
    # Não fechar conectores aqui, pois o @app.result_callback fará isso.


@app.command("download")
def cmd_download(
    ctx: typer.Context,
    origem: str = typer.Option(..., help="Origem das leis (ex: rondonia)."),
    limit: int = typer.Option(10, help="Limite de downloads de PDFs pendentes."),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Sobrescrever PDFs existentes localmente."
    ),
):
    """📥 Baixar PDFs das leis descobertas usando conectores."""
    logger = StructuredLogger(command_name="download")
    logger.info(
        f"Iniciando download de PDFs para origem: {origem}",
        origem=origem,
        limit=limit,
        overwrite=overwrite,
    )
    echo(style(f"📥 Baixando até {limit} PDFs pendentes de '{origem}'...", bold=True))

    connector = get_connector(origem)
    if not connector:
        raise typer.Exit(1)

    if not hasattr(connector, "download_pdf"):
        echo(
            style(
                f"❌ O conector '{origem}' não implementa a função 'download_pdf'.",
                fg=typer.colors.RED,
            )
        )
        raise typer.Exit(1)

    db = db_storage_instance  # Alterado para usar a instância global

    async def run_download():
        nonlocal connector
        # Buscar leis da origem que têm 'url_pdf_original' mas não 'local_pdf_path' ou 'url_pdf_ia'
        # ou se 'overwrite' for True, tentar baixar novamente mesmo que 'local_pdf_path' exista.
        laws_from_db = db.search_leis_para_download(
            origem=origem, limit=(limit * 5)
        )  # Pega mais para filtrar

        laws_to_process: List[Dict[str, Any]] = []
        for law in laws_from_db:
            if len(laws_to_process) >= limit:
                break
            if not law.get("url_pdf_original"):
                continue  # Não tem de onde baixar

            has_local = bool(
                law.get("local_pdf_path") and Path(str(law["local_pdf_path"])).exists()
            )
            has_ia = bool(law.get("url_pdf_ia"))

            if overwrite:  # Se overwrite, tenta baixar se tiver URL original
                if law.get("url_pdf_original"):
                    laws_to_process.append(law)
            elif not has_local and not has_ia and law.get("url_pdf_original"):
                # Baixar se não tem local nem IA, mas tem URL original
                laws_to_process.append(law)
            elif has_local and not has_ia and law.get("url_pdf_original"):
                # Já tem local mas não IA, poderia ser para upload, não download.
                # Mas se o download anterior falhou e o status indica, tentar de novo.
                # (Lógica de status de download não implementada aqui ainda)
                pass

        if not laws_to_process:
            echo(
                style(
                    f"✅ Nenhuma lei pendente de download encontrada para '{origem}' com os critérios atuais.",
                    fg=typer.colors.GREEN,
                )
            )
            return

        echo(f"ℹ️  Encontradas {len(laws_to_process)} leis para tentar download.")
        downloaded_count = 0

        download_base_path = config.TEMP_DIR / "connector_downloads" / origem
        download_base_path.mkdir(parents=True, exist_ok=True)

        conn_manager = (
            connector
            if (hasattr(connector, "__aenter__") and hasattr(connector, "__aexit__"))
            else None
        )

        if conn_manager:
            echo(
                f"ℹ️  Usando context manager para o conector '{origem}' durante downloads."
            )
            await conn_manager.__aenter__()  # type: ignore

        try:
            for law_metadata_from_db in laws_to_process:
                law_id = law_metadata_from_db.get("id")
                if not law_id:
                    echo(
                        style(
                            "⚠️  Metadados da lei sem ID no DB, pulando.",
                            fg=typer.colors.YELLOW,
                        )
                    )
                    continue

                pdf_filename = f"{law_id.replace(':', '_').replace('/', '_')}.pdf"
                output_file_path = download_base_path / pdf_filename

                if output_file_path.exists() and not overwrite:
                    echo(
                        style(
                            f"⏭️  PDF já existe localmente para {law_id} e overwrite=False. Pulando.",
                            fg=typer.colors.BRIGHT_BLACK,
                        )
                    )
                    # Garantir que o DB está atualizado com este path
                    if str(output_file_path) != law_metadata_from_db.get(
                        "local_pdf_path"
                    ):
                        db.update_lei(
                            law_id,
                            {
                                "local_pdf_path": str(output_file_path),
                                "status_geral": "pdf_local_disponivel",
                            },
                        )
                    continue

                echo(
                    f"⬇️  Tentando baixar PDF para {law_id} de {law_metadata_from_db.get('url_pdf_original')}"
                )
                update_data: Dict[str, Any] = {
                    "ultima_tentativa_download_em": datetime.now().isoformat()
                }

                current_connector_instance = conn_manager if conn_manager else connector

                try:
                    success = await current_connector_instance.download_pdf(
                        law_metadata_from_db, output_file_path
                    )  # type: ignore
                    if success:
                        update_data["local_pdf_path"] = str(output_file_path)
                        update_data["status_geral"] = "pdf_local_disponivel"
                        update_data["status_download"] = "sucesso"
                        db.update_lei(law_id, update_data)
                        downloaded_count += 1
                        echo(
                            style(
                                f"✅ PDF baixado para {law_id} em: {output_file_path}",
                                fg=typer.colors.GREEN,
                            )
                        )
                    else:
                        update_data["status_download"] = "falha_conector"
                        db.update_lei(law_id, update_data)
                        echo(
                            style(
                                f"❌ Falha ao baixar PDF para {law_id} (conector retornou False).",
                                fg=typer.colors.YELLOW,
                            )
                        )
                        logger.warning(
                            "Falha ao baixar PDF (conector indicou falha).",
                            law_id=law_id,
                            origem=origem,
                            pdf_url=law_metadata_from_db.get("url_pdf_original"),
                        )

                except NotImplementedError:
                    error_msg = f"Método 'download_pdf' não implementado para o conector '{origem}'. Impossível continuar."
                    echo(style(f"❌ {error_msg}", fg=typer.colors.RED))
                    logger.error(error_msg, origem=origem, status="failure")
                    if conn_manager:
                        await conn_manager.__aexit__(None, None, None)  # type: ignore
                    raise typer.Exit(code=1)
                except Exception as e:
                    error_msg = f"Erro crítico ao baixar PDF para {law_id} com conector '{origem}': {e}"
                    echo(style(f"❌ {error_msg}", fg=typer.colors.RED))
                    logger.error(
                        error_msg,
                        law_id=law_id,
                        origem=origem,
                        error_details=str(e),
                        status="failure",
                    )
                    update_data["status_download"] = "erro_critico"
                    update_data["erro_download_info"] = str(e)
                    db.update_lei(law_id, update_data)
                    log_event(
                        {
                            **log_event_origem_base,
                            "event_type": "pdf_download_error",
                            "law_id": law_id,
                            "message": "Erro crítico baixando PDF.",
                            "error_details": str(e),
                            "status": "failure",
                        }
                    )  # Removido f-string da mensagem
                    # Não parar todo o lote por causa de um erro, continuar com os próximos.
        finally:
            if conn_manager:
                await conn_manager.__aexit__(None, None, None)  # type: ignore

        final_message = f"Processo de download concluído. {downloaded_count} PDFs baixados/atualizados para '{origem}'."
        echo(style(f"🎉 {final_message}", bold=True))
        logger.info(
            final_message,
            origem=origem,
            downloaded_count=downloaded_count,
            attempted_count=len(laws_to_process),
            status="success"
            if downloaded_count == len(laws_to_process) or not laws_to_process
            else "partial_success",
        )

    try:
        asyncio.run(run_download())
    except Exception as main_e:
        logger.critical(
            f"Erro não tratado na execução de run_download: {main_e}",
            origem=origem,
            error_details=str(main_e),
        )
        raise typer.Exit(code=1)


@app.command("upload")
def cmd_upload(
    ctx: typer.Context,
    origem: Optional[str] = typer.Option(
        None, help="Origem específica para upload. Se não informado, busca em todas."
    ),
    limit: int = typer.Option(5, help="Limite de uploads para o Internet Archive."),
    overwrite_ia: bool = typer.Option(
        False,
        "--overwrite-ia",
        help="Forçar re-upload mesmo que já exista URL do IA (pode criar nova versão no IA).",
    ),
):
    """☁️ Upload PDFs locais para o Internet Archive."""
    logger = StructuredLogger(command_name="upload")
    logger.info(
        "Iniciando upload de PDFs para o Internet Archive.",
        origem_filtro=origem,
        limit=limit,
        overwrite_ia=overwrite_ia,
    )
    echo(
        style(
            f"☁️ Fazendo upload de até {limit} PDFs para o Internet Archive...",
            bold=True,
        )
    )
    if origem:
        echo(f"Filtrando pela origem: {origem}")
    if overwrite_ia:
        echo(
            style(
                "⚠️  Modo overwrite-ia ATIVADO. PDFs podem ser reenviados para o IA.",
                fg=typer.colors.YELLOW,
            )
        )

    db = db_storage_instance  # Alterado para usar a instância global
    publisher = InternetArchivePublisher()  # Supondo que não precisa de setup async

    # Buscar leis que têm 'local_pdf_path' e (não têm 'url_pdf_ia' OU overwrite_ia é True)
    laws_to_upload = db.search_leis_para_upload(
        origem=origem, limit=(limit * 5), com_url_ia=(None if overwrite_ia else False)
    )

    # Filtrar para garantir que o local_pdf_path existe
    valid_laws_to_upload: List[Dict[str, Any]] = []
    for law in laws_to_upload:
        if len(valid_laws_to_upload) >= limit:
            break
        local_path_str = law.get("local_pdf_path")
        if local_path_str:
            local_path = Path(local_path_str)
            if local_path.exists() and local_path.is_file():
                # Se overwrite_ia é False, só adiciona se não tiver url_pdf_ia
                if not overwrite_ia and law.get("url_pdf_ia"):
                    continue
                valid_laws_to_upload.append(law)
            else:
                echo(
                    style(
                        f"⚠️ PDF local não encontrado para {law.get('id')}: {local_path_str}. Pulando.",
                        fg=typer.colors.YELLOW,
                    )
                )
                db.update_lei(
                    law.get("id"),
                    {
                        "status_geral": "erro_pdf_local_ausente",
                        "status_upload": "falha_local_nao_encontrado",
                    },
                )

    if not valid_laws_to_upload:
        echo(
            style(
                "✅ Nenhum PDF pendente de upload encontrado com os critérios atuais.",
                fg=typer.colors.GREEN,
            )
        )
        return

    echo(
        f"ℹ️  Encontradas {len(valid_laws_to_upload)} leis com PDFs locais para upload."
    )
    uploaded_count = 0

    # O publisher.upload_pdf não é async, então podemos iterar diretamente.
    for law_metadata in valid_laws_to_upload:
        law_id = law_metadata.get("id")
        pdf_path = Path(
            str(law_metadata["local_pdf_path"])
        )  # Já verificamos a existência

        echo(f"☁️  Tentando upload de {pdf_path.name} para {law_id}...")
        update_data: Dict[str, Any] = {
            "ultima_tentativa_upload_em": datetime.now().isoformat()
        }
        try:
            # O método upload_pdf espera metadados da lei para construir o identificador do IA
            upload_result = publisher.upload_pdf(pdf_path, law_metadata)

            if upload_result and upload_result.get("success"):
                update_data["url_pdf_ia"] = upload_result.get("url")  # ou 'ia_pdf_url'
                update_data["ia_item_id"] = upload_result.get("ia_item_id")
                update_data["url_torrent_ia"] = upload_result.get("ia_torrent_url")
                update_data["magnet_link_ia"] = upload_result.get("ia_magnet_link")
                update_data["status_geral"] = "publicado_ia"
                update_data["status_upload"] = "sucesso"
                db.update_lei(
                    law_id, update_data
                )  # insert_lei faria upsert, mas update_lei é mais semântico se o registro já existe
                uploaded_count += 1
                echo(
                    style(
                        f"✅ Upload bem-sucedido para {law_id}! URL IA: {upload_result.get('url')}",
                        fg=typer.colors.GREEN,
                    )
                )
                if upload_result.get("ia_torrent_url"):
                    echo(
                        style(
                            f"  Torrente: {upload_result['ia_torrent_url']}",
                            fg=typer.colors.BRIGHT_BLACK,
                        )
                    )
            else:
                error_msg = upload_result.get("error", "Erro desconhecido do publisher")
                update_data["status_upload"] = "falha_publisher"
                update_data["erro_upload_info"] = error_msg
                db.update_lei(law_id, update_data)
                echo(
                    style(
                        f"❌ Falha no upload para {law_id}: {error_msg}",
                        fg=typer.colors.RED,
                    )
                )

        except Exception as e:
            echo(
                style(
                    f"❌ Erro crítico durante o upload de {pdf_path.name} para {law_id}: {e}",
                    fg=typer.colors.RED,
                )
            )
            import traceback

            traceback.print_exc()
            update_data["status_upload"] = "erro_critico"
            update_data["erro_upload_info"] = str(e)
            db.update_lei(law_id, update_data)
            logger.error(
                f"Erro crítico durante o upload para {law_id}.",
                law_id=law_id,
                pdf_path=str(pdf_path),
                error_details=str(e),
            )

    final_message = f"Processo de upload concluído. {uploaded_count} PDFs enviados para o Internet Archive."
    echo(style(f"🎉 {final_message}", bold=True))
    logger.info(
        final_message,
        uploaded_count=uploaded_count,
        attempted_count=len(
            valid_laws_to_upload
        ),  # valid_laws_to_upload é a lista de tentativas
        status="success"
        if uploaded_count == len(valid_laws_to_upload) or not valid_laws_to_upload
        else "partial_success",
    )


@app.command("export")
def cmd_export(
    ctx: typer.Context,
    origem: Optional[str] = typer.Option(
        None,
        help="Origem das leis para exportar. Se não informado, exporta todas as origens em arquivos separados.",
    ),
    year: Optional[int] = typer.Option(
        None, help="Ano específico para filtrar a exportação."
    ),
    format: str = typer.Option(
        "parquet", help="Formato de exportação (suporta: parquet, jsonl)."
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output-dir",
        "-o",
        help=f"Diretório para salvar os arquivos exportados. Padrão: {config.DATA_DIR / 'exports'}",
    ),
):
    """📦 Exportar dataset de leis do banco de dados local."""
    logger = StructuredLogger(command_name="export")

    effective_output_dir = output_dir if output_dir else config.DATA_DIR / "exports"
    effective_output_dir.mkdir(parents=True, exist_ok=True)

    log_params = {
        "origem_filtro": origem,
        "ano_filtro": year,
        "formato": format,
        "output_directory": str(effective_output_dir),
    }
    logger.info("Iniciando exportação de dataset.", **log_params)

    echo(
        style(
            f"📦 Exportando dataset para '{effective_output_dir}' no formato '{format}'...",
            bold=True,
        )
    )
    if origem:
        echo(f"Filtrando pela origem: {origem}")
    if year:
        echo(f"Filtrando pelo ano: {year}")

    publisher = InternetArchivePublisher()

    exported_files: List[Path] = []
    manifest_generated_path: Optional[Path] = None

    try:
        if format == "parquet":
            exported_files = publisher.export_dataset_parquet(
                effective_output_dir, specific_origem=origem, specific_ano=year
            )
        elif format == "jsonl":
            exported_files = publisher.export_dataset_jsonl(
                effective_output_dir, specific_origem=origem, specific_ano=year
            )
        else:
            error_msg = f"Formato de exportação '{format}' não suportado."
            echo(style(f"❌ {error_msg}", fg=typer.colors.RED))
            logger.error(error_msg, formato_solicitado=format, status="failure")
            raise typer.Exit(1)

        if exported_files:
            success_msg = f"Dataset(s) exportado(s) com sucesso: {', '.join(map(str, exported_files))}"
            echo(style(f"✅ {success_msg}", fg=typer.colors.GREEN))
            logger.info(
                success_msg,
                exported_file_paths=[str(p) for p in exported_files],
                status="success",
            )

            if origem:
                manifest_generated_path = publisher.generate_dataset_manifest(
                    origem, effective_output_dir, year
                )
                logger.info(
                    f"Manifesto gerado: {manifest_generated_path}",
                    manifest_path=str(manifest_generated_path),
                )
            else:
                msg_multi_origem = "Exportação de múltiplas origens. Manifesto não gerado automaticamente para o consolidado. Gere por origem individual se necessário."
                echo(style(f"⚠️  {msg_multi_origem}", fg=typer.colors.YELLOW))
                logger.warning(
                    msg_multi_origem, tipo_exportacao="multi_origem_sem_manifesto_unico"
                )
        else:
            info_msg = (
                "Nenhum dado encontrado para exportação com os filtros fornecidos."
            )
            echo(style(f"ℹ️ {info_msg}", fg=typer.colors.YELLOW))
            logger.info(info_msg, status="nodata")

    except Exception as e:
        error_msg = f"Erro durante a exportação: {e}"
        echo(style(f"❌ {error_msg}", fg=typer.colors.RED))
        logger.critical(error_msg, error_details=str(e), status="failure")
        import traceback

        traceback.print_exc()
        raise typer.Exit(1)


@app.command("search")
def cmd_search(
    ctx: typer.Context,
    text: Optional[str] = typer.Option(
        None,
        "--text",
        "-t",
        help="Buscar por texto no título ou metadados (busca simples).",
    ),
    origem: Optional[str] = typer.Option(
        None, "--origem", "-o", help="Filtrar por origem."
    ),
    year: Optional[int] = typer.Option(
        None, "--year", "-y", help="Filtrar por ano de publicação."
    ),
    status: Optional[str] = typer.Option(
        None,
        "--status",
        "-s",
        help="Filtrar por status_geral (ex: descoberto, publicado_ia).",
    ),
    limit: int = typer.Option(20, help="Limite de resultados."),
    show_all_fields: bool = typer.Option(
        False, "--all-fields", help="Mostrar todos os campos do registro em JSON."
    ),
):
    """🔍 Buscar leis no banco de dados local."""
    echo(style("🔍 Buscando leis no banco de dados...", bold=True))

    db = db_storage_instance  # Alterado para usar a instância global
    laws = db.search_leis(
        texto_busca=text,  # Renomeado na classe DBManager
        origem=origem,
        ano=year,
        status_geral=status,  # Novo filtro
        limit=limit,
    )

    if not laws:
        echo(
            style(
                "📭 Nenhuma lei encontrada com os critérios fornecidos.",
                fg=typer.colors.YELLOW,
            )
        )
        return

    echo(style(f"📋 Encontradas {len(laws)} leis:", fg=typer.colors.CYAN))
    for law in laws:
        if show_all_fields:
            # import json # Movido para o topo do arquivo
            echo(
                json.dumps(law, indent=2, ensure_ascii=False, default=str)
            )  # default=str para lidar com datas/Path
        else:
            title = law.get("titulo", "N/A")
            year_str = f"({law.get('ano', 'N/A')})" if law.get("ano") else ""
            origem_str = law.get("origem", "N/A")
            status_str = law.get("status_geral", "N/A")
            id_str = law.get("id", "N/A")
            pdf_info = ""
            if law.get("url_pdf_ia"):
                pdf_info = style("[IA]", fg=typer.colors.GREEN)
            elif (
                law.get("local_pdf_path") and Path(str(law["local_pdf_path"])).exists()
            ):
                pdf_info = style("[Local]", fg=typer.colors.BLUE)

            echo(
                f"  • {style(id_str, bold=True)}: {title[:70]}... {year_str} - {origem_str} {pdf_info} ({status_str})"
            )


@app.command("stats")
def cmd_stats(ctx: typer.Context):
    """📊 Mostrar estatísticas do banco de dados de leis."""
    echo(style("📊 Estatísticas do banco de dados:", bold=True))

    db = db_storage_instance
    stats = db.get_stats()

    echo(
        f"  📚 Total de registros de leis: {style(str(stats.get('total_leis', 0)), bold=True)}"
    )

    # ... (seções Por Origem e Por Ano permanecem as mesmas) ...
    echo(style("\n  🏛️ Por Origem:", bold=True))
    if stats.get("por_origem"):
        for origem_stat, count in stats["por_origem"].items():
            echo(f"    • {style(str(origem_stat), fg=typer.colors.CYAN)}: {count}")
    else:
        echo("    Nenhuma lei encontrada.")

    echo(style("\n  📅 Por Ano de Publicação:", bold=True))
    if stats.get("por_ano"):
        for year_stat, count in sorted(
            stats["por_ano"].items(), reverse=True
        ):  # Mais recentes primeiro
            echo(f"    • {style(str(year_stat), fg=typer.colors.BLUE)}: {count}")
    else:
        echo("    Nenhuma lei com ano definido.")

    # Novos status
    for status_key, status_label in [
        ("por_status_geral", "🚦 Status Geral das Leis"),
        ("por_status_download", "📥 Status de Download de PDFs"),
        ("por_status_upload", "☁️ Status de Upload para IA"),
    ]:
        echo(style(f"\n  {status_label}:", bold=True))
        if stats.get(status_key):
            for status_val, count in stats[status_key].items():
                echo(
                    f"    • {style(str(status_val), fg=typer.colors.GREEN if 'sucesso' in str(status_val) else typer.colors.YELLOW)}: {count}"
                )
        else:
            echo("    Nenhum status encontrado para esta categoria.")

    echo(style("\n  🤖 Monitoramento:", bold=True))
    ultima_execucao_geral = stats.get("monitor_geral_ultima_execucao_sucesso")
    if ultima_execucao_geral:
        # Formatar data para melhor leitura
        try:
            dt_obj = datetime.fromisoformat(str(ultima_execucao_geral))
            ultima_execucao_str = dt_obj.strftime("%d/%m/%Y %H:%M:%S")
        except Exception:  # Corrigido E722
            ultima_execucao_str = str(ultima_execucao_geral)
        echo(
            f"  Última execução bem-sucedida do monitor (geral): {style(ultima_execucao_str, bold=True)}"
        )
    else:
        echo("  Monitor ainda não executado com sucesso (nenhuma origem).")

    if stats.get("monitor_por_origem"):
        echo("  Detalhes por origem:")
        for mon_origem in stats["monitor_por_origem"]:
            origem_id = mon_origem["origem"]
            last_run = mon_origem["last_successful_run_at"]
            items_disc = mon_origem["last_items_discovered"]
            marker = mon_origem["last_processed_marker"]

            try:
                dt_obj_origem = datetime.fromisoformat(str(last_run))
                last_run_str = (
                    dt_obj_origem.strftime("%d/%m/%Y %H:%M:%S") if last_run else "N/A"
                )
            except Exception:  # Corrigido E722
                last_run_str = str(last_run) if last_run else "N/A"

            echo(f"    • {style(origem_id, fg=typer.colors.MAGENTA)}:")
            echo(f"        Última execução: {last_run_str}")
            echo(
                f"        Itens descobertos na última execução: {items_disc if items_disc is not None else 'N/A'}"
            )
            echo(f"        Último marcador processado: {marker if marker else 'N/A'}")

    # Placeholder para contagem de erros nos logs (próxima etapa)
    echo(style("\n  🔍 Análise de Logs (Contagem de Erros Recentes):", bold=True))

    error_count_total = 0
    log_files_to_check = []
    today_date_str = datetime.now().strftime("%Y-%m-%d")

    # Considerar logs do dia atual para todos os comandos
    for cmd_name in ["discover", "download", "upload", "export", "monitor"]:
        log_file = config.LOGS_DIR / f"{cmd_name}_{today_date_str}.jsonl"
        if log_file.exists():
            log_files_to_check.append(log_file)

    if not log_files_to_check:
        echo("    Nenhum arquivo de log encontrado para o dia de hoje.")
    else:
        echo(
            f"    Analisando logs de hoje: {[str(f.name) for f in log_files_to_check]}"
        )
        for log_file_path in log_files_to_check:
            try:
                with open(log_file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            log_entry = json.loads(line)
                            event_type = log_entry.get("event_type", "").lower()
                            status = log_entry.get("status", "").lower()
                            # Contar se for um tipo de erro ou status de falha
                            if (
                                "error" in event_type
                                or "critical" in event_type
                                or status == "failure"
                            ):
                                error_count_total += 1
                        except json.JSONDecodeError:
                            # Linha mal formatada, pode registrar isso também se necessário
                            # logger.warning(f"Linha de log mal formatada em {log_file_path}: {line[:100]}")
                            pass
            except Exception as e:
                echo(
                    style(
                        f"    Erro ao processar arquivo de log {log_file_path}: {e}",
                        fg=typer.colors.RED,
                    )
                )

        if error_count_total > 0:
            echo(
                style(
                    f"    Total de {error_count_total} erros/falhas encontrados nos logs de hoje.",
                    fg=typer.colors.RED,
                    bold=True,
                )
            )
        else:
            echo(
                style(
                    "    Nenhum erro/falha encontrado nos logs de hoje.",
                    fg=typer.colors.GREEN,
                )
            )


@app.command("pipeline")
def cmd_pipeline(
    ctx: typer.Context,
    origem: str = typer.Option(..., help="Origem para executar o pipeline completo."),
    limit_discover: Optional[int] = typer.Option(
        None,
        help="Parâmetro 'limit' ou similar para a fase de descoberta (depende do conector). Ex: end_coddoc para rondonia.",
    ),
    extra_discover_params: Optional[List[str]] = typer.Option(
        None,
        "--extra-discover-params",
        "-P",
        help="Parâmetros extras para a descoberta (key=value).",
    ),
    limit_download: int = typer.Option(10, help="Limite para a fase de download."),
    limit_upload: int = typer.Option(5, help="Limite para a fase de upload."),
    skip_discover: bool = typer.Option(False, help="Pular fase de descoberta."),
    skip_download: bool = typer.Option(False, help="Pular fase de download."),
    skip_upload: bool = typer.Option(False, help="Pular fase de upload."),
    skip_export: bool = typer.Option(False, help="Pular fase de exportação."),
):
    """🚀 Executar pipeline completo (discover -> download -> upload -> export) para uma origem."""
    echo(
        style(
            f"🚀 Executando pipeline completo para '{origem}'...",
            bold=True,
            fg=typer.colors.MAGENTA,
        )
    )

    start_time = datetime.now()

    try:
        if not skip_discover:
            echo(
                style(
                    "\n--- Etapa 1/4: Descobrindo leis ---",
                    bold=True,
                    fg=typer.colors.CYAN,
                )
            )
            # Construir os parâmetros para discover
            # discover_params = {'origem': origem} # Removido F841
            if (
                limit_discover is not None
            ):  # Este é um exemplo, pode não ser 'limit' para todos
                # O ideal é que o conector de Rondônia use start_coddoc e end_coddoc
                # Para outros, pode ser `limit` ou `days_ago`, etc.
                # Aqui, vamos assumir que o usuário sabe o que passar em extra_discover_params
                echo(
                    style(
                        f"⚠️  Opção --limit-discover ({limit_discover}) é genérica. Use --extra-discover-params para parâmetros específicos do conector como 'end_coddoc'.",
                        fg=typer.colors.YELLOW,
                    )
                )

            current_extra_params = (
                list(extra_discover_params) if extra_discover_params else []
            )
            # Exemplo: se limit_discover for um coddoc final para Rondônia
            # if origem == "rondonia" and limit_discover is not None:
            # current_extra_params.append(f"end_coddoc={limit_discover}")

            ctx.invoke(cmd_discover, origem=origem, extra_params=current_extra_params)
        else:
            echo(
                style(
                    "\n--- Etapa 1/4: Descobrindo leis (PULADA) ---",
                    fg=typer.colors.BRIGHT_BLACK,
                )
            )

        if not skip_download:
            echo(
                style(
                    "\n--- Etapa 2/4: Baixando PDFs ---",
                    bold=True,
                    fg=typer.colors.CYAN,
                )
            )
            ctx.invoke(
                cmd_download, origem=origem, limit=limit_download, overwrite=False
            )
        else:
            echo(
                style(
                    "\n--- Etapa 2/4: Baixando PDFs (PULADA) ---",
                    fg=typer.colors.BRIGHT_BLACK,
                )
            )

        if not skip_upload:
            echo(
                style(
                    "\n--- Etapa 3/4: Upload para Internet Archive ---",
                    bold=True,
                    fg=typer.colors.CYAN,
                )
            )
            ctx.invoke(
                cmd_upload, origem=origem, limit=limit_upload, overwrite_ia=False
            )
        else:
            echo(
                style(
                    "\n--- Etapa 3/4: Upload para IA (PULADA) ---",
                    fg=typer.colors.BRIGHT_BLACK,
                )
            )

        if not skip_export:
            echo(
                style(
                    "\n--- Etapa 4/4: Exportando dataset ---",
                    bold=True,
                    fg=typer.colors.CYAN,
                )
            )
            # Exportar apenas a origem processada, sem filtro de ano, formato parquet
            ctx.invoke(
                cmd_export, origem=origem, year=None, format="parquet", output_dir=None
            )
        else:
            echo(
                style(
                    "\n--- Etapa 4/4: Exportando dataset (PULADA) ---",
                    fg=typer.colors.BRIGHT_BLACK,
                )
            )

        end_time = datetime.now()
        duration = end_time - start_time
        echo(
            style(
                f"\n✅ Pipeline para '{origem}' concluído com sucesso!",
                bold=True,
                fg=typer.colors.GREEN,
            )
        )
        echo(f"⏱️  Tempo total de execução: {duration}")

    except typer.Exit:  # Captura saídas limpas de subcomandos
        echo(
            style(
                f"\n❌ Pipeline para '{origem}' interrompido devido a erro em uma das etapas.",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        # Não precisa re-raise, Typer já lidou com o exit.
    except Exception as e:
        echo(
            style(
                f"\n❌ Pipeline para '{origem}' falhou com erro inesperado: {e}",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        import traceback

        traceback.print_exc()
        # Não precisa de raise typer.Exit(1) aqui se o erro já causou a saída.


# --- Subcomandos para Gerenciamento de Conectores ---
connector_app = typer.Typer(
    name="connector", help="🔩 Gerenciar e interagir com conectores de dados."
)
app.add_typer(connector_app, name="connector")


@connector_app.command("list")
def connector_list(
    ctx: typer.Context,
):
    """📋 Listar todos os conectores disponíveis e carregados."""
    load_connectors(force_reload=True)  # Força recarregar para pegar novos arquivos
    if not _LOADED_CONNECTORS:
        echo(
            style("❎ Nenhum conector encontrado ou carregado.", fg=typer.colors.YELLOW)
        )
        echo(f"Verifique o diretório: {_CONNECTORS_PATH}")
        return

    echo(style("📚 Conectores disponíveis:", bold=True))
    for origem_key, conn_instance in _LOADED_CONNECTORS.items():
        echo(
            f"  • {style(origem_key, bold=True, fg=typer.colors.CYAN)} ({conn_instance.__class__.__name__} de {conn_instance.__class__.__module__})"
        )

    if not _LOADED_CONNECTORS:  # Checagem dupla caso force_reload não encontre nada
        echo(style("Nenhum conector carregado após a tentativa.", fg=typer.colors.RED))


@connector_app.command("new")
def connector_new(
    ctx: typer.Context,
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Nome do novo conector (ex: acre, minasgerais). Será usado como ORIGEM e nome do arquivo.",
    ),
):
    """✨ Criar um novo arquivo de esqueleto para um conector."""
    echo(style(f"✨ Criando esqueleto para um novo conector: '{name}'...", bold=True))

    connector_name_lower = name.lower().replace("-", "_").replace(" ", "_")
    connector_class_name = (
        "".join(part.capitalize() for part in connector_name_lower.split("_"))
        + "Connector"
    )
    connector_file_name = f"{connector_name_lower}.py"
    connector_file_path = _CONNECTORS_PATH / connector_file_name

    if connector_file_path.exists():
        echo(
            style(
                f"❌ Arquivo '{connector_file_path}' já existe. Escolha um nome diferente.",
                fg=typer.colors.RED,
            )
        )
        raise typer.Exit(1)

    template = f"""\
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional

from .base import BaseConnector
# Se precisar de config:
# import config
# Se precisar de Playwright (ou outras libs pesadas), adicione as importações:
# from playwright.async_api import async_playwright, Browser, Page


class {connector_class_name}(BaseConnector):
    \"\"\"Conector para leis de {name}.\"\"\"
    ORIGEM = "{connector_name_lower}" # Identificador único para este conector

    def __init__(self):
        super().__init__() # Se BaseConnector tiver __init__
        # self.browser: Optional[Browser] = None
        # self.playwright = None
        # Adapte conforme necessidade (ex: delay, timeout, retries)
        # self.delay = config.CRAWLER_DELAY if hasattr(config, 'CRAWLER_DELAY') else 1000
        # self.timeout = config.CRAWLER_TIMEOUT if hasattr(config, 'CRAWLER_TIMEOUT') else 30000
        echo(f"[{{self.ORIGEM}}] Conector inicializado.")

    # Opcional: Implementar se o conector precisar de setup/teardown assíncrono (ex: Playwright)
    # async def _start_browser(self) -> None:
    #     if not self.browser or not self.browser.is_connected():
    #         self.playwright = await async_playwright().start()
    #         self.browser = await self.playwright.chromium.launch(headless=True)
    #         echo(f"[{{self.ORIGEM}}] Browser Playwright iniciado.")

    # async def _stop_browser(self) -> None:
    #     if self.browser and self.browser.is_connected():
    #         await self.browser.close()
    #         echo(f"[{{self.ORIGEM}}] Browser Playwright fechado.")
    #     if self.playwright:
    #         await self.playwright.stop()
    #         self.playwright = None

    # async def __aenter__(self):
    #     await self._start_browser()
    #     return self

    # async def __aexit__(self, exc_type, exc_val, exc_tb):
    #     await self._stop_browser()
    
    # async def close(self): # Se não usar __aexit__ mas precisar de limpeza async
    #    await self._stop_browser()


    async def discover_laws(self, **kwargs) -> List[Dict[str, Any]]:
        \"\"\"
        Descobre novas leis ou atos para '{connector_name_lower}'.
        
        Este método deve retornar uma lista de dicionários, cada um representando
        uma lei/ato descoberto com metadados básicos.
        
        Metadados esperados minimamente (verifique `BaseConnector` e `storage.py`):
        - id (str): Identificador único da lei nesta origem (ex: "{connector_name_lower}-numero-ano")
        - titulo (str): Título completo da lei/ato.
        - origem (str): Deve ser self.ORIGEM.
        - url_original_lei (Optional[str]): URL da página HTML da lei (se houver).
        - url_pdf_original (Optional[str]): URL direta para o arquivo PDF.
        - data_publicacao (Optional[str]): Data da publicação no formato "YYYY-MM-DD".
        - numero (Optional[str]): Número da lei/ato.
        - ano (Optional[int]): Ano da lei/ato.
        - tipo_lei (Optional[str]): Tipo de ato (ex: 'lei', 'decreto', 'portaria').
        - metadados_coleta (dict): Dicionário para informações extras da coleta.
                                  (ex: {{'fonte_declarada': 'Nome do Portal', ...}})
        
        Args:
            **kwargs: Argumentos variáveis que podem ser passados pelo CLI ou monitor.
                      Ex: start_date, end_date, specific_ids, etc.
                      O conector deve decidir como usá-los ou ignorá-los.
                      `kwargs.get('param_name', default_value)`

        Returns:
            Lista de dicionários com metadados das leis.
        \"\"\"
        echo(f"[{{self.ORIGEM}}] Iniciando descoberta de leis com params: {{kwargs}}")
        discovered_laws: List[Dict[str, Any]] = []

        # --- INÍCIO DA LÓGICA DE DESCOBERTA ESPEĆIFICA PARA {name} ---
        # Exemplo:
        # try:
        #     async with self: # Se usar __aenter__/__aexit__ para gerenciar recursos como browser
        #         # page = await self.browser.new_page()
        #         # await page.goto("URL_DO_PORTAL_DE_{name}")
        #         # ... lógica de scraping para encontrar leis ...
        #
        #         # Exemplo de metadados para uma lei descoberta:
        #         law_meta = {{
        #             "id": f"{{self.ORIGEM}}-exemplo-123-2024",
        #             "titulo": "Lei Exemplo Nº 123 de 2024",
        #             "origem": self.ORIGEM,
        #             "url_original_lei": "http://portal.example.com/{name}/lei123.html",
        #             "url_pdf_original": "http://portal.example.com/{name}/pdfs/lei123.pdf",
        #             "data_publicacao": "2024-01-15", # Formato YYYY-MM-DD
        #             "numero": "123",
        #             "ano": 2024,
        #             "tipo_lei": "lei complementar", # ou 'lei ordinaria', 'decreto', etc.
        #             "metadados_coleta": {{
        #                 "fonte_declarada": "Portal de Leis de {name}",
        #                 "descoberto_em_conector": datetime.now().isoformat(),
        #                 # Adicione outros campos relevantes aqui
        #             }}
        #         }}
        #         discovered_laws.append(law_meta)
        #         echo(f"[{{self.ORIGEM}}] Descoberta: {{law_meta['titulo']}}")
        #
        # except Exception as e:
        #     echo(f"[{{self.ORIGEM}}] Erro durante a descoberta: {{e}}")
        #     # Considere logar o traceback para depuração
        #     # import traceback; traceback.print_exc();
        #
        # --- FIM DA LÓGICA DE DESCOBERTA ---

        if not discovered_laws:
            echo(f"[{{self.ORIGEM}}] Nenhuma lei descoberta nesta execução.")

        return discovered_laws

    async def download_pdf(self, law_metadata: Dict[str, Any], output_path: Path) -> bool:
        \"\"\"
        Baixa o PDF de uma lei específica para o caminho fornecido.

        Args:
            law_metadata (Dict[str, Any]): Metadados da lei, como retornado por discover_laws.
                                           Deve conter 'url_pdf_original'.
            output_path (Path): Caminho completo onde o PDF deve ser salvo.

        Returns:
            True se o download foi bem-sucedido, False caso contrário.
        \"\"\"
        pdf_url = law_metadata.get('url_pdf_original')
        law_id = law_metadata.get('id', 'ID desconhecido')

        if not pdf_url:
            echo(f"[{{self.ORIGEM}}] URL do PDF não encontrada nos metadados para {{law_id}}.")
            return False

        echo(f"[{{self.ORIGEM}}] Baixando PDF para {{law_id}} de {{pdf_url}} para {{output_path}}")

        # --- INÍCIO DA LÓGICA DE DOWNLOAD ESPEĆIFICA PARA {name} ---
        # Exemplo usando requests (síncrono, para simplicidade - idealmente usar httpx para async)
        # Para downloads simples, pode não precisar de Playwright.
        # Se precisar de Playwright (ex: JS challenge, login), use o browser gerenciado.
        # import httpx # Recomendado para I/O de rede assíncrono
        # try:
        #     async with httpx.AsyncClient(timeout=self.timeout / 1000.0) as client:
        #         response = await client.get(pdf_url)
        #         response.raise_for_status() # Levanta exceção para erros HTTP 4xx/5xx
        #
        #         output_path.parent.mkdir(parents=True, exist_ok=True)
        #         with open(output_path, 'wb') as f:
        #             f.write(response.content)
        #         echo(f"[{{self.ORIGEM}}] PDF baixado com sucesso: {{output_path.name}} ({{len(response.content)}} bytes)")
        #         return True
        #
        # except httpx.HTTPStatusError as e:
        #     echo(f"[{{self.ORIGEM}}] Erro HTTP ao baixar PDF para {{law_id}}: {{e.response.status_code}} - {{e.request.url}}")
        # except httpx.RequestError as e:
        #     echo(f"[{{self.ORIGEM}}] Erro de requisição ao baixar PDF para {{law_id}}: {{e}}")
        # except Exception as e:
        #     echo(f"[{{self.ORIGEM}}] Erro inesperado ao baixar PDF para {{law_id}}: {{e}}")
        #     # import traceback; traceback.print_exc();
        # return False
        #
        # Se usar Playwright:
        # try:
        #     async with self: # Garante que o browser está ativo
        #         page = await self.browser.new_page()
        #         pdf_content = await page.pdf(path=str(output_path)) # Se a página renderiza o PDF
        #         # Ou se for um link direto para download com Playwright:
        #         # async with page.expect_download() as download_info:
        #         #    await page.goto(pdf_url) # ou await page.click('selector_do_link_de_download')
        #         # download = await download_info.value
        #         # await download.save_as(output_path)
        #         # await page.close()
        #
        #         if output_path.exists() and output_path.stat().st_size > 0:
        #             echo(f"[{{self.ORIGEM}}] PDF baixado com sucesso via Playwright: {{output_path.name}}")
        #             return True
        #         else:
        #             echo(f"[{{self.ORIGEM}}] Falha ao baixar PDF com Playwright, arquivo não criado ou vazio.")
        #             return False
        # except Exception as e:
        #     echo(f"[{{self.ORIGEM}}] Erro ao baixar PDF com Playwright para {{law_id}}: {{e}}")
        #     return False
        # --- FIM DA LÓGICA DE DOWNLOAD ---

        # Placeholder:
        echo(f"[{{self.ORIGEM}}] Lógica de download_pdf para {name} ainda não implementada.")
        return False

# Exemplo de como testar este conector individualmente (opcional)
# async def main_test_{connector_name_lower}():
#     from datetime import datetime # Mover para o topo se usado aqui
#     connector = {connector_class_name}()
#
#     # Teste de descoberta
#     echo("\\n--- Testando discover_laws ---")
#     # Passe quaisquer kwargs que seu discover_laws possa esperar para teste
#     discovered_items = await connector.discover_laws(exemplo_param="valor_teste")
#     if discovered_items:
#         echo(f"Descobertos {{len(discovered_items)}} itens.")
#         for item in discovered_items[:2]: # Mostra os 2 primeiros
#             print(item)
#
#         # Teste de download para o primeiro item descoberto que tenha PDF URL
#         first_law_with_pdf = next((item for item in discovered_items if item.get("url_pdf_original")), None)
#         if first_law_with_pdf:
#             echo("\\n--- Testando download_pdf ---")
#             temp_dir = Path("temp_test_downloads") / "{connector_name_lower}"
#             temp_dir.mkdir(parents=True, exist_ok=True)
#
#             # Usar um nome de arquivo mais robusto, talvez do ID
#             law_id_for_file = first_law_with_pdf.get("id", "temp_pdf").replace(":", "_").replace("/", "_")
#             output_file = temp_dir / f"{{law_id_for_file}}.pdf"
#
#             success = await connector.download_pdf(first_law_with_pdf, output_file)
#             if success:
#                 echo(f"PDF de teste salvo em: {{output_file.resolve()}}")
#             else:
#                 echo(f"Falha ao baixar PDF de teste para {{first_law_with_pdf.get('id')}}")
#     else:
#         echo("Nenhum item descoberto para testar o download.")
#
#     # Se o conector usa recursos que precisam ser fechados (ex: browser Playwright)
#     # e não usa __aenter__/__aexit__, chame o método de fechamento aqui.
#     # if hasattr(connector, 'close') and inspect.iscoroutinefunction(connector.close):
#     #     await connector.close()

# if __name__ == "__main__":
#     # Para executar este teste: python -m src.connectors.{connector_name_lower}
#     # Adicione o diretório raiz ao PYTHONPATH ou use `uv run python -m src.connectors.{connector_name_lower}`
#     # Exemplo de como adicionar o projeto ao path para teste direto:
#     # import sys
#     # sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
#     # from src.connectors.base import BaseConnector # Mover para topo se usado no if __name__
#     # import config # Mover para topo se usado no if __name__
#
#     # asyncio.run(main_test_{connector_name_lower}())
"""

    try:
        _CONNECTORS_PATH.mkdir(parents=True, exist_ok=True)
        with open(connector_file_path, "w", encoding="utf-8") as f:
            f.write(template)
        echo(
            style(
                f"✅ Esqueleto do conector '{connector_class_name}' criado em:",
                fg=typer.colors.GREEN,
            )
        )
        echo(style(str(connector_file_path.resolve()), underline=True))
        echo(style("👉 Próximos passos:", bold=True))
        echo(
            "   1. Abra o arquivo e implemente a lógica de descoberta em `discover_laws()`."
        )
        echo("   2. Implemente a lógica de download de PDF em `download_pdf()`.")
        echo(
            '   3. Teste seu conector (ex: usando o bloco `if __name__ == "__main__":` no final do arquivo).'
        )
        echo(
            f"   4. Após testar, você pode usar: `uv run leizilla discover --origem {connector_name_lower}`"
        )

    except Exception as e:
        echo(style(f"❌ Erro ao criar arquivo do conector: {e}", fg=typer.colors.RED))
        if (
            connector_file_path.exists()
        ):  # Tentar limpar se algo foi criado parcialmente
            try:
                connector_file_path.unlink()
            except Exception as unlink_e:
                echo(
                    style(
                        f"⚠️  Erro adicional ao tentar remover arquivo parcialmente criado: {unlink_e}",
                        fg=typer.colors.YELLOW,
                    )
                )
        raise typer.Exit(1)


# --- Comando Monitor ---
@app.command("monitor")
def cmd_monitor(
    ctx: typer.Context,
    origens: Optional[List[str]] = typer.Option(
        None,
        "--origem",
        "-o",
        help="Processar apenas estas origens. Se não especificado, processa todas.",
    ),
    skip_discovery: Optional[List[str]] = typer.Option(
        None,
        "--skip-discovery",
        help="Lista de origens para pular a fase de descoberta.",
    ),
    skip_download: Optional[List[str]] = typer.Option(
        None, "--skip-download", help="Lista de origens para pular a fase de download."
    ),
    skip_upload: Optional[List[str]] = typer.Option(
        None, "--skip-upload", help="Lista de origens para pular a fase de upload."
    ),
    max_items_discover: int = typer.Option(
        0,
        help="Número máximo de itens a serem processados pela descoberta por origem (0 para sem limite).",
    ),
    max_items_download: int = typer.Option(
        10, help="Número máximo de itens a serem baixados por origem por execução."
    ),
    max_items_upload: int = typer.Option(
        5, help="Número máximo de itens a serem enviados ao IA por origem por execução."
    ),
    force_redownload: bool = typer.Option(
        False, help="Forçar o download de PDFs mesmo que já existam localmente."
    ),
    force_reupload_ia: bool = typer.Option(
        False, help="Forçar o upload para o IA mesmo que já exista um link."
    ),
):
    """🚦 Monitorar todas as fontes, descobrir, baixar e publicar novas leis."""
    load_connectors(
        force_reload=True
    )  # Garante que temos a lista mais recente de conectores
    if not _LOADED_CONNECTORS:
        echo(
            style(
                "❎ Nenhum conector carregado. Nada para monitorar.",
                fg=typer.colors.YELLOW,
            )
        )
        return

    all_origines_available = list(_LOADED_CONNECTORS.keys())
    origines_to_process = origens if origens else all_origines_available

    # Validar origens especificadas
    for o in origines_to_process:
        if o not in all_origines_available:
            echo(
                style(
                    f"❌ Origem '{o}' especificada para processamento não é um conector válido/carregado. Disponíveis: {all_origines_available}",
                    fg=typer.colors.RED,
                )
            )
            raise typer.Exit(1)

    echo(
        style(
            f"🚦 Iniciando monitoramento para origens: {origines_to_process}", bold=True
        )
    )

    # Inicializar gerenciador de BD e publicador
    db = db_storage_instance  # Alterado para usar a instância global
    publisher = InternetArchivePublisher()  # Não é async

    # --- Lógica do Log Estruturado ---
    log_file_name = f"monitor_{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    log_file_path = config.LOGS_DIR / log_file_name

    # Garante que LOGS_DIR existe, config.py já faz isso, mas é bom ser explícito se usado isoladamente
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)

    def log_event(event_data: Dict[str, Any], print_to_console: bool = True):
        # Adicionar informações padrão a todos os eventos
        full_event_data = {
            "timestamp": datetime.now().isoformat(),
            "event_source": "monitor_command",
            **event_data,  # Dados específicos do evento vêm depois para poderem sobrescrever se necessário
        }
        try:
            with open(log_file_path, "a", encoding="utf-8") as f:
                # Usar json.default para lidar com tipos não serializáveis como Path
                f.write(
                    json.dumps(full_event_data, ensure_ascii=False, default=str) + "\n"
                )

            if print_to_console:
                # Simplificar um pouco a mensagem do console
                log_type = full_event_data.get("event_type", "log")
                origem_info = (
                    f" (Origem: {full_event_data['origem']})"
                    if "origem" in full_event_data
                    else ""
                )
                message = full_event_data.get("message", "")
                details = full_event_data.get("details", "")
                count = full_event_data.get("count", "")
                status_info = full_event_data.get("status", "")

                console_msg = f"🗒️  LOG [{log_type}]{origem_info}: {message}"
                if details:
                    console_msg += f" | Detalhes: {details}"
                if count:
                    console_msg += f" | Contagem: {count}"
                if status_info:
                    console_msg += f" | Status: {status_info}"

                # Escolher cor com base no tipo de evento ou status
                color = typer.colors.BRIGHT_BLACK
                if "error" in log_type.lower() or status_info.lower() == "failure":
                    color = typer.colors.RED
                elif "success" in log_type.lower() or "complete" in log_type.lower():
                    color = typer.colors.GREEN
                elif "start" in log_type.lower():
                    color = typer.colors.BLUE

                echo(style(console_msg, fg=color))

        except Exception as e:
            echo(
                style(
                    f"🚨 Erro CRÍTICO ao tentar gravar log: {e}",
                    fg=typer.colors.RED,
                    bold=True,
                )
            )
            echo(f"Dados do evento que falhou: {full_event_data}")

    log_event(
        {
            "event_type": "monitor_session_start",
            "message": "Sessão de monitoramento iniciada.",
            "origines_configuradas_para_processar": origines_to_process,
            "skip_flags": {
                "discovery": skip_discovery,
                "download": skip_download,
                "upload": skip_upload,
            },
            "force_flags": {
                "redownload": force_redownload,
                "reupload_ia": force_reupload_ia,
            },
            "limites_por_origem": {
                "discover": max_items_discover,
                "download": max_items_download,
                "upload": max_items_upload,
            },
        },
        print_to_console=False,
    )  # Não imprimir este log inicial muito verboso

    async def run_monitor_pipeline():
        for origem_id in origines_to_process:
            log_event_origem_base = {"origem": origem_id}
            connector = get_connector(origem_id)

            if not connector:
                msg = f"Conector '{origem_id}' não encontrado no momento do processamento. Pulando."
                echo(style(f"❓ {msg}", fg=typer.colors.YELLOW))
                log_event(
                    {
                        **log_event_origem_base,
                        "event_type": "connector_load_failure",
                        "message": msg,
                        "status": "skipped",
                    }
                )
                continue

            echo(
                style(
                    f"\n--- Processando Origem: {origem_id} ---",
                    bold=True,
                    fg=typer.colors.CYAN,
                )
            )
            log_event(
                {
                    **log_event_origem_base,
                    "event_type": "origem_processing_start",
                    "message": "Iniciando processamento da origem.",
                }
            )

            # Recuperar o estado do monitor para esta origem
            monitor_state = db.get_monitor_state(origem_id)
            last_processed_marker = (
                monitor_state.get("last_processed_marker") if monitor_state else None
            )
            echo(
                f"  ℹ️  Estado de monitoramento para '{origem_id}': Último marcador = {last_processed_marker}"
            )

            # Argumentos para a descoberta, podem incluir o marcador
            # A forma como o marcador é usado depende da implementação do conector.
            # Alguns podem aceitar 'since_date', 'start_id', etc.
            # Por agora, vamos assumir que o conector pode receber `last_processed_marker` em kwargs.
            discover_call_kwargs = {"last_processed_marker": last_processed_marker}
            if max_items_discover > 0 and hasattr(connector, "discover_laws"):
                sig = inspect.signature(connector.discover_laws)
                if "limit" in sig.parameters:
                    discover_call_kwargs["limit"] = max_items_discover

            current_origem_processed_items_count = 0
            new_marker_candidate = last_processed_marker  # Inicia com o marcador antigo

            # 1. Descoberta
            all_discovered_this_run: List[Dict[str, Any]] = []
            newly_inserted_ids_this_run: List[str] = []
            discovery_skipped_flag = bool(
                skip_discovery and origem_id in skip_discovery
            )

            if not discovery_skipped_flag:
                log_event(
                    {
                        **log_event_origem_base,
                        "event_type": "discovery_phase_start",
                        "message": "Iniciando fase de descoberta.",
                    }
                )
                echo(f"🔍 Fase de Descoberta para '{origem_id}'...")
                try:
                    # Aqui, `discover_laws` precisa ser adaptado para aceitar `last_processed` e `limit`
                    # ou o CLI passa isso via `extra_params` se o comando `discover` for invocado.
                    # Para o monitor, vamos chamar diretamente o método do conector.
                    # O conector deve ser responsável por filtrar com base no `last_processed`.
                    # Se o conector não suportar, ele pode re-descobrir tudo, e o monitor filtra depois.

                    # Placeholder para parâmetros de descoberta:
                    # Idealmente, o `discover_laws` do conector aceitaria `since` ou `offset`
                    # Por agora, vamos pegar tudo e filtrar depois, ou limitar se `max_items_discover`
                    # for usado pelo conector.
                    discover_call_kwargs = {}  # Resetando para não pegar o last_processed_marker diretamente se o conector não o usa
                    if max_items_discover > 0 and hasattr(connector, "discover_laws"):
                        sig = inspect.signature(connector.discover_laws)
                        if "limit" in sig.parameters:  # Se o conector aceita um 'limit'
                            discover_call_kwargs["limit"] = max_items_discover
                        # Adicionar outros parâmetros como start_coddoc/end_coddoc se necessário
                        # e se o conector os suportar.
                        # Se o conector tiver um parâmetro específico para 'since' ou 'marker', ele deve ser adicionado aqui.
                        # Ex: if 'since_marker' in sig.parameters: discover_call_kwargs['since_marker'] = last_processed_marker

                    async with connector:  # Usar context manager se disponível
                        raw_discovered_items = await connector.discover_laws(
                            **discover_call_kwargs
                        )

                    if raw_discovered_items:
                        for law_meta in raw_discovered_items:
                            # Validar e adicionar/atualizar no DB
                            # Idealmente, `insert_lei` faria upsert.
                            # Verificar se já existe pelo ID antes de inserir/processar.
                            existing_law = db.get_lei_by_id(law_meta.get("id", ""))
                            if (
                                existing_law
                                and not force_redownload
                                and not force_reupload_ia
                            ):  # Simplificação
                                # echo(f"  Lei {law_meta.get('id')} já existe e não forçando. Pulando redescoberta.")
                                # Adicionar à lista para possível re-download/re-upload se forçado
                                all_discovered_this_run.append(
                                    existing_law
                                )  # Usar o que já está no DB
                                continue

                            law_meta["descoberto_em_monitor"] = (
                                datetime.now().isoformat()
                            )
                            law_meta["status_geral"] = "descoberto_monitor"
                            db.insert_lei(
                                law_meta
                            )  # insert_lei deve fazer upsert ou ter lógica para lidar com duplicatas
                            all_discovered_this_run.append(
                                law_meta
                            )  # Adiciona à lista principal após inserção/validação
                            newly_inserted_ids_this_run.append(str(law_meta.get("id")))
                            echo(
                                f"  📥 Descoberto/Atualizado no DB: {law_meta.get('id')} - {law_meta.get('titulo', 'N/A')[:30]}..."
                            )

                    items_found_count = len(
                        all_discovered_this_run
                    )  # Total de itens considerados (novos + existentes forçados)
                    actual_newly_discovered_by_connector = (
                        len(raw_discovered_items) if raw_discovered_items else 0
                    )
                    echo(
                        f"  🏁 Descoberta para '{origem_id}' retornou {actual_newly_discovered_by_connector} itens. Total para processamento: {items_found_count}."
                    )
                    log_event(
                        {
                            **log_event_origem_base,
                            "event_type": "discovery_phase_complete",
                            "message": f"Fase de descoberta concluída. {actual_newly_discovered_by_connector} itens retornados pelo conector. {items_found_count} itens no total para processamento.",
                            "items_returned_by_connector": actual_newly_discovered_by_connector,
                            "newly_inserted_ids_count": len(
                                newly_inserted_ids_this_run
                            ),
                            "total_items_for_processing_phase": items_found_count,
                            "status": "success",
                        }
                    )

                except Exception as e_discover:
                    error_message = (
                        f"Erro na descoberta para '{origem_id}': {e_discover}"
                    )
                    echo(style(f"  ❌ {error_message}", fg=typer.colors.RED))
                    log_event(
                        {
                            **log_event_origem_base,
                            "event_type": "discovery_phase_error",
                            "message": error_message,
                            "error_details": str(e_discover),
                            "status": "failure",
                        }
                    )
                    # Continuar para a próxima origem em caso de erro aqui? Ou parar?
                    # Por enquanto, vamos continuar com os itens já descobertos (se houver) e depois pular para próxima origem.
                    # Se a descoberta falhou completamente, all_discovered_this_run estará vazio.
                    # No entanto, os itens já existentes no DB (e que correspondem ao `last_processed_marker` ou mais recentes)
                    # ainda podem ser considerados para download/upload se as flags `force` estiverem ativas.
                    # Por simplicidade, se a descoberta falhar, não tentamos reprocessar itens antigos a menos que explicitamente pedido.
                    pass  # Erro já logado.

            # Após a descoberta (mesmo que falhe), `all_discovered_this_run` contém o que foi retornado + itens existentes se `force`
            # Se `skip_discovery` for true, precisamos popular `all_discovered_this_run` com itens do DB que podem precisar de ação.
            if discovery_skipped_flag:
                message = f"Fase de Descoberta pulada para '{origem_id}'. Carregando itens do DB para possível download/upload."
                echo(f"⏭️  {message}")
                log_event(
                    {
                        **log_event_origem_base,
                        "event_type": "discovery_phase_skipped",
                        "message": message,
                    }
                )
                # Carregar itens que podem precisar de download ou upload
                # Se `force_redownload` ou `force_reupload_ia` estiverem ativos, a lógica abaixo de seleção será mais permissiva.
                # Esta query busca itens que *poderiam* ser processados.
                all_discovered_this_run = db.search_leis_para_download_ou_upload(
                    origem_id,
                    limit=(
                        max_items_download + max_items_upload + 10
                    ),  # Pega uma margem
                )
                echo(
                    f"  ℹ️  Carregados {len(all_discovered_this_run)} itens do DB para '{origem_id}' para possível processamento."
                )

            # 2. Download de PDFs
            downloaded_this_run = 0
            download_skipped_flag = bool(skip_download and origem_id in skip_download)

            if not download_skipped_flag:
                log_event(
                    {
                        **log_event_origem_base,
                        "event_type": "download_phase_start",
                        "message": "Iniciando fase de download.",
                    }
                )
                echo(f"📥 Fase de Download para '{origem_id}'...")

                # Selecionar leis para download desta lista combinada
                # Uma lei precisa de download se:
                # 1. Tem url_pdf_original
                # 2. (Não tem local_pdf_path OU local_pdf_path não existe OU force_redownload é True)
                # 3. E ainda não tem url_pdf_ia (a menos que force_reupload_ia também esteja ativa, mas isso é mais para upload)
                laws_to_attempt_download = []
                for law_meta in (
                    all_discovered_this_run
                ):  # Itera sobre o que foi descoberto ou carregado do DB
                    if (
                        max_items_download > 0
                        and len(laws_to_attempt_download) >= max_items_download
                    ):  # Respeita o limite
                        break

                    has_pdf_url = bool(law_meta.get("url_pdf_original"))
                    local_path_str = law_meta.get("local_pdf_path")
                    local_file_exists = bool(
                        local_path_str
                        and Path(local_path_str).exists()
                        and Path(local_path_str).is_file()
                    )

                    if has_pdf_url:
                        if not local_file_exists or force_redownload:
                            laws_to_attempt_download.append(law_meta)
                        # Se já tem local_pdf_path e existe, e não é force_redownload, não precisa baixar.

                if not laws_to_attempt_download:
                    echo("  ✅ Nenhuma lei para baixar nesta execução.")
                else:
                    echo(
                        f"  ℹ️  {len(laws_to_attempt_download)} leis para tentar baixar."
                    )
                    download_base_path = (
                        config.TEMP_DIR / "monitor_downloads" / origem_id
                    )
                    download_base_path.mkdir(parents=True, exist_ok=True)

                    async with connector:  # Re-entrar no contexto se necessário (alguns conectores podem precisar)
                        for law_meta in laws_to_attempt_download:  # Corrigido aqui
                            law_id = str(law_meta["id"])
                            pdf_filename = (
                                f"{law_id.replace(':', '_').replace('/', '_')}.pdf"
                            )
                            output_file_path = download_base_path / pdf_filename
                            update_db_fields: Dict[str, Any] = {
                                "ultima_tentativa_download_em": datetime.now().isoformat()
                            }
                            try:
                                success = await connector.download_pdf(
                                    law_meta, output_file_path
                                )
                                if success:
                                    update_db_fields["local_pdf_path"] = str(
                                        output_file_path
                                    )
                                    update_db_fields["status_geral"] = (
                                        "pdf_local_monitor"
                                    )
                                    update_db_fields["status_download"] = (
                                        "sucesso_monitor"
                                    )
                                    law_meta["local_pdf_path"] = str(
                                        output_file_path
                                    )  # Atualiza o dict em memória também
                                    downloaded_this_run += 1
                                    echo(f"    ✅ PDF baixado para {law_id}")
                                else:
                                    update_db_fields["status_download"] = (
                                        "falha_monitor"
                                    )
                                    echo(
                                        style(
                                            f"    ❌ Falha ao baixar PDF para {law_id} (conector indicou falha).",
                                            fg=typer.colors.YELLOW,
                                        )
                                    )
                                db.update_lei(law_id, update_db_fields)
                            except Exception as e_download:
                                update_db_fields["status_download"] = "erro_monitor"
                                update_db_fields["erro_download_info"] = str(e_download)
                                db.update_lei(law_id, update_db_fields)
                                echo(
                                    style(
                                        f"    ❌ Erro crítico ao baixar PDF para {law_id}: {e_download}",
                                        fg=typer.colors.RED,
                                    )
                                )
                                log_event(
                                    {
                                        **log_event_origem_base,
                                        "event_type": "pdf_download_error",
                                        "law_id": law_id,
                                        "message": f"Erro crítico baixando PDF.",
                                        "error_details": str(e_download),
                                        "status": "failure",
                                    }
                                )

                    log_event(
                        {
                            **log_event_origem_base,
                            "event_type": "download_phase_complete",
                            "message": f"Fase de download concluída. {downloaded_this_run} PDFs baixados de {len(laws_to_attempt_download)} tentativas.",
                            "items_downloaded_successfully": downloaded_this_run,
                            "items_attempted_count": len(laws_to_attempt_download),
                            "status": "success"
                            if downloaded_this_run == len(laws_to_attempt_download)
                            or not laws_to_attempt_download
                            else "partial_success",
                        }
                    )
                    echo(
                        f"  🏁 Download para '{origem_id}' concluiu. {downloaded_this_run} PDFs baixados."
                    )
            else:
                message = f"Fase de Download pulada para '{origem_id}'."
                echo(f"⏭️  {message}")
                log_event(
                    {
                        **log_event_origem_base,
                        "event_type": "download_phase_skipped",
                        "message": message,
                    }
                )

            # 3. Upload para Internet Archive
            uploaded_this_run = 0
            upload_skipped_flag = bool(skip_upload and origem_id in skip_upload)
            if not upload_skipped_flag:
                log_event(
                    {
                        **log_event_origem_base,
                        "event_type": "upload_phase_start",
                        "message": "Iniciando fase de upload para o IA.",
                    }
                )
                echo(f"☁️ Fase de Upload para IA para '{origem_id}'...")

                # Selecionar leis para upload:
                # 1. Tem local_pdf_path que existe
                # 2. (Não tem url_pdf_ia OU force_reupload_ia é True)
                laws_to_attempt_upload = []
                for law_meta in (
                    all_discovered_this_run
                ):  # Usar a lista geral, pois o download pode ter acabado de ocorrer
                    if (
                        max_items_upload > 0
                        and len(laws_to_attempt_upload) >= max_items_upload
                    ):  # Respeitar limite
                        break

                    local_path_str = law_meta.get("local_pdf_path")
                    if (
                        local_path_str
                        and Path(local_path_str).exists()
                        and Path(local_path_str).is_file()
                    ):
                        if not law_meta.get("url_pdf_ia") or force_reupload_ia:
                            laws_to_attempt_upload.append(law_meta)

                if not laws_to_attempt_upload:
                    echo("  ✅ Nenhuma lei para upload nesta execução.")
                else:
                    echo(f"  ℹ️  {len(laws_to_attempt_upload)} leis para tentar upload.")
                    for law_meta in laws_to_attempt_upload:  # Corrigido aqui
                        law_id = str(law_meta["id"])
                        pdf_path = Path(str(law_meta["local_pdf_path"]))
                        update_db_fields = {
                            "ultima_tentativa_upload_em": datetime.now().isoformat()
                        }
                        try:
                            # upload_pdf não é async
                            upload_result = publisher.upload_pdf(pdf_path, law_meta)
                            if upload_result and upload_result.get("success"):
                                update_db_fields["url_pdf_ia"] = upload_result.get(
                                    "url"
                                )  # ou 'ia_pdf_url'
                                update_db_fields["ia_item_id"] = upload_result.get(
                                    "ia_item_id"
                                )
                                update_db_fields["url_torrent_ia"] = upload_result.get(
                                    "ia_torrent_url"
                                )
                                update_db_fields["magnet_link_ia"] = upload_result.get(
                                    "ia_magnet_link"
                                )
                                update_db_fields["status_geral"] = (
                                    "publicado_ia_monitor"
                                )
                                update_db_fields["status_upload"] = "sucesso_monitor"
                                uploaded_this_run += 1
                                echo(
                                    f"    ✅ Upload para IA bem-sucedido para {law_id}. Torrent: {upload_result.get('ia_torrent_url')}"
                                )
                            else:
                                update_db_fields["status_upload"] = (
                                    "falha_publisher_monitor"
                                )
                                update_db_fields["erro_upload_info"] = (
                                    upload_result.get("error", "Erro desconhecido")
                                )
                                echo(
                                    style(
                                        f"    ❌ Falha no upload para IA para {law_id}: {upload_result.get('error', 'Erro desconhecido')}",
                                        fg=typer.colors.RED,
                                    )
                                )
                            db.update_lei(law_id, update_db_fields)
                        except Exception as e_upload:
                            update_db_fields["status_upload"] = "erro_monitor"
                            update_db_fields["erro_upload_info"] = str(e_upload)
                            db.update_lei(law_id, update_db_fields)
                            echo(
                                style(
                                    f"    ❌ Erro crítico no upload para IA para {law_id}: {e_upload}",
                                    fg=typer.colors.RED,
                                )
                            )
                            log_event(
                                {
                                    **log_event_origem_base,
                                    "event_type": "ia_upload_error",
                                    "law_id": law_id,
                                    "message": "Erro crítico no upload para IA.",
                                    "error_details": str(e_upload),
                                    "status": "failure",
                                }
                            )

                    log_event(
                        {
                            **log_event_origem_base,
                            "event_type": "upload_phase_complete",
                            "message": f"Fase de upload concluída. {uploaded_this_run} PDFs enviados de {len(laws_to_attempt_upload)} tentativas.",
                            "items_uploaded_successfully": uploaded_this_run,
                            "items_attempted_count": len(laws_to_attempt_upload),
                            "status": "success"
                            if uploaded_this_run == len(laws_to_attempt_upload)
                            or not laws_to_attempt_upload
                            else "partial_success",
                        }
                    )
                    echo(
                        f"  🏁 Upload para IA para '{origem_id}' concluiu. {uploaded_this_run} PDFs enviados."
                    )
            else:
                message = f"Fase de Upload pulada para '{origem_id}'."
                echo(f"⏭️  {message}")
                log_event(
                    {
                        **log_event_origem_base,
                        "event_type": "upload_phase_skipped",
                        "message": message,
                    }
                )

            # ** Atualizar Estado de Rastreamento **
            # O `new_marker_candidate` deve ser o identificador do último item *descoberto*
            # que foi processado com sucesso (ou pelo menos tentado) nas fases de download/upload.
            # Se `all_discovered_this_run` for ordenado do mais antigo para o mais novo,
            # o último item dessa lista que foi tocado (downloaded/uploaded) seria um bom candidato.
            # Ou, se os IDs são sequenciais/ordenáveis, o maior ID descoberto.
            # Por simplicidade, vamos usar o ID do último item em `all_discovered_this_run` se houver itens.
            # Uma lógica mais robusta consideraria o último item *efetivamente salvo/publicado*.

            final_marker_for_this_run = (
                new_marker_candidate  # Mantenha o antigo se nada novo foi processado
            )
            if all_discovered_this_run:  # Apenas se a lista não estiver vazia
                # Tenta pegar um 'id' ou 'data_publicacao' do último item descoberto como marcador.
                # A escolha do que usar como marcador depende da estratégia do conector.
                # Exemplo: usar o 'id' do último item. Se IDs forem como 'sigla-ano-numero', pode funcionar.
                # Se for 'coddoc', pode ser o maior 'coddoc'.
                # Se for baseado em data, a data mais recente.
                # Vamos assumir que o 'id' ou 'data_publicacao' do ultimo item é um bom proximo marcador
                # Esta lógica precisaria ser adaptada para cada tipo de conector/marcador.
                # Exemplo simples: se o último item tiver um ID, use-o.
                last_item_in_batch = all_discovered_this_run[
                    -1
                ]  # O último item da lista processada/considerada

                # Estratégia de marcador: Tentar 'data_publicacao', depois 'id'.
                # O marcador deve ser algo que o conector possa usar para continuar.
                # Se o conector usa datas, 'data_publicacao' é bom. Se usa IDs sequenciais, 'id' (ou parte dele).
                if (
                    "data_publicacao" in last_item_in_batch
                    and last_item_in_batch["data_publicacao"]
                ):
                    final_marker_for_this_run = str(
                        last_item_in_batch["data_publicacao"]
                    )
                elif "id" in last_item_in_batch and last_item_in_batch["id"]:
                    final_marker_for_this_run = str(last_item_in_batch["id"])
                # Se nem ID nem data_publicacao, o marcador não é atualizado de forma útil aqui.
                # O conector específico ou uma convenção de nomenclatura de ID seria necessária.

            # Apenas atualiza o marcador se ele mudou ou se houve itens processados/descobertos.
            # E também registrar a data da execução e quantos itens foram descobertos (brutos).
            # `len(all_discovered_this_run)` aqui reflete os itens retornados pelo conector + existentes (se force)
            # `actual_newly_discovered_by_connector` seria mais preciso para "novos" apenas da descoberta.

            # Condição para atualizar o estado:
            # 1. O marcador mudou Efetivamente.
            # 2. OU (Não houve mudança de marcador MAS houve alguma atividade de download ou upload bem sucedida)
            #    Isso cobre o caso onde reprocessamos o mesmo marcador mas conseguimos baixar/upar algo que antes falhou.
            marker_changed = (
                final_marker_for_this_run != last_processed_marker
                and final_marker_for_this_run is not None
            )
            activity_occured = (
                downloaded_this_run > 0
                or uploaded_this_run > 0
                or (len(newly_inserted_ids_this_run) > 0 and not discovery_skipped_flag)
            )

            if marker_changed or activity_occured:
                db.update_monitor_state(
                    origem=origem_id,
                    marker=final_marker_for_this_run,
                    last_successful_run_at=datetime.now(),
                    # Usar `actual_newly_discovered_by_connector` se disponível e se a descoberta não foi pulada
                    last_items_discovered=actual_newly_discovered_by_connector
                    if not discovery_skipped_flag
                    and "actual_newly_discovered_by_connector" in locals()
                    else 0,
                )
                msg = f"Estado de monitoramento para '{origem_id}' atualizado. Novo marcador: {final_marker_for_this_run}."
                details_state_update = {
                    "new_marker": final_marker_for_this_run,
                    "items_discovered_by_connector_in_run": actual_newly_discovered_by_connector
                    if not discovery_skipped_flag
                    and "actual_newly_discovered_by_connector" in locals()
                    else "N/A (descoberta pulada ou falhou)",
                    "downloaded_in_run": downloaded_this_run,
                    "uploaded_in_run": uploaded_this_run,
                    "newly_inserted_to_db_in_run": len(newly_inserted_ids_this_run),
                }
                echo(f"  💾 {msg}")
                log_event(
                    {
                        **log_event_origem_base,
                        "event_type": "monitor_state_updated",
                        "message": msg,
                        **details_state_update,
                    }
                )
            else:
                msg = f"Nenhuma mudança significativa para atualizar o estado de monitoramento de '{origem_id}'."
                echo(f"  ℹ️  {msg}")
                log_event(
                    {
                        **log_event_origem_base,
                        "event_type": "monitor_state_unchanged",
                        "message": msg,
                    },
                    print_to_console=False,
                )

            log_event(
                {
                    **log_event_origem_base,
                    "event_type": "origem_processing_complete",
                    "message": "Processamento da origem concluído.",
                }
            )
            echo(
                style(
                    f"--- Origem {origem_id} processada ---",
                    bold=True,
                    fg=typer.colors.CYAN,
                )
            )

        # Fim do loop por origens
        log_event(
            {
                "event_type": "monitor_session_complete",
                "message": "Sessão de monitoramento concluída para todas as origens especificadas.",
            }
        )
        echo(
            style(
                "\n🏁 Monitoramento concluído para todas as origens especificadas.",
                bold=True,
                fg=typer.colors.GREEN,
            )
        )

    try:
        asyncio.run(run_monitor_pipeline())
    except Exception as e_main:
        final_error_msg = f"Erro fatal durante a execução do monitor: {e_main}"
        echo(style(f"❌ {final_error_msg}", fg=typer.colors.RED, bold=True))
        log_event(
            {
                "event_type": "monitor_session_error_fatal",
                "message": final_error_msg,
                "error_details": str(e_main),
            },
            print_to_console=False,
        )
        import traceback

        traceback.print_exc()
        raise typer.Exit(1)


# --- Subcomandos para Gerenciamento de Conectores ---
# (código do connector_app e seus comandos permanece o mesmo)
# ... (resto do arquivo)

# --- Subcomandos para Torrents ---
torrent_app = typer.Typer(
    name="torrent", help="🔗 Gerenciar e obter links de torrents para datasets."
)
app.add_typer(torrent_app, name="torrent")


@torrent_app.command("get")
def torrent_get(
    ctx: typer.Context,
    dataset_id: str = typer.Argument(
        ...,
        help="ID do dataset (ex: leis_rondonia_2024, leis_federal_completo). Corresponde ao nome do arquivo .manifest.json sem a extensão.",
    ),
    url: bool = typer.Option(
        False, "--url", help="Exibir a URL do arquivo .torrent em vez do magnet link."
    ),
    show_all: bool = typer.Option(
        False, "--all", help="Exibir todas as informações do manifesto em JSON."
    ),
):
    """🔗 Obtém o magnet link ou URL de torrent de um manifesto de dataset."""

    exports_dir = config.DATA_DIR / "exports"
    manifest_path = exports_dir / f"{dataset_id}.manifest.json"

    if not manifest_path.exists():
        echo(
            style(
                f"❌ Manifesto para o dataset '{dataset_id}' não encontrado em: {manifest_path.resolve()}",
                fg=typer.colors.RED,
            )
        )
        echo(
            "Verifique se o dataset foi exportado e o ID está correto."
        )  # Removido f-string
        raise typer.Exit(1)

    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        echo(
            style(
                f"❌ Erro ao ler ou decodificar o arquivo de manifesto '{manifest_path}': {e}",
                fg=typer.colors.RED,
            )
        )
        raise typer.Exit(1)
    except Exception as e:
        echo(
            style(
                f"❌ Erro inesperado ao abrir o arquivo de manifesto '{manifest_path}': {e}",
                fg=typer.colors.RED,
            )
        )
        raise typer.Exit(1)

    if show_all:
        echo(
            style(f"📄 Conteúdo completo do manifesto para '{dataset_id}':", bold=True)
        )
        echo(json.dumps(manifest_data, indent=2, ensure_ascii=False))
        return

    files = manifest_data.get("files", {})
    link_to_show: Optional[str] = None
    label: str = ""

    if url:
        link_to_show = files.get("torrent")
        label = "URL do Torrent"
    else:
        link_to_show = files.get("magnet")
        label = "Magnet Link"

    if not link_to_show:
        if url and files.get("magnet"):
            link_to_show = files.get("magnet")
            label = "Magnet Link (fallback)"
            echo(
                style(
                    "⚠️ URL do Torrent não encontrada, mostrando Magnet Link como fallback.",
                    fg=typer.colors.YELLOW,
                )
            )  # Removido f-string
        elif not url and files.get("torrent"):
            link_to_show = files.get("torrent")
            label = "URL do Torrent (fallback)"
            echo(
                style(
                    "⚠️ Magnet Link não encontrado, mostrando URL do Torrent como fallback.",
                    fg=typer.colors.YELLOW,
                )
            )  # Removido f-string

        if not link_to_show:
            echo(
                style(
                    f"🤷 Link de torrent/magnet não encontrado no manifesto para '{dataset_id}'.",
                    fg=typer.colors.YELLOW,
                )
            )
            echo(f"Conteúdo da seção 'files' do manifesto: {files}")
            raise typer.Exit(1)

    echo(style(f"🔗 {label} para '{dataset_id}':", bold=True))
    echo(link_to_show)


# Development commands
@dev_app.command("setup")
def dev_setup():
    """🛠️ Configurar ambiente de desenvolvimento (instalar dependências, etc.)."""
    echo("🛠️  Configurando ambiente de desenvolvimento...")

    import subprocess

    try:
        echo("📦 Instalando/sincronizando dependências com 'uv pip sync'...")
        # Assumindo que requirements.txt e requirements-dev.txt existem ou pyproject.toml é usado
        # Se estiver usando pyproject.toml com uv, 'uv sync --dev' pode não ser o comando.
        # 'uv pip sync requirements.txt requirements-dev.txt' é mais explícito se houver esses arquivos.
        # Se for um projeto com pyproject.toml e [project.optional-dependencies], seria 'uv pip install .[dev]'
        # Vamos usar um comando genérico que funcione com pyproject.toml:
        subprocess.run(
            ["uv", "pip", "install", "-e", ".[dev]"], check=True, cwd=PROJECT_ROOT
        )
        echo(style("✅ Dependências instaladas/sincronizadas.", fg=typer.colors.GREEN))

        echo("🔧 Instalando pre-commit hooks...")
        # Garantir que pre-commit está instalado (geralmente via dev dependencies)
        result = subprocess.run(
            ["pre-commit", "install"], capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        if result.returncode == 0:
            echo(style("✅ Pre-commit hooks instalados.", fg=typer.colors.GREEN))
        else:
            # Tentar instalar pre-commit via uv se não encontrado
            echo(
                style(
                    "pre-commit não encontrado, tentando instalar via uv...",
                    fg=typer.colors.YELLOW,
                )
            )
            subprocess.run(
                ["uv", "pip", "install", "pre-commit"], check=True, cwd=PROJECT_ROOT
            )
            result = subprocess.run(
                ["pre-commit", "install"],
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT,
            )
            if result.returncode == 0:
                echo(
                    style(
                        "✅ Pre-commit hooks instalados após instalação do pre-commit.",
                        fg=typer.colors.GREEN,
                    )
                )
            else:
                echo(
                    style(
                        f"⚠️  Falha ao instalar pre-commit hooks. Output: {result.stdout} {result.stderr}",
                        fg=typer.colors.YELLOW,
                    )
                )

        echo(style("🎉 Ambiente de desenvolvimento configurado!", bold=True))

    except subprocess.CalledProcessError as e:
        echo(style(f"❌ Erro durante o setup: {e}", fg=typer.colors.RED))
        echo(f"Comando: {' '.join(e.cmd)}")
        echo(f"Output: {e.output}")
        echo(f"Stderr: {e.stderr}")
        raise typer.Exit(1)
    except FileNotFoundError as e:
        echo(
            style(
                f"❌ Comando não encontrado durante o setup: {e.filename}. Certifique-se de que 'uv' e/ou 'pre-commit' estão no PATH.",
                fg=typer.colors.RED,
            )
        )
        raise typer.Exit(1)


@dev_app.command("lint")
def dev_lint(
    fix: bool = typer.Option(
        False, "--fix", help="Tentar corrigir problemas automaticamente."
    ),
):
    """🔍 Executar linting com Ruff (e opcionalmente corrigir)."""
    cmd = ["ruff", "check", "."]
    if fix:
        cmd.append("--fix")

    echo(f"🔍 Executando '{' '.join(cmd)}'...")
    import subprocess

    try:
        # Usar uv run para garantir que está usando a versão do ambiente virtual
        subprocess.run(
            ["uv", "run", "ruff", "check", ".", *(["--fix"] if fix else [])],
            check=True,
            cwd=PROJECT_ROOT,
        )
        echo(style("✅ Linting passou!", fg=typer.colors.GREEN))
    except subprocess.CalledProcessError:
        echo(
            style(
                "❌ Problemas encontrados no linting. Rode com '--fix' para tentar corrigir ou verifique o output acima.",
                fg=typer.colors.RED,
            )
        )  # Removido f-string
        raise typer.Exit(1)


@dev_app.command("format")
def dev_format(
    check_only: bool = typer.Option(
        False, "--check", help="Não modificar arquivos, apenas verificar formatação."
    ),
):
    """🎨 Formatar código com Ruff."""
    cmd = ["ruff", "format", "."]
    if check_only:
        cmd.append("--check")
        echo("🎨 Verificando formatação do código com Ruff (sem modificar)...")
    else:
        echo("🎨 Formatando código com Ruff...")

    import subprocess

    try:
        subprocess.run(["uv", "run", *cmd], check=True, cwd=PROJECT_ROOT)
        if check_only:
            echo(style("✅ Código está formatado corretamente!", fg=typer.colors.GREEN))
        else:
            echo(style("✅ Código formatado!", fg=typer.colors.GREEN))
    except subprocess.CalledProcessError:
        if check_only:
            echo(
                style(
                    "❌ Código precisa de formatação. Rode sem '--check' para formatar.",
                    fg=typer.colors.RED,
                )
            )
        else:
            echo(style("❌ Erro na formatação com Ruff.", fg=typer.colors.RED))
        raise typer.Exit(1)


@dev_app.command("test")
def dev_test(
    pytest_args: Optional[str] = typer.Option(
        None,
        help="Argumentos adicionais para passar ao pytest (entre aspas). Ex: '-k test_specific'",
    ),
):
    """🧪 Executar testes com pytest."""
    echo("🧪 Executando testes com pytest...")
    import subprocess

    cmd = ["uv", "run", "pytest"]
    if pytest_args and isinstance(
        pytest_args, str
    ):  # Verificar se é string antes de split
        cmd.extend(pytest_args.split())

    try:
        subprocess.run(cmd, check=True, cwd=PROJECT_ROOT)
        echo(style("✅ Todos os testes passaram!", fg=typer.colors.GREEN))
    except subprocess.CalledProcessError:
        echo(style("❌ Alguns testes falharam.", fg=typer.colors.RED))
        raise typer.Exit(1)
    except FileNotFoundError:
        echo(
            style(
                "❌ pytest não encontrado. Verifique se está instalado nas dependências de desenvolvimento.",
                fg=typer.colors.RED,
            )
        )
        raise typer.Exit(1)


@dev_app.command("check-all")
def dev_check_all(ctx: typer.Context):
    """✅ Executar todas as verificações: lint (check), format (check) e tests."""
    echo(
        style(
            "🚀 Executando todas as verificações de qualidade do código...", bold=True
        )
    )

    all_passed = True
    try:
        echo(style("\n--- Verificação 1/3: Linting (ruff check) ---", bold=True))
        ctx.invoke(dev_lint, fix=False)
    except typer.Exit as e:
        if e.exit_code != 0:
            all_passed = False
        echo(style("Linting falhou ou encontrou problemas.", fg=typer.colors.YELLOW))

    try:
        echo(
            style(
                "\n--- Verificação 2/3: Formatação (ruff format --check) ---", bold=True
            )
        )
        ctx.invoke(dev_format, check_only=True)
    except typer.Exit as e:
        if e.exit_code != 0:
            all_passed = False
        echo(style("Verificação de formatação falhou.", fg=typer.colors.YELLOW))

    try:
        echo(style("\n--- Verificação 3/3: Testes (pytest) ---", bold=True))
        ctx.invoke(dev_test)
    except typer.Exit as e:
        if e.exit_code != 0:
            all_passed = False
        echo(style("Testes falharam.", fg=typer.colors.YELLOW))

    if all_passed:
        echo(
            style(
                "\n🎉 Todas as verificações de qualidade passaram!",
                bold=True,
                fg=typer.colors.GREEN,
            )
        )
    else:
        echo(
            style(
                "\n❌ Algumas verificações de qualidade falharam. Veja os detalhes acima.",
                bold=True,
                fg=typer.colors.RED,
            )
        )
        raise typer.Exit(1)


# Nenhuma result_callback global será usada por enquanto,
# confiando no gerenciamento de contexto dos conectores e fechamento explícito.


def run_cli():
    """Ponto de entrada principal para o CLI quando executado como script."""
    try:
        app()
    finally:
        # Tentativa final de fechar conectores, principalmente para casos de exceção não tratada.
        # Isso é complicado por causa do asyncio. Se um comando asyncio falhou,
        # o loop pode estar em um estado inconsistente.
        # Para simplificar, vamos assumir que os comandos individuais devem limpar após si mesmos.
        # Se precisarmos de uma limpeza global robusta aqui, ela precisaria de mais cuidado
        # com o estado do loop de eventos asyncio.
        # Exemplo de tentativa de fechamento assíncrono (pode não funcionar se o loop estiver fechado):
        # try:
        #     asyncio.run(close_all_connectors())
        # except RuntimeError as e:
        #     if "cannot be called when another loop is running" in str(e) or \
        #        "Event loop is closed" in str(e):
        #         # Tentar criar um novo loop para limpeza, se necessário, mas é complexo.
        #         # Ou apenas logar que a limpeza automática falhou.
        #         echo(style("⚠️ Não foi possível fechar conectores automaticamente na saída: loop de evento asyncio problemático.", fg=typer.colors.YELLOW), err=True)
        #     else:
        #         raise e # Re-raise outras RuntimeErrors
        # except Exception as e:
        #     echo(style(f"⚠️ Erro ao tentar fechar conectores na saída final: {e}", fg=typer.colors.YELLOW), err=True)

        # Uma abordagem mais simples é apenas limpar o dicionário.
        # A responsabilidade de fechar os recursos (ex: browser Playwright)
        # deve ser do próprio conector usando __aenter__/__aexit__ ou um método close explícito
        # chamado pelo comando que o utilizou.
        if _LOADED_CONNECTORS:
            echo(
                style(
                    "ℹ️  Lembrete: conectores podem ainda estar ativos. Implemente __aexit__ ou chame close() explicitamente.",
                    fg=typer.colors.BRIGHT_BLACK,
                ),
                err=True,
            )


if __name__ == "__main__":
    run_cli()
