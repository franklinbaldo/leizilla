"""Testes para leizilla.cli.main — configuração de logging da CLI.

Produção 2026-09-25: nada no projeto chamava `logging.basicConfig`, então
todo `logger.info`/`logger.debug` em discovery.py/parser.py/publisher.py era
descartado silenciosamente (o "last resort handler" do Python só mostra
WARNING+), inclusive em CI — tornando o diagnóstico de falhas de discovery
(ex.: issue #262) impossível de investigar a partir dos logs do próprio run.
"""

from unittest.mock import patch

from leizilla.cli import main


def test_main_configures_root_logging_before_running_app():
    with (
        patch("leizilla.cli.logging.basicConfig") as mock_basic_config,
        patch("leizilla.cli.app") as mock_app,
        patch.dict("os.environ", {}, clear=False),
    ):
        import os

        os.environ.pop("LOG_LEVEL", None)
        main()

    mock_basic_config.assert_called_once()
    assert mock_basic_config.call_args.kwargs["level"] == "INFO"
    mock_app.assert_called_once()


def test_main_respects_log_level_env_override():
    with (
        patch("leizilla.cli.logging.basicConfig") as mock_basic_config,
        patch("leizilla.cli.app"),
        patch.dict("os.environ", {"LOG_LEVEL": "debug"}, clear=False),
    ):
        main()

    assert mock_basic_config.call_args.kwargs["level"] == "DEBUG"
