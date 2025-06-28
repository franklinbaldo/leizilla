#!/usr/bin/env python3
"""
Leizilla CLI - Interface de linha de comando para o sistema de indexação de leis.
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

import typer
from typer import echo, style

# Configure app
app = typer.Typer(
    name="leizilla",
    help="🦖 O dinossauro que devora PDFs jurídicos e cospe dados abertos",
    add_completion=False,
)

# Create subcommands
dev_app = typer.Typer(name="dev", help="🛠️ Comandos de desenvolvimento")
app.add_typer(dev_app, name="dev")


# Main CLI commands
@app.command("discover")
def cmd_discover(
    origem: str = typer.Option("rondonia", help="Origem das leis (rondonia, acre, etc)"),
    year: Optional[int] = typer.Option(None, help="Ano específico para buscar"),
):
    """🔍 Descobrir leis nos portais oficiais"""
    echo(f"🔍 Descobrindo leis de {origem}" + (f" do ano {year}" if year else ""))
    
    try:
        from crawler import LeisCrawler
        from storage import DatabaseManager
        
        async def run_discover():
            crawler = LeisCrawler()
            db = DatabaseManager()
            
            if origem == "rondonia":
                laws = await crawler.discover_rondonia_laws(
                    start_year=year or 2020,
                    end_year=year if year else None
                )
                
                for law in laws:
                    db.insert_lei(law)
                    echo(f"✅ Salvou: {law.get('titulo', 'N/A')}")
                
                echo(f"🎉 Descobriu {len(laws)} leis de {origem}")
            else:
                echo(f"❌ Origem '{origem}' ainda não implementada")
                raise typer.Exit(1)
        
        asyncio.run(run_discover())
        
    except Exception as e:
        echo(f"❌ Erro: {e}")
        raise typer.Exit(1)


@app.command("download")
def cmd_download(
    origem: str = typer.Option("rondonia", help="Origem das leis"),
    limit: int = typer.Option(10, help="Limite de downloads"),
):
    """📥 Baixar PDFs das leis descobertas"""
    echo(f"📥 Baixando até {limit} PDFs de {origem}")
    
    try:
        from crawler import LeisCrawler
        from storage import DatabaseManager
        import tempfile
        
        async def run_download():
            crawler = LeisCrawler()
            db = DatabaseManager()
            
            # Get laws without PDFs
            laws = db.search_leis(origem=origem, limit=limit)
            laws_to_download = [law for law in laws if not law.get('url_pdf_ia')]
            
            if not laws_to_download:
                echo("✅ Todos os PDFs já foram baixados")
                return
            
            downloaded = 0
            for law in laws_to_download[:limit]:
                if not law.get('url_original'):
                    continue
                    
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                    success = await crawler.download_pdf(law['url_original'], Path(tmp.name))
                    if success:
                        # Update database with local path for future upload
                        db.update_lei(law['id'], {'local_pdf_path': tmp.name})
                        downloaded += 1
                        echo(f"✅ Baixou: {law.get('titulo', 'N/A')}")
                    else:
                        echo(f"❌ Falha: {law.get('titulo', 'N/A')}")
            
            echo(f"🎉 Baixou {downloaded} PDFs")
        
        asyncio.run(run_download())
        
    except Exception as e:
        echo(f"❌ Erro: {e}")
        raise typer.Exit(1)


@app.command("upload")
def cmd_upload(
    limit: int = typer.Option(5, help="Limite de uploads"),
):
    """☁️ Upload PDFs para Internet Archive"""
    echo(f"☁️ Fazendo upload de até {limit} PDFs para IA")
    
    try:
        from publisher import InternetArchivePublisher
        from storage import DatabaseManager
        
        publisher = InternetArchivePublisher()
        db = DatabaseManager()
        
        # Get laws with local PDFs but no IA URL
        laws = db.search_leis(limit=limit * 2)  # Get more to filter
        laws_to_upload = [
            law for law in laws 
            if law.get('local_pdf_path') and not law.get('url_pdf_ia')
        ]
        
        if not laws_to_upload:
            echo("✅ Todos os PDFs já foram enviados para IA")
            return
        
        uploaded = 0
        for law in laws_to_upload[:limit]:
            try:
                pdf_path = Path(law['local_pdf_path'])
                if not pdf_path.exists():
                    continue
                
                result = publisher.upload_pdf(pdf_path, law)
                if result.get('success'):
                    # Update database with IA URL
                    db.update_lei(law['id'], {'url_pdf_ia': result['url']})
                    uploaded += 1
                    echo(f"✅ Upload: {law.get('titulo', 'N/A')}")
                else:
                    echo(f"❌ Falha: {law.get('titulo', 'N/A')}")
                    
            except Exception as e:
                echo(f"❌ Erro em {law.get('titulo', 'N/A')}: {e}")
        
        echo(f"🎉 Fez upload de {uploaded} PDFs")
        
    except Exception as e:
        echo(f"❌ Erro: {e}")
        raise typer.Exit(1)


@app.command("export")
def cmd_export(
    origem: str = typer.Option("rondonia", help="Origem das leis"),
    year: Optional[int] = typer.Option(None, help="Ano específico"),
    format: str = typer.Option("parquet", help="Formato de exportação (parquet, jsonl)"),
):
    """📦 Exportar dataset de leis"""
    echo(f"📦 Exportando dataset de {origem}" + (f" do ano {year}" if year else ""))
    
    try:
        from publisher import InternetArchivePublisher
        from pathlib import Path
        
        publisher = InternetArchivePublisher()
        output_dir = Path("data/exports")
        output_dir.mkdir(exist_ok=True)
        
        if format == "parquet":
            output_path = publisher.export_dataset_parquet(origem, output_dir, year)
            echo(f"✅ Dataset exportado: {output_path}")
        else:
            echo(f"❌ Formato '{format}' não implementado ainda")
            raise typer.Exit(1)
        
    except Exception as e:
        echo(f"❌ Erro: {e}")
        raise typer.Exit(1)


@app.command("search")
def cmd_search(
    text: Optional[str] = typer.Option(None, help="Buscar por texto"),
    origem: Optional[str] = typer.Option(None, help="Filtrar por origem"),
    year: Optional[int] = typer.Option(None, help="Filtrar por ano"),
    limit: int = typer.Option(20, help="Limite de resultados"),
):
    """🔍 Buscar leis no banco de dados"""
    echo("🔍 Buscando leis...")
    
    try:
        from storage import DatabaseManager
        
        db = DatabaseManager()
        laws = db.search_leis(
            origem=origem,
            ano=year,
            texto=text,
            limit=limit
        )
        
        if not laws:
            echo("📭 Nenhuma lei encontrada")
            return
        
        echo(f"📋 Encontradas {len(laws)} leis:")
        for law in laws:
            title = law.get('titulo', 'N/A')
            year_str = f"({law.get('ano', 'N/A')})" if law.get('ano') else ""
            origem_str = law.get('origem', 'N/A')
            echo(f"  • {title} {year_str} - {origem_str}")
        
    except Exception as e:
        echo(f"❌ Erro: {e}")
        raise typer.Exit(1)


@app.command("stats")
def cmd_stats():
    """📊 Mostrar estatísticas do banco de dados"""
    echo("📊 Estatísticas do banco:")
    
    try:
        from storage import DatabaseManager
        
        db = DatabaseManager()
        stats = db.get_stats()
        
        echo(f"  📚 Total de leis: {stats.get('total', 0)}")
        echo(f"  🏛️ Por origem:")
        for origem, count in stats.get('por_origem', {}).items():
            echo(f"    • {origem}: {count}")
        
        echo(f"  📅 Por ano:")
        for year, count in sorted(stats.get('por_ano', {}).items()):
            echo(f"    • {year}: {count}")
            
    except Exception as e:
        echo(f"❌ Erro: {e}")
        raise typer.Exit(1)


@app.command("pipeline")
def cmd_pipeline(
    origem: str = typer.Option("rondonia", help="Origem das leis"),
    year: Optional[int] = typer.Option(None, help="Ano específico"),
    limit: int = typer.Option(5, help="Limite por etapa"),
):
    """🚀 Executar pipeline completo"""
    echo(f"🚀 Executando pipeline completo para {origem}")
    
    try:
        # Run each step
        echo("\n📝 Etapa 1/4: Descobrir leis")
        cmd_discover(origem=origem, year=year)
        
        echo("\n📝 Etapa 2/4: Baixar PDFs")  
        cmd_download(origem=origem, limit=limit)
        
        echo("\n📝 Etapa 3/4: Upload para IA")
        cmd_upload(limit=limit)
        
        echo("\n📝 Etapa 4/4: Exportar dataset")
        cmd_export(origem=origem, year=year)
        
        echo("\n✅ Pipeline concluído com sucesso!")
        
    except Exception as e:
        echo(f"❌ Pipeline falhou: {e}")
        raise typer.Exit(1)


# Development commands
@dev_app.command("setup")
def dev_setup():
    """🛠️ Configurar ambiente de desenvolvimento"""
    echo("🛠️ Configurando ambiente...")
    
    import subprocess
    
    try:
        # Install dependencies
        subprocess.run(["uv", "sync", "--dev"], check=True)
        echo("✅ Dependências instaladas")
        
        # Install pre-commit hooks
        result = subprocess.run(["uv", "run", "pre-commit", "install"], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            echo("✅ Pre-commit hooks instalados")
        else:
            echo("⚠️ Pre-commit não disponível")
        
        echo("🎉 Setup concluído!")
        
    except subprocess.CalledProcessError as e:
        echo(f"❌ Erro no setup: {e}")
        raise typer.Exit(1)


@dev_app.command("lint")
def dev_lint():
    """🔍 Executar linting com ruff"""
    echo("🔍 Executando ruff check...")
    
    import subprocess
    try:
        result = subprocess.run(["uv", "run", "ruff", "check", "."], check=True)
        echo("✅ Linting passou!")
    except subprocess.CalledProcessError:
        echo("❌ Problemas encontrados no linting")
        raise typer.Exit(1)


@dev_app.command("format")
def dev_format():
    """🎨 Formatar código com ruff"""
    echo("🎨 Formatando código...")
    
    import subprocess
    try:
        subprocess.run(["uv", "run", "ruff", "format", "."], check=True)
        echo("✅ Código formatado!")
    except subprocess.CalledProcessError:
        echo("❌ Erro na formatação")
        raise typer.Exit(1)


@dev_app.command("test")
def dev_test():
    """🧪 Executar testes com pytest"""
    echo("🧪 Executando testes...")
    
    import subprocess
    try:
        subprocess.run(["uv", "run", "pytest"], check=True)
        echo("✅ Testes passaram!")
    except subprocess.CalledProcessError:
        echo("❌ Testes falharam")
        raise typer.Exit(1)


@dev_app.command("check")
def dev_check():
    """✅ Executar todas as verificações"""
    echo("✅ Executando todas as verificações...")
    
    checks = [
        ("Linting", dev_lint),
        ("Formatação", lambda: dev_format_check()),
        ("Testes", dev_test),
    ]
    
    failed = []
    for name, check_func in checks:
        try:
            check_func()
        except typer.Exit:
            failed.append(name)
    
    if failed:
        echo(f"❌ Verificações falharam: {', '.join(failed)}")
        raise typer.Exit(1)
    else:
        echo("🎉 Todas as verificações passaram!")


def dev_format_check():
    """Check formatting without applying changes"""
    import subprocess
    try:
        subprocess.run(["uv", "run", "ruff", "format", ".", "--check"], check=True)
    except subprocess.CalledProcessError:
        raise typer.Exit(1)


def main():
    """Entry point para o CLI"""
    app()


if __name__ == "__main__":
    main()