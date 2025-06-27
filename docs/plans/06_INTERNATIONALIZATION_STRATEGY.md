# Estratégia de Internacionalização (i18n)

## Objetivo

Capacitar o Projeto XYZ a suportar múltiplos idiomas em sua interface de usuário (UI) e, potencialmente, em outros conteúdos textuais. Mesmo que inicialmente apenas um idioma seja implementado (ex: Português ou Inglês), a estrutura para i18n será estabelecida para facilitar futuras traduções.

## Benefícios da Internacionalização

*   **Alcance Global:** Tornar o produto acessível e utilizável por um público mais amplo.
*   **Melhor Experiência do Usuário:** Usuários se sentem mais confortáveis utilizando um produto em seu idioma nativo.
*   **Vantagem Competitiva:** Pode ser um diferencial em mercados globais.
*   **Escalabilidade:** Preparar o projeto para crescimento em diferentes regiões.

## Abordagem Geral

A internacionalização será implementada seguindo estas etapas principais:

1.  **Escolha da Biblioteca/Framework de i18n:** Selecionar uma biblioteca robusta e adequada à stack tecnológica do projeto.
2.  **Externalização de Strings:** Mover todas as strings visíveis ao usuário do código-fonte para arquivos de tradução dedicados.
3.  **Configuração da Estrutura de Tradução:** Definir como os arquivos de tradução serão organizados e gerenciados.
4.  **Implementação da Lógica de Seleção de Idioma:** Permitir que o usuário escolha o idioma ou detectá-lo automaticamente.
5.  **Processo de Tradução:** Definir como as novas strings serão traduzidas e atualizadas.

## Escolha da Biblioteca/Framework de i18n

A escolha dependerá da linguagem e do framework principal do Projeto XYZ:

*   **JavaScript (Frontend - React, Vue, Angular):**
    *   `react-i18next` (para React, baseado em `i18next`)
    *   `vue-i18n` (para Vue.js)
    *   `@angular/localize` (para Angular)
    *   `i18next` (biblioteca principal, pode ser usada com qualquer framework ou vanilla JS)
*   **JavaScript (Backend - Node.js):**
    *   `i18next`
    *   `@fastify/accept-negotiator` (para Fastify, para detecção de idioma) + `i18next`
*   **Python (Django):**
    *   Sistema de tradução embutido do Django (`django.utils.translation`).
*   **Python (Flask):**
    *   `Flask-Babel`.
*   **Java (Spring Boot):**
    *   Suporte nativo do Spring para `ResourceBundleMessageSource`.
*   **Outras Linguagens:** Pesquisar bibliotecas populares e bem mantidas para a respectiva stack.

**Critérios de Seleção:**

*   Popularidade e suporte da comunidade.
*   Facilidade de integração.
*   Suporte para pluralização.
*   Suporte para interpolação de variáveis.
*   Suporte para formatação de datas, números e moedas.
*   Performance.

## Externalização de Strings

Todas as strings que são exibidas na interface do usuário (rótulos de botões, mensagens de erro, títulos, etc.) devem ser substituídas por chamadas a uma função de tradução fornecida pela biblioteca de i18n.

**Exemplo (usando uma sintaxe genérica `t('key')`):**

**Antes:**

```html
<!-- Em um template HTML/JSX -->
<h1>Welcome to our Application!</h1>
<button>Submit</button>
<p>Error: Invalid input.</p>
```

```javascript
// Em código JavaScript
const message = "Profile updated successfully.";
```

**Depois:**

```html
<!-- Em um template HTML/JSX -->
<h1>{{ t('home.title') }}</h1>
<button>{{ t('common.submit') }}</button>
<p>{{ t('errors.invalidInput') }}</p>
```

```javascript
// Em código JavaScript
const message = t('profile.updateSuccess');
```

**Chaves de Tradução:**

*   Usar um sistema de chaves hierárquico e descritivo (ex: `pageName.section.keyName`).
*   Manter a consistência na nomeação das chaves.

## Estrutura dos Arquivos de Tradução

Normalmente, os arquivos de tradução são organizados por idioma, e às vezes por módulo ou namespace.

**Formato Comum:** JSON, YAML, PO/POT (para Gettext).

**Exemplo de Estrutura de Diretório:**

```
locales/
├── en/
│   ├── common.json
│   ├── home.json
│   └── profile.json
├── pt_BR/
│   ├── common.json
│   ├── home.json
│   └── profile.json
└── es/
    ├── common.json
    ├── home.json
    └── profile.json
```

**Exemplo de `locales/en/home.json`:**

```json
{
  "title": "Welcome to our Application!",
  "subtitle": "Discover amazing features."
}
```

**Exemplo de `locales/pt_BR/home.json`:**

```json
{
  "title": "Bem-vindo à nossa Aplicação!",
  "subtitle": "Descubra funcionalidades incríveis."
}
```

## Implementação da Lógica de Seleção de Idioma

1.  **Idioma Padrão:** Definir um idioma padrão (ex: `en`).
2.  **Detecção de Idioma:**
    *   **Preferência do Usuário:** Se o usuário estiver logado, permitir que ele defina um idioma preferido em suas configurações de perfil.
    *   **Cabeçalho `Accept-Language`:** Utilizar o cabeçalho HTTP `Accept-Language` enviado pelo navegador.
    *   **Parâmetro de URL ou Subdomínio:** Ex: `example.com/pt-br/page` ou `pt-br.example.com/page`.
    *   **Cookie ou Local Storage:** Armazenar a escolha do usuário.
3.  **Mecanismo de Troca de Idioma:** Fornecer um componente na UI (ex: um dropdown) para que o usuário possa mudar o idioma manualmente.
4.  **Carregamento das Traduções:**
    *   Carregar apenas o arquivo de idioma ativo para otimizar o desempenho.
    *   Algumas bibliotecas suportam "code splitting" para arquivos de tradução.

## Processo de Tradução

1.  **Idioma Base:** Desenvolver inicialmente com todas as strings no idioma base (ex: Inglês), usando as chaves de tradução.
2.  **Extração de Strings:** Usar ferramentas (muitas bibliotecas de i18n vêm com CLIs) para extrair automaticamente as chaves de tradução do código-fonte para um arquivo de template (ex: `en.json` ou `messages.pot`).
3.  **Tradução:**
    *   **Manual:** Tradutores humanos (internos ou externos) traduzem os arquivos de template para os idiomas desejados.
    *   **Ferramentas de Gerenciamento de Tradução (TMS):** Plataformas como Crowdin, Transifex, Lokalise, Weblate podem ajudar a gerenciar o fluxo de trabalho de tradução, colaborar com tradutores e manter as traduções sincronizadas.
    *   **Tradução Automática (com revisão):** Usar serviços como Google Translate ou DeepL para uma tradução inicial, seguida por revisão humana.
4.  **Integração das Traduções:** Adicionar os arquivos traduzidos ao repositório na estrutura definida.
5.  **Atualizações:** Quando novas strings são adicionadas ao código, repetir o processo de extração e tradução.

## Considerações Adicionais

*   **Pluralização:** Lidar corretamente com formas plurais, que variam entre idiomas (ex: `1 item`, `2 items` vs. variações mais complexas em outros idiomas). As bibliotecas de i18n geralmente têm suporte para isso.
*   **Gênero:** Alguns idiomas têm formas gramaticais diferentes baseadas em gênero. Isso pode ser complexo e pode exigir strings separadas ou lógica específica.
*   **Formatação de Datas, Números e Moedas:** Usar as funcionalidades da biblioteca de i18n ou APIs nativas da linguagem (ex: `Intl` no JavaScript) para formatar esses valores de acordo com o locale do usuário.
*   **Layout e Design (LTR/RTL):** Se houver suporte para idiomas da direita para a esquerda (RTL) como Árabe ou Hebraico, o layout da UI precisará ser ajustado (geralmente via CSS).
*   **Imagens e Conteúdo Multimídia:** Considerar se imagens contendo texto também precisam ser localizadas.
*   **SEO:** Implementar `hreflang` tags para ajudar os motores de busca a entenderem as diferentes versões de idioma das páginas.
*   **Testes:** Testar a aplicação em diferentes idiomas para garantir que as traduções são exibidas corretamente e que o layout não está quebrado.

## Plano de Implementação Inicial

1.  **Pesquisa e Decisão:** Selecionar a biblioteca de i18n mais adequada (1-2 dias).
2.  **Configuração Básica:** Integrar a biblioteca escolhida no projeto. Configurar o idioma padrão (ex: Inglês) e criar a estrutura inicial de arquivos (ex: `locales/en/common.json`) (2-3 dias).
3.  **Refatoração Inicial:** Converter uma pequena seção ou algumas páginas da aplicação para usar o sistema de i18n, externalizando as strings (3-5 dias). Isso servirá como um piloto.
4.  **Documentar o Processo:** Criar um guia interno para desenvolvedores sobre como adicionar novas strings e solicitar traduções.
5.  **Planejar a Tradução Completa:** Definir o escopo para traduzir o restante da aplicação e como o processo de tradução será gerenciado.

Adotar uma estratégia de internacionalização desde cedo, mesmo que apenas um idioma seja suportado inicialmente, tornará o Projeto XYZ muito mais adaptável e pronto para o crescimento futuro em mercados globais.
