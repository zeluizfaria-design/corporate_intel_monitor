# Corporate Intelligence Monitor - Handoff Completo
**Data:** 2026-03-06  
**Estado geral:** P1-P7, P9 e P10 concluidos. P8 (Frontend React) encerrada formalmente em 2026-03-06 com validacao manual `APROVADO`, apos revalidacao tecnica final (`scripts/run_ci.ps1` OK, backend `24/24`, frontend `14/14` + build, smoke HTTP real OK).

## Leitura rapida para nova janela
- Snapshot curto: `RESUMO_CONTEXTO_JANELA.md`
- Checklist operacional: `PROXIMA_SESSAO_P8.md`

---

## 1. Caminho oficial do projeto
`C:\Users\Jose\.claude\projects\corporate_intel_monitor\`

Sempre usar o caminho em `C:` para desenvolvimento.

---

## 2. O que esta pronto hoje

### Backend
- Pipeline principal funcionando (`main.py`) com coletores, NLP e DuckDB.
- API FastAPI com endpoints de artigos, resumo, coleta, watchlist, alertas e exportacao CSV.
- Endpoints sociais:
  - `GET /social/sources`
  - `GET /social/{ticker}/summary?days=7`
- Ajuste de robustez no `StockTwitsCollector` com headers browser-like para reduzir erro 403.

### Frontend (P8)
Pasta `frontend/` com base Vite + React + TypeScript, incluindo:
- `frontend/package.json`
- `frontend/vite.config.ts`
- `frontend/src/main.tsx`
- `frontend/src/App.tsx`
- `frontend/src/api.ts`
- `frontend/src/types.ts`
- `frontend/src/components/ErrorBoundary.tsx`
- `frontend/src/index.css`
- `frontend/src/App.test.tsx`
- `frontend/src/test/setup.ts`

Funcionalidades implementadas na SPA:
- Consulta por ticker e janela de dias.
- Filtro por `source_type` no feed.
- Trigger de coleta (`POST /collect`).
- Exportacao CSV por botao da interface.
- Cards de resumo e feed de artigos.
- Cards de tendencia social por fonte.
- Watchlist na UI (listar/adicionar/remover) com clique para consultar ticker.
- Painel de fontes sociais (gratuitas vs credenciais).
- Dialog "Identidade de login" para email de apoio (Gmail/alias), salvo localmente via `localStorage`.
- Ordenacao de feed (`mais recentes`, `mais antigos`, `fonte`, `titulo`).
- Paginacao de feed (20 itens/pagina).
- Visualizacoes por periodo:
  - sentimento diario
  - eventos no periodo
- Loading granular por painel com `Promise.allSettled`.
- Polling de coleta no frontend com `POST /collect` + `GET /collect/{job_id}` ate status final.
- Card de status da coleta na UI com estado (`queued/running/completed/failed`), `job_id`, ticker, janela e timestamps.
- Acao manual `Atualizar status` para reconsultar o mesmo `job_id` apos timeout/falha sem disparar novo job.
- Aviso visual de sucesso parcial quando a coleta finaliza `completed` com `collector_failures` no resumo.

### Testes de frontend
- Vitest + React Testing Library configurados.
- Suite atual cobrindo:
  - carregamento do dashboard
  - paginacao do feed
  - filtro por `source_type`
  - exportacao CSV
  - watchlist (adicionar, consultar por clique e remover)
  - degradacao parcial com erro em endpoint especifico
  - erros de `POST/DELETE` da watchlist
  - coleta com polling por `job_id` (sucesso e falha)
  - erro ao consultar status de coleta (`GET /collect/{job_id}` com falha)
  - timeout de polling quando job permanece em `running`
  - recuperacao via `Atualizar status` apos timeout, concluindo no mesmo `job_id`
  - sucesso parcial de coleta (`completed` com `collector_failures`) com aviso explicito na UI
- Comandos:
  - `npm run test` (watch)
  - `npm run test:run` (CI/local one-shot)
- Revalidacao adicional desta janela:
  - `npm run test:run` => `14/14` passando
  - `npm run build` => sucesso
- Observacao de ambiente (shell atual):
  - pode ocorrer `EPERM`/`spawn EPERM` em `esbuild` durante `npm ci` ou execucao de scripts no sandbox; no ambiente desta janela, a validacao frontend foi concluida com execucao escalada.

### Testes backend (novos)
- Suite de integracao: `tests/test_api_integration.py`
  - valida endpoints principais (`/health`, artigos/resumo, social, watchlist, export CSV)
  - valida fluxo de coleta com `job_id` em sucesso e falha (`POST /collect` + `GET /collect/{job_id}`)
  - valida job `completed` com falhas parciais em `collector_failures`
  - valida `404` para `job_id` inexistente em `GET /collect/{job_id}`
- Suite de resiliencia: `tests/test_base_collector_resilience.py`
  - valida retry/backoff em `BaseCollector._get` para `429/5xx`, timeout/transport, no-retry em `404`
- Suite de background tasks: `tests/test_api_background_tasks.py`
  - valida logging e transicao de estado (`completed`/`failed`) em `_run_collection_bg`
  - valida execucao resiliente quando `_run_collection_bg` recebe `job_id` inexistente
- Execucao combinada:
  - `python -m unittest tests.test_base_collector_resilience tests.test_api_integration tests.test_api_background_tasks -v`
  - resultado atual: `24/24` testes passando
  - inclui cenarios E2E de resiliencia com indisponibilidade parcial real:
    - falha parcial social
    - falha parcial betting
    - degradacao multipla social + betting
    - degradacao multipla total dos coletores secundarios

### CI
- Pipeline local:
  - `scripts/run_ci.ps1`
  - roda frontend (`npm ci`, `test:run`, `build`) + backend tests (`unittest`)
- Pipeline remoto:
  - `.github/workflows/ci.yml`
  - dispara em `push` e `pull_request`
  - roda o mesmo fluxo (frontend + backend)
  - backend deps de CI incluem `pdfplumber`, `selectolax` e `feedparser` para estabilidade dos imports de coletores

### Runtime frontend validado
- Node.js LTS instalado: `v24.14.0`.
- npm instalado: `11.9.0`.
- `npm install` executado com sucesso em `frontend/`.
- `npm run test:run` executado com sucesso em `frontend/`.
- `npm run build` executado com sucesso em `frontend/`.
- `npm audit --json` executado com sucesso em `frontend/` com `0 vulnerabilidades`.
- Ajuste de seguranca aplicado com `overrides.esbuild` em `frontend/package.json`.

---

## 3. Diretrizes externas incorporadas

Fontes consultadas (fornecidas pelo usuario):
- `Relatorio de Pesquisa.docx`
- `Seguranca de Acesso a Portais Financeiros.pdf`

Aplicacao no projeto:
- Compliance/pesquisa: priorizar APIs oficiais/publicas, transparencia de finalidade e rate limiting.
- Seguranca: nao expor segredos no frontend; credenciais no backend/cofre de segredos.
- Gmail no frontend: permitido apenas como identificador de apoio (sem senha, token, cookie, MFA).

---

## 4. Lacunas atuais para a proxima janela

1. Sem lacunas abertas da P8 (frontend) apos sign-off `APROVADO` em 2026-03-06.
2. Proximas janelas devem focar apenas em evolucao de roadmap pos-P8.

---

## 5. Comandos de retomada

```bash
cd "C:\Users\Jose\.claude\projects\corporate_intel_monitor"

# Backend
uvicorn api.main:app --host 0.0.0.0 --port 8000

# Frontend
cd frontend
npm install
npm run test:run
npm run dev

# CI local completo
cd ..
powershell -ExecutionPolicy Bypass -File .\scripts\run_ci.ps1
```

Observacao:
- Dependencias Python (`fastapi`, `uvicorn`) ja estao instaladas no ambiente atual.
- Se `node`/`npm` nao forem reconhecidos no shell, usar caminho completo `C:\Program Files\nodejs\npm.cmd`.
- Para iteracao rapida sem reinstalar pacotes frontend: `.\scripts\run_ci.ps1 -SkipNpmCi`.

---

## 6. API relevante para o frontend

- `GET /health`
- `GET /articles/{ticker}?days=7`
- `GET /articles/{ticker}/summary?days=7`
- `POST /collect`
- `GET /collect/{job_id}`
- `GET /social/sources`
- `GET /social/{ticker}/summary?days=7`
- `GET /watchlist`
- `POST /watchlist`
- `DELETE /watchlist/{ticker}`
- `GET /export/{ticker}?days=30`

---

## 7. Riscos e observacoes

- Smoke tecnico E2E da P8 executado com sucesso em 2026-03-06:
  - backend/health OK
  - frontend/Vite OK
  - sociais (`/social/sources`, `/social/{ticker}/summary`) OK
  - watchlist (`GET/POST/DELETE`) OK
  - filtro `source_type` no feed OK
  - coleta (`POST /collect`) OK
  - exportacao CSV (`GET /export/{ticker}`) OK
- Testes de componente atualizados para 14 cenarios, cobrindo sucesso e erro dos fluxos principais da P8 incluindo polling de coleta, timeout, reconsulta manual e sucesso parcial.
- `npm audit` zerado (0 vulnerabilidades) apos fix de cadeia `vite/esbuild`.
- Repositorio Git inicializado (`main`) com `origin` configurado e sincronizado com GitHub.

---

## 8. Estado Git

- Branch atual: `main`
- Remoto configurado:
  - `origin` -> `https://github.com/zeluizfaria-design/corporate_intel_monitor.git`
- `main` sincronizada com `origin/main`.
- CI remoto executando automaticamente e verde nos commits recentes (`03f19b5`, `51f9d76`, `a2d93cb`, `2df300e`, `8093e88`, `382da20`).

---

## 9. Proxima acao recomendada

Executar checklist de validacao manual em `PROXIMA_SESSAO_P8.md` para fechar a P8 com foco na UX visual do polling de status por `job_id` ja implementado.

## 10. Guia rapido para nova janela de contexto
1. Ler `RESUMO_CONTEXTO_JANELA.md` e `PROXIMA_SESSAO_P8.md`.
2. Subir backend e frontend pelos comandos da secao 5.
3. Rodar checklist manual de UX (secao "Smoke tests manuais").
4. Registrar resultado final no `CONTEXTO_SESSAO.md`.
