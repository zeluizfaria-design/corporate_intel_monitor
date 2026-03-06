# Corporate Intelligence Monitor - Contexto de Sessao
> Atualizado em 2026-03-06 para retomada em nova janela de contexto.

## Estado resumido
- Backend funcional (coletores + NLP + DuckDB + API).
- P8 avancou no frontend React/TS com backlog tecnico imediato implementado na UI.
- Endpoints sociais para a UI adicionados (`/social/sources` e `/social/{ticker}/summary`).
- Dialog de identidade de login (email de apoio) implementado no frontend com armazenamento local.
- Runtime Node.js/npm instalado e frontend compilando em build de producao.
- Testes de componentes configurados com Vitest + React Testing Library.

## Mudancas aplicadas nesta sessao

### Backend
- Ajustes em `api/main.py`:
  - organizacao de imports e estabilidade do modulo
  - novo `GET /social/sources`
  - novo `GET /social/{ticker}/summary`
- Ajuste em `collectors/social_collector.py`:
  - StockTwits com headers browser-like para reduzir bloqueio 403.

### Frontend
Arquivos atualizados em `frontend/` nesta janela:
- `README.md`
- `src/App.tsx`
- `src/api.ts`
- `src/types.ts`
- `src/index.css`
- `src/App.test.tsx`
- `src/test/setup.ts`
- `vite.config.ts`
- `package.json`

Funcionalidades adicionadas:
- Watchlist na UI (`GET/POST/DELETE /watchlist`) com cadastro e remocao.
- Clique em ticker da watchlist para consultar rapidamente.
- Filtro por `source_type` no feed via query da API.
- Botao de exportacao CSV consumindo `GET /export/{ticker}?days=...`.
- Cards de tendencia social por fonte com participacao percentual.
- Ordenacao do feed (`mais recentes`, `mais antigos`, `fonte`, `titulo`).
- Paginacao do feed (20 itens por pagina, navegacao `Anterior/Proxima`).
- Visualizacoes por periodo na UI:
  - sentimento diario (barras empilhadas)
  - eventos no periodo (ranking com barras)
- Estados de carregamento granulares por painel:
  - resumo
  - feed
  - resumo social
  - fontes sociais
  - watchlist
- `loadAll` com `Promise.allSettled` para degradacao parcial quando um endpoint falha.
- Ajuste de encoding em `frontend/package.json` (UTF-8 sem BOM) para compatibilidade com Vite/PostCSS.

Validacao executada:
- `npm install` concluido em `frontend/`.
- `npm run build` concluido com sucesso (Vite + TypeScript).
- `npm run test:run` concluido com sucesso (Vitest: 8 testes passando).
- `npm audit --json` concluido com `0 vulnerabilidades`.
- Versoes usadas: Node `v24.14.0`, npm `11.9.0`.
- Ajuste aplicado em `frontend/package.json`: `overrides.esbuild` para mitigar advisory do ecossistema Vite/esbuild.

## Decisao sobre Gmail no fluxo
- Aprovado apenas como email/alias de referencia para login manual.
- Proibido armazenar senha/token/cookie/MFA no frontend.
- Implementado aviso explicito de seguranca na dialog.

## Dependencias/ambiente pendentes
- `fastapi` e `uvicorn` instalados no ambiente Python global via `uv pip install --system`.
- `node`/`npm` existem em `C:\Program Files\nodejs`, mas o shell pode exigir ajuste de `PATH` para comandos Node.

## Smoke E2E P8 (executado em 2026-03-06)
- Backend e frontend iniciados com sucesso (`uvicorn` em `127.0.0.1:8000` e Vite em `127.0.0.1:5173`).
- Checks validados com sucesso:
  - `GET /social/sources`
  - `GET /social/{ticker}/summary`
  - fluxo watchlist (`GET` + `POST` + `DELETE`)
  - filtro por `source_type` no feed (`GET /articles/{ticker}?source_type=...`)
  - `GET /articles/{ticker}/summary`
  - `POST /collect`
  - `GET /export/{ticker}` retornando `text/csv`
- Resultado: smoke tecnico P8 aprovado para os fluxos principais integrados API + frontend.
- Pendente apenas validacao manual visual em browser (interacoes de clique/download/dialogo de identidade).

## Revalidacao tecnica adicional (2026-03-06)
- Frontend revalidado:
  - `npm run test:run`: sucesso (`8/8` testes passando).
  - `npm run build`: sucesso (build de producao gerado em `frontend/dist`).
- Smoke de integracao com processos reais reexecutado:
  - `GET /health` -> `200`
  - `GET /social/sources` -> `200`
  - `GET /articles/NVDA/summary?days=7` -> `200`
  - `GET /export/NVDA?days=7` -> `200` (`text/csv`)
  - `GET http://127.0.0.1:5173` -> `200` (`text/html`)
- Observacao de ambiente:
  - neste shell, `npm`/`node` podem nao estar no `PATH` por padrao; usar `C:\Program Files\nodejs\` quando necessario.

## Estado do backlog P8
- Item 1 (ordenacao/paginacao do feed): concluido.
- Item 2 (visualizacoes de eventos/sentimento por periodo): concluido.
- Item 3 (loading granular por painel): concluido.
- Item 4 (testes de componentes com Vitest + RTL): concluido com cobertura ampliada:
  - carregamento + paginacao
  - filtro por fonte
  - exportacao CSV
  - watchlist (adicionar/consultar/remover)
  - degradacao parcial (`Promise.allSettled`)
  - erros de `POST/DELETE` da watchlist

## Avanco pos-P8 (integracao automatizada)
- Nova suite de integracao backend criada em `tests/test_api_integration.py` com `unittest + FastAPI TestClient`.
- Suite cobre:
  - `GET /health`
  - `GET /articles/{ticker}` e `GET /articles/{ticker}/summary`
  - filtro `source_type`
  - `GET /social/sources` e `GET /social/{ticker}/summary`
  - fluxo de watchlist (`POST` duplicado + `GET` + `DELETE`)
  - `GET /export/{ticker}` com validacao de `text/csv`
- Estrategia de isolamento:
  - DuckDB temporario por teste em `tests/.tmp/`, sem depender do banco principal.
- Comando de execucao:
  - `python -m unittest tests.test_api_integration -v`
- Status atual:
  - `6/6` testes passando em 2026-03-06.

## Avanco em resiliencia (2026-03-06)
- `collectors/base_collector.py` recebeu resiliencia adicional em `_get()`:
  - retry para HTTP transitorio: `429`, `500`, `502`, `503`, `504`
  - suporte a `Retry-After` quando disponivel
  - retry para `httpx.TimeoutException` e `httpx.TransportError`
  - falha rapida para erros nao-transitorios (ex.: `404`)
  - validacao explicita de inicializacao do client (`async with`)
- Nova suite: `tests/test_base_collector_resilience.py` cobrindo:
  - retry em `429` com sucesso posterior
  - retry em timeout com sucesso posterior
  - sem retry em `404`
  - erro apos 3 tentativas em `503`
  - erro quando `_get()` e chamado sem contexto assíncrono
- Validacao combinada:
  - `python -m unittest tests.test_base_collector_resilience tests.test_api_integration -v`
  - resultado: `11/11` testes passando.

## Automacao de pipeline local (2026-03-06)
- Script criado: `scripts/run_ci.ps1`
- Fluxo automatizado no script:
  - `npm ci` (com cache local em `frontend/.npm-cache`)
  - `npm run test:run`
  - `npm run build`
  - `python -m unittest tests.test_base_collector_resilience tests.test_api_integration -v`
- Robustez do script:
  - fallback de `npm.cmd` para `C:\Program Files\nodejs\npm.cmd`
  - verificacao de `LASTEXITCODE` em cada etapa (falha rapida)
  - opcao `-SkipNpmCi` para iteracoes rapidas locais
- Execucao validada em 2026-03-06 com sucesso (frontend + backend verdes).

## CI remoto (GitHub Actions) (2026-03-06)
- Workflow criado: `.github/workflows/ci.yml`
- Disparo:
  - `push` (todas as branches)
  - `pull_request`
- Etapas do job (`ubuntu-latest`):
  - setup Node 24 + cache npm
  - setup Python 3.13
  - frontend: `npm ci`, `npm run test:run`, `npm run build`
  - backend: install deps minimas de teste (`fastapi`, `uvicorn`, `duckdb`, `pydantic-settings`, `python-dotenv`, `httpx`)
  - backend tests: `python -m unittest tests.test_base_collector_resilience tests.test_api_integration -v`

## Estado Git/publicacao (2026-03-06)
- Repositorio Git inicializado no projeto.
- Branch atual: `main`.
- Commits locais criados:
  - `fe6e3c1` - `chore: setup CI pipelines and automated integration/resilience tests`
  - `eec6c36` - `chore: track CI helper script and ignore local artifacts`
- `safe.directory` configurado globalmente para:
  - `C:/Users/Jose/.claude/projects/corporate_intel_monitor`
- Estado atual: sem `remote` configurado; pendente apenas `git remote add origin ...` + `git push -u origin main` para ativar CI remoto no GitHub.

## Retomada rapida (ordem sugerida)
1. Subir API (`uvicorn api.main:app --host 0.0.0.0 --port 8000`).
2. Subir frontend (`npm run dev`; se PowerShell bloquear scripts, usar `npm.cmd run dev`).
3. Executar testes automatizados frontend (`npm run test:run`).
4. Executar validacao manual visual da P8 com ticker real (ex.: NVDA, AAPL, PETR4):
   - watchlist por clique (consulta via UI)
   - filtro por fonte no feed
   - ordenacao/paginacao do feed
   - visualizacoes por periodo (sentimento e eventos)
   - exportacao CSV por botao
   - cards de tendencia social
   - dialog de identidade (persistencia no `localStorage`)
5. (Opcional) iniciar testes de integracao frontend/backend em ambiente controlado.

## Arquivo de continuidade
Use `PROXIMA_SESSAO_P8.md` como checklist operacional da proxima janela.
