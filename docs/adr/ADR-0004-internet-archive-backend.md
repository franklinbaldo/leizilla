# ADR-0004: Internet Archive como Backend de Processamento e Distribuição

**Status:** Proposto

**Contexto:**

O projeto Leizilla necessita de uma solução robusta, de baixo custo e escalável para o armazenamento de grandes volumes de arquivos PDF (atos normativos), processamento de OCR nesses arquivos, e distribuição pública dos dados brutos e processados. Manter uma infraestrutura própria para essas tarefas pode ser custoso e complexo.

**Decisão:**

Utilizaremos o Internet Archive (IA) como a principal plataforma para:

1.  **Armazenamento Permanente de PDFs:** Todos os PDFs coletados serão enviados para o IA.
2.  **Processamento de OCR:** O IA automaticamente realiza OCR na maioria dos PDFs textuais ou de imagem, disponibilizando o texto extraído (geralmente em formato DjVu TXT). O Leizilla consumirá este texto OCRizado pelo IA.
3.  **Geração de Derivados:** O IA gera automaticamente formatos derivados, como DjVu, e notavelmente, arquivos `.torrent` para cada item, facilitando a distribuição P2P.
4.  **Distribuição Primária:** Os links de download direto do IA (para PDFs, texto OCR) e os links `.torrent` serão os canais primários de acesso aos dados brutos.

**Motivação:**

*   **Custo Zero:** O armazenamento e processamento no IA são gratuitos para uploads de material de interesse público.
*   **Escalabilidade e Resiliência:** O IA é uma instituição global com infraestrutura massiva projetada para preservação digital a longo prazo.
*   **Funcionalidades Prontas:** OCR, geração de torrents, e APIs de acesso já são fornecidas pelo IA, economizando esforço de desenvolvimento.
*   **Alinhamento com a Missão:** Disponibilizar dados públicos em uma plataforma de acesso aberto como o IA está alinhado com os objetivos de transparência do Leizilla.
*   **Descoberta Facilitada:** Itens no IA são indexados e podem ser descobertos por um público mais amplo.

**Consequências e Riscos:**

*   **Dependência de Terceiros:** O Leizilla se torna dependente da disponibilidade contínua e das políticas do Internet Archive. Mudanças na API, políticas de uso, ou a eventual descontinuidade do serviço representam um risco.
*   **Velocidade de Processamento:** O tempo para OCR e geração de derivados no IA não é controlado pelo Leizilla e pode variar.
*   **Limitações da API:** A API do IA pode ter limitações de taxa (rate limits) ou pode não expor todas as funcionalidades desejadas de forma programática fácil (ex: obtenção direta de magnet links otimizados).
*   **Controle sobre os Dados:** Embora os dados sejam publicamente acessíveis, o controle final sobre a infraestrutura de armazenamento não é do Leizilla.
*   **Qualidade do OCR:** A qualidade do OCR do IA é geralmente boa, mas pode variar e não é configurável pelo Leizilla. Para casos específicos onde um OCR de altíssima precisão ou customizado seja necessário, esta solução pode não ser suficiente.

**Mitigações:**

*   **Torrents como Backup Resiliente e Canal de Distribuição Alternativo:** A geração automática de arquivos `.torrent` pelo IA para cada item é uma mitigação chave. Os torrents permitem a distribuição descentralizada (P2P) dos dados. O Leizilla irá:
    *   Coletar e armazenar os links `.torrent` e, se possível, `magnet links` para cada item/dataset.
    *   Promover o uso de torrents como um método robusto para a comunidade obter cópias completas dos datasets, reduzindo a dependência de um único ponto de acesso (servidores do IA).
    *   Incentivar a semeadura (seeding) dos torrents pela comunidade.
*   **Exportações Locais Agregadas:** Manter a capacidade de gerar datasets agregados (ex: Parquet, JSONL) localmente, que podem ser distribuídos por outros canais se necessário, embora o IA seja o primário para os arquivos brutos.
*   **Monitoramento da Saúde do IA:** Acompanhar o status do serviço do IA e suas políticas.
*   **Design Modular:** Manter a modularidade do sistema para que, em um cenário extremo, o backend de armazenamento e processamento possa ser substituído, embora com esforço considerável.
*   **Foco em Dados Públicos:** Ao focar em dados que já são públicos, o risco associado ao controle de dados é menor do que seria para dados privados ou sensíveis.

**Alternativas Consideradas:**

*   **Infraestrutura Própria (Self-Hosted):** Envolveria custos significativos de servidores, armazenamento, desenvolvimento e manutenção de software de OCR, e mecanismos de distribuição. Rejeitada devido ao custo e complexidade.
*   **Serviços de Cloud (AWS S3/Textract, GCP Storage/Vision API):** Oferecem grande escalabilidade e funcionalidades, mas com custos diretos associados ao volume de dados e processamento, que podem crescer rapidamente. Rejeitada para manter o Leizilla como um projeto de custo operacional próximo de zero.

Este ADR formaliza a decisão de usar o Internet Archive como um pilar central da arquitetura do Leizilla, reconhecendo seus benefícios e gerenciando ativamente os riscos associados.
