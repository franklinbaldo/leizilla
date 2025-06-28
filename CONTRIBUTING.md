# 🤝 Como Contribuir

## ⚡ Setup Rápido

```bash
# 1. Clone e entre no diretório
git clone https://github.com/franklinbaldo/leizilla.git
cd leizilla

# 2. Setup ambiente Python
uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. Instale dependências
uv sync --dev

# 4. Configure pre-commit hooks
uv run leizilla dev setup
```

**Pronto!** Ambiente funcionando em 2 minutos.

## 🔧 Comandos Essenciais

```bash
# Setup completo (rode uma vez)
uv run leizilla dev setup

# Verificar tudo que o CI roda
uv run leizilla dev check

# Lint e formatação
uv run leizilla dev lint        # Verificar problemas
uv run leizilla dev format      # Corrigir formatação

# Testes
uv run leizilla dev test        # Rodar testes

# Comandos individuais com uv
uv run ruff check .             # Lint direto
uv run ruff format .            # Formatação direta
uv run mypy .                   # Type checking direto
uv run pytest                   # Testes diretos
```

## 🔀 Fluxo de Pull Request

1. **Crie branch** a partir de `main`:
   ```bash
   git checkout main
   git pull origin main
   git checkout -b feat/sua-feature
   ```

2. **Faça suas mudanças** seguindo o padrão do projeto

3. **Commit usando Conventional Commits**:
   ```bash
   git commit -m "feat: adicionar crawler para leis estaduais"
   git commit -m "fix: corrigir parsing de metadados"
   git commit -m "docs: atualizar exemplo de uso"
   ```

4. **Checklist antes do push**:
   ```bash
   uv run leizilla dev check  # Deve passar sem erros
   ```

5. **Abra PR** com descrição clara do que foi feito

## ✅ Checklist Pré-Push

- [ ] `uv run leizilla dev check` passa sem erros
- [ ] Testes cobrem nova funcionalidade
- [ ] ADR criado para mudanças arquiteturais
- [ ] Documentação atualizada se necessário
- [ ] Commit messages seguem padrão

## 📋 Tipos de Contribuição

### 🚀 **Novas Features**
- Sempre criar **ADR** primeiro em `docs/adr/`
- Seguir padrão do projeto (veja `src/`)
- Incluir testes unitários

### 🐛 **Bug Fixes**
- Reproduzir bug em teste
- Corrigir e verificar que teste passa
- Mencionar issue no commit

### 📚 **Documentação**
- Manter exemplos atualizados
- Usar linguagem clara e direta
- Evitar duplicação entre arquivos

### 🎨 **Melhorias**
- Manter compatibilidade com código existente
- Discutir mudanças breaking em issues

## 🎯 Padrões do Projeto

### **Código Python**
- **Python 3.12+** obrigatório
- **Type hints** em todas funções
- **Docstrings** para APIs públicas
- **ruff** para formatação e linting

### **Testes**
- Usar **pytest** 
- Cobertura básica (mínimo 60%, crescer gradualmente)
- Mockar APIs externas
- Testes rápidos (<5s total)

### **Commits**
- **Conventional Commits** obrigatório
- Scopes: `feat`, `fix`, `docs`, `style`, `refactor`, `test`
- Mensagens em inglês

## 🔍 Dúvidas Frequentes

**P: Como adicionar nova dependência?**  
R: `uv add nome-da-lib` e inclua no commit

**P: Como rodar apenas um teste?**  
R: `uv run pytest tests/test_specific.py -v`

**P: Como criar ADR?**  
R: Copie template de ADR existente em `docs/adr/`

**P: Onde documentar changes breaking?**  
R: Sempre em ADR + mencionar no PR description

---

## 🆘 Precisa de Ajuda?

1. Leia `docs/DEVELOPMENT.md` para detalhes técnicos
2. Consulte ADRs existentes em `docs/adr/`
3. Abra issue com label `question`

**Obrigado por contribuir com o Leizilla!** 🦖⚖️