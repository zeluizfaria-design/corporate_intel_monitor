# Resumo de Retomada - Nova Janela de Contexto
> Data de corte: 2026-03-06

## Estado atual
- Projeto em fase de encerramento da P8 (frontend React).
- Backend validado: `24/24` testes passando.
- Frontend validado: `14/14` testes passando + `npm run build` OK.
- CI local completo (`scripts/run_ci.ps1`) reexecutado com sucesso em 2026-03-06.
- Smoke HTTP com processos reais reexecutado com sucesso:
  - `GET /health` -> `200`
  - `GET /social/sources` -> `200`
  - `GET /articles/NVDA/summary?days=7` -> `200`
  - `GET /export/NVDA?days=7` -> `200`
  - frontend (`/`) -> `200` (`text/html`)
- Pendencia final: apenas sign-off visual/manual humano da UX em browser para fechamento formal da P8.

## O que ja esta implementado
- Polling de coleta por `job_id` (`POST /collect` + `GET /collect/{job_id}`) com card de status.
- Tratamento de timeout/erro de polling e acao manual `Atualizar status`.
- Aviso de sucesso parcial quando job finaliza `completed` com `collector_failures`.
- Watchlist, filtro por fonte, ordenacao/paginacao de feed, visualizacoes de periodo e exportacao CSV.
- Resiliencia E2E backend coberta para indisponibilidade parcial real de coletores:
  - falha parcial social
  - falha parcial betting
  - degradacao multipla (social + betting)
  - degradacao multipla total com `saved_articles=0` e job `completed`

## Evidencias tecnicas mais recentes
- Backend:
  - `python -m unittest tests.test_base_collector_resilience tests.test_api_integration tests.test_api_background_tasks -v`
  - Resultado: `24/24`.
- Frontend:
  - `npm run test:run`
  - Resultado: `14/14`.
  - `npm run build` concluido com sucesso.

## Observacao de ambiente (importante)
- Neste ambiente pode ocorrer `EPERM` / `spawn EPERM` do `esbuild` ao rodar `npm ci` ou scripts dentro de sandbox.
- Se ocorrer, usar execucao fora do sandbox ou manter cache local do npm e PATH explicito do Node.

## Proxima acao recomendada
1. Executar checklist de `PROXIMA_SESSAO_P8.md`.
2. Fazer sign-off visual manual dos fluxos da P8 em `http://localhost:5173` (ou `5174` se a porta principal estiver ocupada).
3. Registrar resultado final (aprovado/reprovado + ajustes residuais) no `CONTEXTO_SESSAO.md`.

## Roteiro minimo para outra janela
1. Abrir este arquivo e depois `PROXIMA_SESSAO_P8.md`.
2. Subir backend + frontend com os comandos de bootstrap do checklist.
3. Executar apenas os smoke tests manuais de UX.
4. Registrar o sign-off final no `CONTEXTO_SESSAO.md`.

## Ordem de leitura sugerida
1. `RESUMO_CONTEXTO_JANELA.md` (este arquivo)
2. `PROXIMA_SESSAO_P8.md`
3. `HANDOFF_COMPLETO.md`
4. `CONTEXTO_SESSAO.md`
