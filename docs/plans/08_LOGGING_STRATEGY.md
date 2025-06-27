# Estratégia de Logging Detalhado

## Objetivo

Implementar um sistema de logging abrangente e estruturado no Projeto XYZ para facilitar o debugging durante o desenvolvimento, o monitoramento do comportamento da aplicação em produção, a auditoria de eventos importantes e a análise de erros e performance.

## Por que Logging é Importante?

*   **Debugging:** Logs fornecem um rastro da execução do programa, ajudando a identificar onde e por que os erros ocorrem.
*   **Monitoramento:** Acompanhar a saúde da aplicação, detectar problemas proativamente e entender como o sistema está sendo usado.
*   **Auditoria:** Registrar eventos críticos de segurança ou de negócio para conformidade e análise posterior.
*   **Análise de Erros:** Coletar informações detalhadas sobre exceções e falhas para diagnóstico rápido.
*   **Análise de Performance:** Registrar tempos de execução de operações críticas para identificar gargalos.
*   **Suporte ao Usuário:** Logs podem ajudar a entender o contexto de um problema reportado por um usuário.

## Princípios de Logging

*   **Estruturado:** Usar um formato consistente (ex: JSON) para que os logs possam ser facilmente parseados, pesquisados e analisados por ferramentas.
*   **Níveis de Log:** Utilizar diferentes níveis de severidade (DEBUG, INFO, WARNING, ERROR, CRITICAL) para categorizar as mensagens.
*   **Contextual:** Incluir informações contextuais relevantes em cada mensagem de log (ex: ID do usuário, ID da requisição, nome do módulo/função).
*   **Significativo:** Evitar logs excessivamente verbosos ou inúteis. Cada log deve ter um propósito.
*   **Seguro:** Não registrar informações sensíveis (senhas, chaves de API, dados pessoais) em plain text. Implementar mascaramento ou omitir esses dados.
*   **Performático:** A escrita de logs não deve impactar significativamente a performance da aplicação. Usar logging assíncrono se necessário.
*   **Configurável:** Permitir a configuração dos níveis de log e dos destinos (outputs) em diferentes ambientes (desenvolvimento, staging, produção) sem necessidade de alterar o código.

## Níveis de Log (Severidade)

*   **DEBUG:** Informações detalhadas, úteis apenas para diagnóstico durante o desenvolvimento (ex: valores de variáveis, fluxo de controle detalhado). Deve ser desabilitado em produção por padrão.
*   **INFO:** Mensagens informativas sobre o progresso normal da aplicação (ex: serviço iniciado, requisição recebida, tarefa concluída com sucesso).
*   **WARNING:** Indica que algo inesperado aconteceu ou um problema potencial que não impede o funcionamento atual da aplicação, mas pode causar problemas futuros (ex: uso de API obsoleta, falha ao conectar a um serviço secundário que tem fallback).
*   **ERROR:** Um erro ocorreu que impediu a execução de uma operação específica, mas a aplicação como um todo continua funcionando (ex: falha ao processar uma requisição específica devido a dados inválidos, exceção não tratada em uma parte não crítica).
*   **CRITICAL (ou FATAL):** Um erro grave ocorreu que impede o funcionamento da aplicação ou de um componente essencial (ex: falha ao conectar ao banco de dados principal, falta de recursos críticos). Geralmente requer intervenção imediata.

## O Que Logar?

*   **Ciclo de Vida da Aplicação:** Início e parada de serviços, carregamento de configuração.
*   **Requisições e Respostas (APIs/Serviços Web):**
    *   Método HTTP, URL, IP de origem.
    *   Cabeçalhos importantes (ex: `User-Agent`, `Content-Type`).
    *   Corpo da requisição (parcialmente, com dados sensíveis mascarados).
    *   Código de status da resposta, tempo de processamento.
    *   ID de Correlação (para rastrear uma requisição através de múltiplos serviços).
*   **Eventos de Negócio Importantes:**
    *   Criação/atualização/deleção de entidades principais (ex: usuário criado, pedido processado).
    *   Transações financeiras (com devida segurança).
    *   Mudanças de estado significativas.
*   **Erros e Exceções:**
    *   Stack traces completos.
    *   Contexto da requisição ou operação que causou o erro.
    *   Valores de parâmetros relevantes.
*   **Eventos de Segurança:**
    *   Tentativas de login (sucesso e falha).
    *   Acesso a recursos protegidos.
    *   Mudanças de permissão.
    *   Potenciais atividades suspeitas (ex: múltiplas falhas de login).
*   **Chamadas a Serviços Externos:**
    *   Qual serviço foi chamado, parâmetros.
    *   Sucesso/falha da chamada, tempo de resposta.
*   **Operações Assíncronas/Jobs em Background:**
    *   Início, progresso, conclusão (sucesso ou falha) de tarefas.
*   **Decisões Importantes em Lógica Condicional:** Quando o fluxo do programa toma um caminho específico baseado em certas condições que são importantes para entender o comportamento.

## Formato do Log (JSON Estruturado)

Usar JSON facilita a ingestão e análise por sistemas de gerenciamento de logs.

**Campos Comuns:**

*   `timestamp`: Data e hora do evento (formato ISO 8601 UTC).
*   `level`: Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL).
*   `message`: A mensagem de log principal.
*   `service_name` (ou `application_name`): Nome do serviço/aplicação que gerou o log.
*   `hostname`: Nome da máquina onde o log foi gerado.
*   `pid`: ID do processo.
*   `thread_id` (ou `goroutine_id`): ID da thread/goroutine (se aplicável).
*   `module` (ou `logger_name`, `function_name`): Módulo, classe ou função que originou o log.
*   `correlation_id` (ou `trace_id`, `request_id`): ID para rastrear uma operação através de diferentes logs e serviços.
*   `user_id` (ou `client_id`): Identificador do usuário/cliente associado ao evento.
*   `error_type`: Tipo da exceção (ex: `ValueError`, `NullPointerException`).
*   `error_message`: Mensagem da exceção.
*   `stack_trace`: Stack trace do erro.
*   **Campos Personalizados:** Quaisquer outros dados contextuais relevantes para o evento (ex: `order_id`, `product_id`, `duration_ms`).

**Exemplo de Log em JSON:**

```json
{
  "timestamp": "2023-10-27T10:30:15.123Z",
  "level": "ERROR",
  "message": "Failed to process payment for order",
  "service_name": "payment-service",
  "hostname": "prod-server-01",
  "pid": 12345,
  "module": "PaymentProcessor",
  "correlation_id": "abc123xyz789",
  "user_id": "user-456",
  "order_id": "ord-789",
  "error_type": "InsufficientFundsError",
  "error_message": "User does not have sufficient funds.",
  "stack_trace": "Traceback (most recent call last):\n  File \"payment_processor.py\", line 100, in process\n    raise InsufficientFundsError(...)"
}
```

## Ferramentas de Logging

*   **Bibliotecas de Logging Padrão da Linguagem:**
    *   **Python:** `logging`
    *   **Java:** SLF4J com Logback ou Log4j2
    *   **Node.js:** `console` (básico), Winston, Pino (foco em performance e JSON), Bunyan
    *   **Go:** `log` (básico), Zerolog, Zap
    *   **Ruby:** `Logger`
*   **Configuração:** As bibliotecas permitem configurar handlers (para onde os logs vão: console, arquivo, rede), formatters (como os logs são formatados) e filtros.

## Destinos dos Logs (Outputs/Handlers)

*   **Console (stdout/stderr):** Útil para desenvolvimento e ambientes containerizados (Docker/Kubernetes).
*   **Arquivos Locais:**
    *   Rotação de arquivos (log rotation) para evitar que os arquivos fiquem muito grandes.
    *   Definir tamanho máximo e número de arquivos de backup.
*   **Sistemas de Gerenciamento de Logs Centralizados (Recomendado para Produção):**
    *   **ELK Stack:** Elasticsearch, Logstash, Kibana
    *   **Grafana Loki** com Promtail
    *   **Splunk**
    *   **Datadog Logs**
    *   **AWS CloudWatch Logs**
    *   **Google Cloud Logging**
    *   **Azure Monitor Logs**
    Estes sistemas permitem agregação, busca, análise e alertas em cima dos logs de múltiplas fontes.

## Plano de Implementação

1.  **Escolher a Biblioteca de Logging:** Selecionar uma biblioteca apropriada para a stack do Projeto XYZ.
2.  **Definir o Formato Padrão:** Estabelecer o formato JSON estruturado e os campos principais a serem incluídos.
3.  **Configurar Níveis de Log por Ambiente:**
    *   **Desenvolvimento:** DEBUG ou INFO para console.
    *   **Staging:** INFO para console/arquivo, com opção de DEBUG se necessário.
    *   **Produção:** INFO ou WARNING para um sistema de gerenciamento de logs centralizado. ERROR e CRITICAL devem sempre ser capturados.
4.  **Implementar um Wrapper/Helper (Opcional):** Criar um pequeno wrapper em torno da biblioteca de logging para facilitar o uso consistente e adicionar automaticamente campos contextuais (ex: `service_name`).
5.  **Adicionar Logs em Pontos Chave:**
    *   Começar com o fluxo principal da aplicação: inicialização, requisições HTTP, erros críticos.
    *   Gradualmente adicionar logs em outros pontos conforme descrito em "O Que Logar?".
6.  **Gerenciamento de ID de Correlação:** Implementar a geração e propagação de IDs de correlação (ex: via middleware para requisições HTTP, e passando-o para chamadas de função subsequentes).
7.  **Segurança:** Revisar os logs para garantir que nenhuma informação sensível está sendo exposta. Implementar mascaramento.
8.  **Documentação:** Documentar a estratégia de logging, como adicionar novos logs, e como acessar/analisar logs em diferentes ambientes.
9.  **Integração com Sistema Centralizado (para Produção):** Configurar o envio de logs para a plataforma escolhida.
10. **Treinamento:** Garantir que a equipe entenda como usar o sistema de logging efetivamente.

Uma estratégia de logging bem implementada é um investimento crucial para a manutenibilidade, confiabilidade e observabilidade do Projeto XYZ. Embora não seja uma feature visível ao usuário final, é fundamental para suportar a operação e desenvolvimento do produto.
