# 📌 Leizilla – Master TODO

> Todas as tarefas são **opt‑in**. Para evitar paralisia, só mova algo para "Em progresso" depois de abrir uma *issue* ou *PR* vinculada.

---

## 0️⃣ Meta

* [ ] **Lifecycle** – quando concluir uma tarefa, mova‑a para `DONE.md` com data e SHA.
* [ ] **Labels** – padronizar tags `prio:high`, `type:bug`, etc. no GitHub.

---

## 1️⃣ Config & Setup

* [ ] Documentar como obter `IA_ACCESS_KEY` / `IA_SECRET_KEY` fileciteturn1file0
* [ ] Adicionar validação em runtime para variáveis de ambiente em `config.py` fileciteturn1file0
* [ ] Expandir `.env.example` com descrição e valores padrão fileciteturn1file0
* [ ] Criar script `./scripts/doctor.sh` que verifica pré‑requisitos (uv, DuckDB, Playwright).
* [ ] Fornecer instalador cross‑platform (`install.ps1`, `install.sh`).

---

## 2️⃣ Crawler & ETL

* [ ] Substituir lógica *placeholder* no `LeisCrawler` por crawler real do portal ALE‑RO.
* [ ] Implementar **crawl resume** usando flags no banco (`status_crawling`).
* [ ] Adicionar *rate‑limit* e *back‑off* automáticos.
* [ ] Salvar snapshot HTML para cada lei (proveniência).
* [ ] Normalizar texto via spaCy (acentos, stop‑words).
* [ ] Paralelizar ETL com `anyio` TaskGroups.

---

## 3️⃣ Banco & Schema

* [ ] Criar índices FTS assim que DuckDB suportar Português.
* [ ] Integrar extensão `vector()` para busca semântica.
* [ ] Introduzir *migrations* estilo Alembic em `storage.py`.
* [ ] Verificar integridade com checksums SHA‑256 contra arquivos no IA.

---

## 4️⃣ CLI & UX

* [ ] Novo comando `leizilla validate` para sanity‑check de datasets.
* [ ] Exibir barras de progresso com `tqdm` (ou `rich`).
* [ ] Saída colorida e legível.
* [ ] Adicionar `justfile` com atalhos comuns.

---

## 5️⃣ Testes & Qualidade

* [ ] Cobertura mínima 80 % (pytest‑cov).
* [ ] Testes de integração crawler/publisher usando VCR.py.
* [ ] Job Windows no GitHub Actions.
* [ ] Refinar configuração Ruff (regra E501 opt‑out?).

---

## 6️⃣ Pipeline & CI/CD

* [ ] Workflow cron semanal para rodar pipeline completo.
* [ ] Cache de navegadores Playwright no CI.
* [ ] Upload noturno do banco `.duckdb` para IA com tag YYYY‑MM‑DD.
* [ ] Gerar arquivo `SHA256SUMS` nos releases.

---

## 7️⃣ Frontend Estatístico

* [ ] Esqueleto HTML/CSS minimalista + DuckDB‑WASM.
* [ ] Templates de queries (dropdown).
* [ ] Botão de exportação CSV/JSON.
* [ ] Auditoria de acessibilidade (WCAG AA).

---

## 8️⃣ Documentação

* [ ] Consolidar seções duplicadas entre `README.md` e `docs/DEVELOPMENT.md`.
* [ ] Adicionar diagrama Mermaid de alto nível.
* [ ] Criar `STYLE_GUIDE.md` com convenções de commit e código.
* [ ] FAQ sobre limites do Internet Archive.
