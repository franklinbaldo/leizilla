# Diretrizes para Refatoração Contínua

## Objetivo

Estabelecer um processo e diretrizes para a refatoração contínua do código do Projeto XYZ. O objetivo é melhorar progressivamente a qualidade interna do código, focando em legibilidade, manutenibilidade, simplicidade e performance, sem alterar o comportamento externo observável.

## Por que Refatorar?

*   **Melhorar a Compreensão:** Código claro é mais fácil de entender, modificar e depurar.
*   **Facilitar a Manutenção:** Reduz o tempo e o esforço necessários para corrigir bugs ou adicionar novas funcionalidades.
*   **Reduzir Complexidade:** Simplificar algoritmos complexos e estruturas de dados.
*   **Encontrar Bugs Escondidos:** O processo de refatoração muitas vezes revela problemas latentes.
*   **Aumentar a Reusabilidade:** Componentes bem definidos e desacoplados são mais fáceis de reutilizar.
*   **Melhorar a Performance:** Embora não seja o objetivo primário de toda refatoração, pode ser um resultado em áreas específicas.
*   **Adaptar-se a Novos Requisitos:** Facilitar a evolução do sistema.

## Quando Refatorar? (A Regra do Escoteiro)

"Deixe a área do acampamento mais limpa do que você a encontrou."

*   **Antes de Adicionar uma Nova Funcionalidade:** Se o código existente não está claro ou bem estruturado para suportar a nova feature, refatore-o primeiro.
*   **Ao Corrigir um Bug:** Muitas vezes, a causa raiz de um bug é um código confuso. Refatore para tornar a correção mais fácil e para prevenir bugs futuros.
*   **Durante Revisões de Código (Code Reviews):** Identificar oportunidades de refatoração é uma parte importante da revisão. Pequenas refatorações podem ser sugeridas ou feitas diretamente.
*   **Após Entender Melhor o Código:** Quando você trabalha em uma parte do código e finalmente a entende, aproveite para limpá-la para o próximo desenvolvedor.
*   **Sessões Dedicadas (Ocasionalmente):** Para dívidas técnicas maiores, pode ser necessário alocar tempo específico para refatoração.

## O Que Procurar (Code Smells - "Maus Cheiros" no Código)

Indicadores de que uma refatoração pode ser necessária:

*   **Código Duplicado:** O mesmo bloco de código aparece em múltiplos lugares.
    *   **Refatoração:** Extrair para uma função/método/classe comum.
*   **Funções/Métodos Longos:** Funções que fazem muitas coisas ou são difíceis de entender de uma vez.
    *   **Refatoração:** Decompor em funções menores e mais focadas (Extrair Método).
*   **Classes Grandes (God Classes):** Classes que têm muitas responsabilidades, conhecem ou fazem demais.
    *   **Refatoração:** Dividir a classe em classes menores e mais coesas (Extrair Classe, Princípio da Responsabilidade Única - SRP).
*   **Muitos Parâmetros em Funções/Métodos:** Pode indicar que a função está fazendo demais ou que alguns parâmetros podem ser agrupados.
    *   **Refatoração:** Introduzir Objeto de Parâmetro, Preservar Objeto Inteiro.
*   **Obsessão por Tipos Primitivos:** Usar tipos primitivos (string, int) para representar conceitos do domínio que poderiam ser classes.
    *   **Refatoração:** Substituir Tipo Primitivo por Objeto.
*   **Comentários Excessivos (Code Deodorant):** Comentários usados para explicar código confuso em vez de tornar o código autoexplicativo.
    *   **Refatoração:** Renomear variáveis/funções, Extrair Método para tornar o código mais claro.
*   **Nomes Ruins:** Nomes de variáveis, funções, classes que não revelam claramente seu propósito.
    *   **Refatoração:** Renomear Variável/Função/Classe.
*   **Feature Envy (Inveja de Funcionalidade):** Um método que parece mais interessado nos dados de outra classe do que na sua própria.
    *   **Refatoração:** Mover Método para a classe que contém os dados que ele mais utiliza.
*   **Switch Statements ou Cadeias de `if-else if` Longas:** Especialmente se baseadas no tipo de um objeto.
    *   **Refatoração:** Substituir Condicional por Polimorfismo.
*   **Message Chains (Cadeias de Mensagens):** `objeto.getOutraCoisa().getMaisUmaCoisa().facaAlgo()` - Acoplamento excessivo.
    *   **Refatoração:** Ocultar Delegado (Lei de Demeter).
*   **Middle Man (Homem do Meio):** Classes que delegam a maior parte do seu trabalho para outras classes.
    *   **Refatoração:** Remover Homem do Meio, Inlinear Método.
*   **Data Clumps (Aglomerados de Dados):** Grupos de variáveis que frequentemente aparecem juntas em diferentes partes do código.
    *   **Refatoração:** Extrair Classe para agrupar esses dados.
*   **Temporary Field (Campo Temporário):** Um campo de instância que é usado apenas em certas circunstâncias.
    *   **Refatoração:** Extrair Classe, Introduzir Objeto Nulo.

## Processo de Refatoração Seguro

1.  **Tenha Testes:** **NÃO REFATORE SEM TESTES AUTOMATIZADOS!** Os testes garantem que você não alterou o comportamento externo do código. Se não houver testes para a seção de código que você quer refatorar, escreva-os primeiro (testes de caracterização).
2.  **Pequenos Passos:** Faça uma pequena alteração de cada vez.
3.  **Teste Frequentemente:** Execute os testes após cada pequena alteração. Se um teste quebrar, é fácil identificar o que deu errado e reverter ou corrigir.
4.  **Commits Atômicos:** Faça commit das suas refatorações em pequenos incrementos lógicos, com mensagens claras. Isso facilita a revisão e o rollback se necessário.
5.  **Use Ferramentas de Refatoração da IDE:** Muitas IDEs (VS Code, IntelliJ, PyCharm, Eclipse) têm ferramentas automatizadas para refatorações comuns (renomear, extrair método, etc.). Elas são menos propensas a erros.
6.  **Revisão de Código:** Peça para outro desenvolvedor revisar suas refatorações, especialmente as mais significativas.

## Áreas Prioritárias para Refatoração (Sugestões Iniciais)

*   **Identificar os módulos/classes mais complexos:** Usar métricas como Complexidade Ciclomática, se disponível, ou simplesmente a percepção da equipe.
*   **Código com histórico de bugs:** Áreas que frequentemente apresentam problemas.
*   **Partes do sistema que serão modificadas em breve:** Refatorar antes de adicionar novas funcionalidades pode economizar tempo a longo prazo.
*   **Código que é difícil de testar:** Geralmente indica forte acoplamento ou responsabilidades misturadas.

## O Que NÃO é Refatoração

*   **Reescrever código do zero sem um plano claro:** Refatoração é sobre melhoria incremental.
*   **Adicionar novas funcionalidades:** O comportamento externo não deve mudar.
*   **Corrigir bugs (apenas):** Embora a refatoração possa revelar e ajudar a corrigir bugs, o objetivo principal é melhorar a estrutura. A correção do bug é uma tarefa separada, embora possa ser feita em conjunto.
*   **Otimização de performance prematura:** Refatore para clareza primeiro. Otimize a performance apenas quando houver um gargalo identificado por profiling.

## Cultura de Refatoração

*   **Incentivar a refatoração como parte do trabalho diário.**
*   **Não culpar por código "ruim" existente:** O código evolui, e o entendimento também.
*   **Valorizar a qualidade interna do software.**
*   **Discutir e aprender sobre padrões de design e técnicas de refatoração em equipe.**

## Ferramentas de Suporte

*   **IDEs com funcionalidades de refatoração automática.**
*   **Linters e Analisadores Estáticos:** Ferramentas como ESLint, Pylint, SonarLint, CodeClimate podem ajudar a identificar code smells automaticamente.
*   **Frameworks de Teste:** Essenciais para garantir a segurança da refatoração.
*   **Ferramentas de Cobertura de Teste:** Para garantir que as áreas refatoradas estão bem testadas.

Este plano visa incorporar a refatoração como uma prática padrão no ciclo de desenvolvimento do Projeto XYZ, levando a um codebase mais saudável, sustentável e agradável de se trabalhar. Embora este plano em si não seja uma "feature" de produto, ele é crucial para a capacidade de entregar features de alta qualidade de forma eficiente e contínua.
