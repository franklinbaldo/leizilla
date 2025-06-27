"""
Interface de linha de comando para Leizilla.

Fornece comandos para crawling, storage e publicação.
"""

import asyncio
import argparse
import sys
from pathlib import Path
from typing import Optional

import config
import crawler
import storage
import publisher


async def cmd_discover(args) -> None:
    """Comando para descobrir leis."""
    print(f"🔍 Descobrindo leis de {args.origem} (ano: {args.year or 'todos'})")
    
    if args.origem == 'rondonia':
        laws = await crawler.discover_laws_rondonia(start_year=args.year or 2020)
        
        # Salvar no banco
        db = storage.storage
        
        for law in laws:
            try:
                db.insert_lei(law)
                print(f"💾 Salva: {law['id']}")
            except Exception as e:
                print(f"❌ Erro ao salvar {law.get('id', 'N/A')}: {e}")
        
        print(f"✅ Descobertas e salvas {len(laws)} leis")
    
    else:
        print(f"❌ Origem '{args.origem}' ainda não suportada")


async def cmd_download(args) -> None:
    """Comando para download de PDFs."""
    print(f"📥 Baixando PDFs...")
    
    # Buscar leis no banco que ainda não foram baixadas
    db = storage.storage
    laws = db.search_leis(origem=args.origem, limit=args.limit)
    
    downloaded = 0
    for law in laws:
        if not law.get('url_original'):
            continue
        
        filename = f"{law['id']}.pdf"
        success = await crawler.download_lei_pdf(law['url_original'], filename)
        
        if success:
            downloaded += 1
            print(f"📄 Baixado: {law['id']}")
        else:
            print(f"❌ Falha: {law['id']}")
    
    print(f"✅ Downloads concluídos: {downloaded}/{len(laws)}")


def cmd_upload(args) -> None:
    """Comando para upload para Internet Archive."""
    print(f"☁️  Fazendo upload para IA...")
    
    # Buscar PDFs baixados
    temp_dir = config.TEMP_DIR
    pdf_files = list(temp_dir.glob("*.pdf"))
    
    if not pdf_files:
        print("❌ Nenhum PDF encontrado em data/temp/")
        return
    
    db = storage.storage
    uploaded = 0
    
    for pdf_path in pdf_files[:args.limit]:
        # Extrair ID da lei do nome do arquivo
        lei_id = pdf_path.stem
        lei_data = db.get_lei(lei_id)
        
        if not lei_data:
            print(f"❌ Metadados não encontrados para: {lei_id}")
            continue
        
        try:
            result = publisher.upload_lei_to_ia(pdf_path, lei_data)
            
            if result.get('success'):
                # Atualizar banco com URLs do IA
                lei_data.update({
                    'url_pdf_ia': result.get('ia_pdf_url'),
                    'metadados': {
                        **lei_data.get('metadados', {}),
                        'ia_identifier': result.get('identifier'),
                        'ia_uploaded_at': result.get('upload_timestamp')
                    }
                })
                db.insert_lei(lei_data)
                
                uploaded += 1
                print(f"☁️  Uploaded: {lei_id}")
            else:
                print(f"❌ Falha upload: {lei_id} - {result.get('error')}")
        
        except Exception as e:
            print(f"❌ Erro upload {lei_id}: {e}")
    
    print(f"✅ Uploads concluídos: {uploaded}/{len(pdf_files[:args.limit])}")


def cmd_export(args) -> None:
    """Comando para exportar datasets."""
    print(f"📦 Exportando dataset de {args.origem}...")
    
    try:
        result = publisher.export_and_upload_dataset(
            origem=args.origem,
            ano=args.year
        )
        
        print(f"📁 Arquivo local: {result['export_path']}")
        
        if result['upload_result'].get('success'):
            print(f"☁️  Upload IA: {result['upload_result'].get('ia_detail_url')}")
        else:
            print(f"❌ Falha upload: {result['upload_result'].get('error')}")
    
    except Exception as e:
        print(f"❌ Erro na exportação: {e}")


def cmd_stats(args) -> None:
    """Comando para mostrar estatísticas."""
    print("📊 Estatísticas do banco de dados:")
    
    db = storage.storage
    stats = db.get_stats()
    
    print(f"\n📋 Total de leis: {stats['total_leis']}")
    
    print("\n🌍 Por origem:")
    for origem, count in stats['por_origem'].items():
        print(f"  {origem}: {count}")
    
    print("\n📅 Por ano (últimos 10):")
    for ano, count in stats['por_ano'].items():
        print(f"  {ano}: {count}")


def cmd_search(args) -> None:
    """Comando para buscar leis."""
    print(f"🔍 Buscando leis...")
    
    db = storage.storage
    results = db.search_leis(
        origem=args.origem,
        ano=args.year,
        texto=args.text,
        limit=args.limit
    )
    
    print(f"\n📋 Encontradas {len(results)} leis:")
    
    for lei in results:
        print(f"  {lei['id']} - {lei['titulo'][:60]}{'...' if len(lei['titulo']) > 60 else ''}")
        print(f"    Ano: {lei['ano']}, Tipo: {lei.get('tipo_lei', 'N/A')}")


def main() -> None:
    """Função principal da CLI."""
    parser = argparse.ArgumentParser(
        description="Leizilla - Indexador de leis brasileiras"
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Comandos disponíveis')
    
    # Comando discover
    discover_parser = subparsers.add_parser('discover', help='Descobrir leis')
    discover_parser.add_argument('--origem', default='rondonia', help='Origem das leis')
    discover_parser.add_argument('--year', type=int, help='Ano específico')
    
    # Comando download
    download_parser = subparsers.add_parser('download', help='Baixar PDFs')
    download_parser.add_argument('--origem', default='rondonia', help='Origem das leis')
    download_parser.add_argument('--limit', type=int, default=10, help='Limite de downloads')
    
    # Comando upload
    upload_parser = subparsers.add_parser('upload', help='Upload para IA')
    upload_parser.add_argument('--limit', type=int, default=10, help='Limite de uploads')
    
    # Comando export
    export_parser = subparsers.add_parser('export', help='Exportar dataset')
    export_parser.add_argument('--origem', default='rondonia', help='Origem das leis')
    export_parser.add_argument('--year', type=int, help='Ano específico')
    
    # Comando stats
    subparsers.add_parser('stats', help='Mostrar estatísticas')
    
    # Comando search
    search_parser = subparsers.add_parser('search', help='Buscar leis')
    search_parser.add_argument('--origem', help='Filtrar por origem')
    search_parser.add_argument('--year', type=int, help='Filtrar por ano')
    search_parser.add_argument('--text', help='Buscar por texto')
    search_parser.add_argument('--limit', type=int, default=20, help='Limite de resultados')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Executar comando
    try:
        if args.command == 'discover':
            asyncio.run(cmd_discover(args))
        elif args.command == 'download':
            asyncio.run(cmd_download(args))
        elif args.command == 'upload':
            cmd_upload(args)
        elif args.command == 'export':
            cmd_export(args)
        elif args.command == 'stats':
            cmd_stats(args)
        elif args.command == 'search':
            cmd_search(args)
        else:
            print(f"❌ Comando desconhecido: {args.command}")
            sys.exit(1)
    
    except KeyboardInterrupt:
        print("\n👋 Interrompido pelo usuário")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Erro: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()