# ADR 0001: Projeto 100% Estático, DuckDB Local, Distribuição via Torrent

## Status

Aceito

## Contexto

O projeto Leizilla visa indexar todas as leis brasileiras, começando por Rondônia, com foco em transparência radical, infraestrutura mínima e ser 100% estático. Isso significa evitar a necessidade de servidores backend para hospedagem de dados ou processamento de buscas. A escolha de ferramentas e abordagens deve suportar este objetivo principal.

## Decisão

O Leizilla será desenvolvido seguindo os seguintes princípios arquiteturais fundamentais:

1.  **Operação 100% Estática:** Todos os artefatos gerados (datasets, metadados, frontend de busca) serão arquivos estáticos. Não haverá componentes de backend dinâmicos ou servidores de aplicação para manter.
2.  **DuckDB Local para ETL e Staging:** O DuckDB será utilizado como a principal ferramenta para o processo de Extract, Transform, Load (ETL) dos dados das leis. Ele servirá como um banco de dados local e embarcado para processar, normalizar e preparar os datasets.
3.  **Distribuição de Dados via Torrent (e outros canais estáticos):** Os datasets finais (primariamente em formatos como Parquet e JSON Lines) serão distribuídos utilizando o sistema BitTorrent para permitir acesso resiliente e descentralizado. Outros canais de distribuição estática, como GitHub Releases e espelhamento em serviços de arquivo público, também serão utilizados.
4.  **Busca Client-Side:** A funcionalidade de busca nos dados será implementada no lado do cliente (navegador), utilizando DuckDB-WASM para executar consultas SQL diretamente nos arquivos de dados estáticos.

## Consequências

*   **Positivas:**
    *   **Infraestrutura Simplificada:** Reduz drasticamente a complexidade e o custo de manutenção da infraestrutura, alinhando-se com o objetivo de "infra mínima".
    *   **Escalabilidade de Leitura:** A distribuição de dados via arquivos estáticos e torrents é inerentemente escalável para um grande número de consumidores sem sobrecarga proporcional em um servidor central.
    *   **Reprodutibilidade e Auditoria:** A natureza estática dos datasets e o versionamento facilitam a reprodutibilidade dos dados e a auditoria dos processos de geração.
    *   **Portabilidade dos Dados:** Datasets em formatos padrão (Parquet, JSONL) são facilmente utilizáveis em uma vasta gama de ferramentas e ambientes analíticos.
    *   **Resiliência de Acesso aos Dados:** A distribuição via torrent aumenta a resiliência do acesso aos dados, diminuindo a dependência de um único ponto de hospedagem.
    *   **Performance de ETL:** O uso de DuckDB localmente para ETL permite processamento rápido e eficiente de grandes volumes de dados textuais e sua transformação em formatos estruturados.
    *   **Experiência de Usuário Interativa (Busca):** A busca client-side com DuckDB-WASM pode oferecer uma experiência de usuário rápida e interativa para consultas de dados sem latência de rede para um backend.

*   **Negativas/Desafios:**
    *   **Limitações de Gravação/Interação Dinâmica:** Funcionalidades que exigem escrita de dados em tempo real por parte dos usuários finais (ex: comentários, anotações colaborativas) não são suportadas nativamente por esta arquitetura estática.
    *   **Complexidade da Busca Client-Side Avançada:** Implementar buscas muito complexas, que exigem grandes índices pré-computados ou cruzamento de fontes de dados não presentes no cliente, pode ser desafiador. A pesquisa semântica planejada exigirá considerações adicionais para manter a abordagem estática/client-side.
    *   **Atualização de Dados:** O processo de atualização dos datasets publicados requer a regeneração e redistribuição dos arquivos estáticos, o que pode ser mais complexo do que atualizar um banco de dados centralizado.
    *   **Dependência de Ferramentas Client-Side:** A funcionalidade de busca depende da capacidade do navegador do usuário de executar WASM e manipular os dados localmente.
    *   **Gestão de Dados para ETL:** Embora DuckDB seja eficiente, a gestão do ciclo de vida dos dados brutos, intermediários e processados localmente durante o ETL requer um pipeline bem definido.

*   **Neutras/Compensações:**
    *   **Escolha de Ferramentas Específicas:** A implementação desta arquitetura dependerá da escolha de ferramentas específicas para crawling (Playwright), OCR (potencialmente um serviço externo como Internet Archive), e hospedagem de arquivos (GitHub, Internet Archive). As características dessas ferramentas (ex: OCR automático do IA, geração de torrents pelo IA) influenciarão o fluxo de trabalho detalhado, mas a decisão arquitetural principal de ser estático e usar torrents permanece.

Este ADR estabelece a fundação para a arquitetura do Leizilla, alinhada com seus objetivos centrais de transparência, minimalismo e dados abertos.
