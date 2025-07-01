import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
# import os # Removido

# Tentativa de importar config para LOGS_DIR. Se não estiver disponível (ex: teste unitário), usar um fallback.
try:
    from config import LOGS_DIR
except ImportError:
    # Fallback para o caso de config.py não ser acessível ou LOGS_DIR não definido.
    # Isso pode acontecer em contextos de teste ou se a estrutura do projeto mudar.
    PROJECT_ROOT_FALLBACK = Path(__file__).resolve().parent.parent
    LOGS_DIR = PROJECT_ROOT_FALLBACK / "logs_fallback"
    print(f"AVISO: config.LOGS_DIR não encontrado. Usando fallback: {LOGS_DIR}")

# Garantir que o diretório de logs exista no momento da importação do módulo
LOGS_DIR.mkdir(parents=True, exist_ok=True)


class StructuredLogger:
    """
    Logger para registrar eventos estruturados em arquivos JSONL.
    Cada instância pode ser configurada para um comando ou processo específico.
    """

    def __init__(self, command_name: str, log_dir: Optional[Path] = None):
        self.command_name = command_name
        self.log_dir = log_dir or LOGS_DIR
        self.log_file_path = self._get_log_file_path()

        # Informação da sessão de logging (pode ser útil para agrupar logs de uma execução)
        self.session_id = datetime.now().strftime("%Y%m%d%H%M%S%f")

    def _get_log_file_path(self) -> Path:
        """Determina o caminho do arquivo de log para o dia atual."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"{self.command_name}_{date_str}.jsonl"
        return self.log_dir / filename

    def _write_log(self, event_data: Dict[str, Any]):
        """Escreve o evento de log no arquivo."""
        try:
            # Garante que o diretório de log existe (pode ter sido criado por outro processo/logger)
            self.log_dir.mkdir(parents=True, exist_ok=True)

            with open(self.log_file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event_data, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            # Fallback crítico: se não conseguir escrever no arquivo, printar no stderr
            print(
                f"CRITICAL_LOGGING_ERROR: Failed to write to log file {self.log_file_path}. Error: {e}",
                file=sys.stderr,
            )
            print(f"CRITICAL_LOGGING_ERROR_DATA: {event_data}", file=sys.stderr)

    def log(self, event_type: str, message: Optional[str] = None, **kwargs: Any):
        """
        Registra um evento de log.

        Args:
            event_type (str): Tipo do evento (ex: "process_start", "item_processed", "error").
            message (Optional[str]): Mensagem descritiva do evento.
            **kwargs: Dados adicionais a serem incluídos no log.
        """
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "session_id": self.session_id,
            "command": self.command_name,
            "event_type": event_type,
        }
        if message:
            log_entry["message"] = message

        # Adicionar quaisquer outros dados fornecidos
        log_entry.update(kwargs)

        self._write_log(log_entry)

    # Métodos de conveniência (opcional, mas podem ser úteis)
    def info(self, message: str, **kwargs: Any):
        self.log(event_type="info", message=message, **kwargs)

    def error(self, message: str, error_details: Optional[str] = None, **kwargs: Any):
        log_data = {"message": message, **kwargs}
        if error_details:
            log_data["error_details"] = error_details
        self.log(event_type="error", **log_data)

    def warning(self, message: str, **kwargs: Any):
        self.log(event_type="warning", message=message, **kwargs)

    def critical(
        self, message: str, error_details: Optional[str] = None, **kwargs: Any
    ):
        log_data = {"message": message, **kwargs}
        if error_details:
            log_data["error_details"] = error_details
        self.log(event_type="critical", **log_data)


# Exemplo de como usar (não será executado quando importado):
if __name__ == "__main__":
    import sys  # Adicionado para o fallback logging

    # Exemplo de uso do logger
    discovery_logger = StructuredLogger(command_name="discover_example")
    discovery_logger.info(
        "Iniciando processo de descoberta.", detalhes_da_config="config_xyz"
    )

    try:
        # Simula uma operação
        num_itens = 10
        for i in range(num_itens):
            if i == 5:
                raise ValueError("Erro simulado no item 5")
            discovery_logger.log(
                event_type="item_discovered",
                message=f"Item {i + 1} descoberto.",
                item_id=f"item_{i + 1}",
                origem="exemplo_origem",
            )
        discovery_logger.info(f"Descoberta concluída. {num_itens} itens processados.")
    except ValueError as e:
        discovery_logger.error(
            message="Erro durante a descoberta.",
            error_details=str(e),
            item_problematico="item_5",
        )

    print(
        f"Logs de exemplo foram escritos em: {discovery_logger.log_file_path.resolve()}"
    )

    test_logger = StructuredLogger("test_command")
    test_logger.log(
        "test_event", message="Este é um teste.", data={"chave": "valor", "numero": 123}
    )
    print(f"Log de teste escrito em: {test_logger.log_file_path.resolve()}")
