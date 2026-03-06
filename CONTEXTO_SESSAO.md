# Corporate Intelligence Monitor - Contexto de Sessao
> Atualizado em 2026-03-06 (janela mais recente) para retomada em nova janela de contexto.

## Como usar este arquivo na proxima janela
1. Ler primeiro `RESUMO_CONTEXTO_JANELA.md` para snapshot rapido.
2. Usar este arquivo para historico consolidado e evidencias tecnicas.
3. Executar o checklist operacional em `PROXIMA_SESSAO_P8.md`.

## Estado resumido
- Backend funcional (coletores + NLP + DuckDB + API).
- P8 avancou no frontend React/TS com backlog tecnico imediato implementado na UI.
- Endpoints sociais para a UI adicionados (`/social/sources` e `/social/{ticker}/summary`).
- Dialog de identidade de login (email de apoio) implementado no frontend com armazenamento local.
- Runtime Node.js/npm instalado e frontend compilando em build de producao.
- Testes de componentes configurados com Vitest + React Testing Library.

## Mudancas aplicadas nesta sessao

### Atualizacao de continuidade (fechamento tecnico revalidado em 2026-03-06)
- Pipeline local completo reexecutado com sucesso:
  - comando: `powershell -ExecutionPolicy Bypass -File .\scripts\run_ci.ps1`
  - frontend: `npm ci` + `npm run test:run` + `npm run build` OK
  - backend: `python -m unittest tests.test_base_collector_resilience tests.test_api_integration tests.test_api_background_tasks -v` com `24/24` testes passando
- Smoke de integracao com processos reais reexecutado com sucesso:
  - `GET /health` -> `200`
  - `GET /social/sources` -> `200`
  - `GET /articles/NVDA/summary?days=7` -> `200`
  - `GET /export/NVDA?days=7` -> `200` (`text/csv`)
  - frontend `/` -> `200` (`text/html`)
- Observacoes operacionais:
  - neste ambiente, `npm ci` e `vite dev` podem falhar com `spawn EPERM` em sandbox; execucao escalada contorna.
  - em parte das execucoes o Vite pode subir em `5174` quando `5173` ja estiver ocupada.
- Conclusao da continuidade:
  - fechamento tecnico da P8 mantido como aprovado.
  - resta somente o sign-off visual/manual humano em browser para encerramento formal.

### Atualizacao incremental desta janela (retencao de jobs de coleta)
- Backend (`api/main.py`):
  - adicionada limpeza automatica de `_collection_jobs` no `POST /collect`.
  - politica de retencao aplicada:
    - remover jobs finalizados (`completed`/`failed`) com mais de 24h.
    - limitar armazenamento em memoria para no maximo 500 jobs (remove os mais antigos em overflow).
  - objetivo: evitar crescimento indefinido do estado em memoria da API em execucoes prolongadas.
- Testes adicionados/ajustados:
  - `tests/test_api_background_tasks.py`:
    - `test_cleanup_collection_jobs_removes_old_finished_jobs`.
  - `tests/test_api_integration.py`:
    - `test_collect_trigger_cleans_stale_finished_jobs`.
- Revalidacao tecnica desta continuidade:
  - backend:
    - `python -m unittest tests.test_base_collector_resilience tests.test_api_integration tests.test_api_background_tasks -v`
    - resultado: `20/20` testes passando.
  - frontend (execucao escalada devido `spawn EPERM` do `esbuild` no sandbox):
    - `npm.cmd run test:run` -> `14/14` passando.
    - `npm.cmd run build` -> sucesso.

### Atualizacao incremental desta janela (cenarios E2E de indisponibilidade parcial real)
- Backend (integracao API + fluxo real de coleta):
  - novo cenario E2E integrado em `tests/test_api_integration.py` para indisponibilidade parcial real de coletores sociais:
    - executa `POST /collect` com `run_collection` real.
    - simula um coletor social saudavel e outro indisponivel.
    - valida `GET /collect/{job_id}` com status final `completed` e `collector_failures` preenchido.
  - novo cenario E2E integrado para indisponibilidade parcial real de coletores de betting:
    - executa `POST /collect` com `run_collection` real.
    - simula um coletor de betting saudavel e outro indisponivel.
    - valida `GET /collect/{job_id}` com status final `completed` e falha parcial registrada.
- Resultado tecnico:
  - `python -m unittest tests.test_base_collector_resilience tests.test_api_integration tests.test_api_background_tasks -v`
  - baseline atualizada para `24/24` testes backend passando.
  - cobertura adicional:
    - degradacao multipla (falha simultanea social + betting) com job `completed` e duas entradas em `collector_failures`.
    - degradacao multipla total dos coletores secundarios (social + betting indisponiveis) com `saved_articles=0` e status final `completed`.

### Atualizacao de fechamento desta janela (2026-03-06)
- Revalidacao backend executada novamente com sucesso:
  - `python -m unittest tests.test_base_collector_resilience tests.test_api_integration tests.test_api_background_tasks -v`
  - resultado: `18/18` testes passando.
- Revalidacao frontend executada novamente com sucesso:
  - `npm run test:run` -> `14/14` testes passando.
  - `npm run build` -> build de producao concluido.
- Observacao de ambiente desta janela (shell/sandbox):
  - `npm ci` pode falhar com `EPERM` em `esbuild` por lock/restricao de execucao local.
  - no ambiente atual, foi necessario executar validacoes frontend em modo escalado para contornar `spawn EPERM` do `esbuild`.
- Estado de fechamento:
  - pendente apenas validacao visual/manual em browser para encerramento formal da UX da P8.

### Atualizacao final desta janela (resiliencia UX + cobertura)
- Frontend:
  - card de status de coleta agora explicita `sucesso parcial` quando o job termina como `completed` com `collector_failures` no `summary`.
  - novo aviso visual: "Coleta concluida com falhas parciais em N coletor(es)".
  - testes frontend atualizados para `14/14` (Vitest), incluindo cenario de coleta concluida com falhas parciais.
- Backend (integracao API):
  - novo cenario em `tests/test_api_integration.py` para job `completed` com `collector_failures` (sem promover para `failed`).
  - baseline backend atualizada para `18/18` testes passando:
    - `python -m unittest tests.test_base_collector_resilience tests.test_api_integration tests.test_api_background_tasks -v`

### Atualizacao incremental desta janela (polling + resiliencia adicional)
- Frontend:
  - polling do status de coleta por `job_id` integrado no fluxo `Coletar agora`.
  - card dedicado de status da coleta (estado, `job_id`, ticker, janela e timestamps).
  - acao manual `Atualizar status` no card de coleta para reconsultar o mesmo `job_id` sem iniciar novo job.
  - tratamento explicito de erro quando `GET /collect/{job_id}` falha durante polling.
  - testes frontend atualizados para `14/14` (Vitest), cobrindo sucesso/falha do polling, erro no endpoint de status, timeout de polling, recuperacao via reconsulta manual e sucesso parcial.
- Backend (integracao API):
  - novos cenarios em `tests/test_api_integration.py`:
    - job finalizado com `failed` quando coletor levanta excecao.
    - `GET /collect/{job_id}` com job inexistente retornando `404`.
  - novo cenario em `tests/test_api_background_tasks.py`:
    - execucao de `_run_collection_bg` sem job registrado (nao quebra e mantem logging).
  - baseline backend atualizada para `18/18` testes passando:
    - `python -m unittest tests.test_base_collector_resilience tests.test_api_integration tests.test_api_background_tasks -v`

### Atualizacao desta janela (publicacao + resiliencia E2E)
- Repositorio publicado no GitHub:
  - `origin`: `https://github.com/zeluizfaria-design/corporate_intel_monitor.git`
  - branch `main` sincronizada com `origin/main`.
- CI remoto em GitHub Actions validado com sucesso nos commits recentes:
  - `03f19b5` (`fix(collectors): lazy-load optional collector modules`)
  - `51f9d76` (`docs: update session context and p8 handoff checklist`)
  - `a2d93cb` (`feat(api): add resilient background collection summary and tests`)
  - `2df300e` (`test(api): avoid importing main module in background task tests`)
  - `8093e88` (`chore(ci): install feedparser in backend test dependencies`)
  - `382da20` (`feat(api): add collection job status endpoint and tracking`)
- Evolucao de resiliencia no backend:
  - `POST /collect` agora retorna `job_id`.
  - novo `GET /collect/{job_id}` para acompanhar status (`queued/running/completed/failed`), erro e resumo.
  - `_run_collection_bg` com tracking de status/timestamps.
- Cobertura de testes backend ampliada:
  - nova suite `tests/test_api_background_tasks.py`
  - `tests/test_api_integration.py` cobre fluxo de status de coleta por `job_id`
  - baseline atual: `18/18` testes backend passando.
- Pipeline local e remoto atualizados para incluir a nova suite de background task:
  - `scripts/run_ci.ps1`
  - `.github/workflows/ci.yml`
  - dependencias de CI backend incluem `pdfplumber`, `selectolax` e `feedparser`.

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
- `npm run test:run` concluido com sucesso (Vitest: 14 testes passando).
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
  - `npm run test:run`: sucesso (`14/14` testes passando).
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
- backend: install deps minimas de teste (`fastapi`, `uvicorn`, `duckdb`, `pydantic-settings`, `python-dotenv`, `httpx`, `pdfplumber`, `selectolax`, `feedparser`)
- backend tests: `python -m unittest tests.test_base_collector_resilience tests.test_api_integration tests.test_api_background_tasks -v`

## Estado Git/publicacao (2026-03-06)
- Repositorio publicado e sincronizado no GitHub.
- `origin` configurado para `https://github.com/zeluizfaria-design/corporate_intel_monitor.git`.
- Branch principal: `main` rastreando `origin/main`.
- CI remoto ativo e validado com sucesso em commits recentes.

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
