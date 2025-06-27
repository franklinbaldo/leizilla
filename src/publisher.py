"""
Módulo de publicação para Internet Archive.

Gerencia upload de PDFs para IA e exportação de datasets.
"""

import subprocess
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
import tempfile
import hashlib

import config
import storage


class InternetArchivePublisher:
    """Gerenciador de publicação no Internet Archive."""
    
    def __init__(self):
        self.access_key = config.IA_ACCESS_KEY
        self.secret_key = config.IA_SECRET_KEY
        
        if not self.access_key or not self.secret_key:
            raise ValueError("IA_ACCESS_KEY e IA_SECRET_KEY são obrigatórias")
    
    def upload_pdf(self, 
                   pdf_path: Path, 
                   lei_metadata: Dict[str, Any],
                   collection: str = "leizilla") -> Dict[str, Any]:
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
            result = self._execute_ia_upload(pdf_path, identifier, ia_metadata)
            
            if result['success']:
                # URLs resultantes
                base_url = f"https://archive.org/details/{identifier}"
                pdf_url = f"https://archive.org/download/{identifier}/{pdf_path.name}"
                
                upload_result = {
                    'identifier': identifier,
                    'ia_detail_url': base_url,
                    'ia_pdf_url': pdf_url,
                    'ia_ocr_url': f"https://archive.org/download/{identifier}/{pdf_path.stem}_djvu.txt",
                    'upload_timestamp': datetime.now().isoformat(),
                    'success': True
                }
                
                print(f"✅ Upload IA bem-sucedido: {identifier}")
                return upload_result
            
            else:
                print(f"❌ Falha no upload IA: {result.get('error', 'Erro desconhecido')}")
                return {'success': False, 'error': result.get('error')}
        
        except Exception as e:
            print(f"❌ Erro no upload IA: {e}")
            return {'success': False, 'error': str(e)}
    
    def _generate_ia_identifier(self, lei_metadata: Dict[str, Any]) -> str:
        """Gera identificador único para o IA."""
        # Formato: leizilla-{origem}-{tipo}-{ano}-{numero}
        origem = lei_metadata.get('origem', 'brasil')
        tipo = lei_metadata.get('tipo_lei', 'lei')
        ano = lei_metadata.get('ano', datetime.now().year)
        numero = lei_metadata.get('numero', 'unknown')
        
        # Sanitizar para identificador válido do IA
        identifier = f"leizilla-{origem}-{tipo}-{ano}-{numero}"
        identifier = identifier.lower().replace(' ', '-').replace('_', '-')
        
        # Garantir que é único adicionando hash se necessário
        if len(identifier) > 80:  # Limite do IA
            content_hash = hashlib.md5(str(lei_metadata).encode()).hexdigest()[:8]
            identifier = f"leizilla-{origem}-{ano}-{content_hash}"
        
        return identifier
    
    def _prepare_ia_metadata(self, 
                           lei_metadata: Dict[str, Any], 
                           collection: str) -> Dict[str, str]:
        """Prepara metadados para upload no IA."""
        metadata = {
            'collection': collection,
            'mediatype': 'texts',
            'title': lei_metadata.get('titulo', 'Lei Brasileira'),
            'creator': 'Leizilla Project',
            'subject': f"lei; brasil; {lei_metadata.get('origem', '')}; jurídico",
            'description': f"Lei brasileira indexada pelo projeto Leizilla. "
                          f"Origem: {lei_metadata.get('origem', 'N/A')}, "
                          f"Ano: {lei_metadata.get('ano', 'N/A')}",
            'date': str(lei_metadata.get('ano', datetime.now().year)),
            'language': 'Portuguese',
            'licenseurl': 'https://creativecommons.org/publicdomain/mark/1.0/',
            'source': lei_metadata.get('url_original', ''),
            
            # Metadados específicos do Leizilla
            'leizilla-origem': lei_metadata.get('origem', ''),
            'leizilla-tipo': lei_metadata.get('tipo_lei', ''),
            'leizilla-numero': str(lei_metadata.get('numero', '')),
            'leizilla-ano': str(lei_metadata.get('ano', '')),
            'leizilla-version': '1.0'
        }
        
        # Adicionar metadados extras se existirem
        if 'metadados' in lei_metadata and isinstance(lei_metadata['metadados'], dict):
            for key, value in lei_metadata['metadados'].items():
                if isinstance(value, (str, int, float)):
                    metadata[f'leizilla-{key}'] = str(value)
        
        return metadata
    
    def _execute_ia_upload(self, 
                          pdf_path: Path, 
                          identifier: str, 
                          metadata: Dict[str, str]) -> Dict[str, Any]:
        """Executa upload via comando ia."""
        
        # Preparar comando ia
        cmd = [
            'ia', 'upload', identifier, str(pdf_path),
            '--checksum'  # Verificar integridade
        ]
        
        # Adicionar metadados
        for key, value in metadata.items():
            cmd.extend(['--metadata', f'{key}:{value}'])
        
        # Configurar ambiente com credenciais
        env = {
            'IA_ACCESS_KEY': self.access_key,
            'IA_SECRET_KEY': self.secret_key
        }
        
        try:
            # Executar comando
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutos timeout
            )
            
            if result.returncode == 0:
                return {'success': True, 'output': result.stdout}
            else:
                return {
                    'success': False,
                    'error': result.stderr or result.stdout,
                    'returncode': result.returncode
                }
        
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'Upload timeout (5 minutos)'}
        except FileNotFoundError:
            return {'success': False, 'error': 'Comando "ia" não encontrado. Instale: pip install internetarchive'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def export_dataset_parquet(self, 
                             origem: str,
                             output_dir: Path,
                             ano: Optional[int] = None) -> Path:
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
    
    def upload_dataset(self, 
                      parquet_path: Path,
                      origem: str,
                      ano: Optional[int] = None) -> Dict[str, Any]:
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
            'titulo': f'Dataset de Leis - {origem.title()}' + (f' ({ano})' if ano else ''),
            'origem': origem,
            'tipo_lei': 'dataset',
            'ano': ano or datetime.now().year,
            'numero': 'dataset',
            'metadados': {
                'tipo': 'dataset_parquet',
                'formato': 'parquet',
                'origem_dados': origem,
                'ano_dados': ano,
                'gerado_em': datetime.now().isoformat(),
                'versao_leizilla': '1.0'
            }
        }
        
        return self.upload_pdf(parquet_path, dataset_metadata, collection='leizilla-datasets')


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
    
    return {
        'export_path': str(parquet_path),
        'upload_result': upload_result
    }