from abc import ABC, abstractmethod
from typing import List, Dict, Any
from pathlib import Path


class BaseConnector(ABC):
    """Interface base para todos os conectores de fontes de leis."""

    # Identificador único para o conector (ex: "rondonia")
    ORIGEM = "base_connector"

    @abstractmethod
    async def discover_laws(self) -> List[Dict[str, Any]]:
        """Descobre novas leis ou atos. Deve retornar uma lista de dicionários com metadados básicos."""
        raise NotImplementedError

    @abstractmethod
    async def download_pdf(
        self, law_metadata: Dict[str, Any], output_path: Path
    ) -> bool:
        """Baixa o PDF de uma lei específica para o caminho fornecido."""
        raise NotImplementedError
