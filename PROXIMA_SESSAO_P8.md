# Proxima Sessao - Etapa P8 (Frontend React)

## Objetivo
Fechar a P8 com validacao visual/manual final em browser e registrar ajustes residuais.

## Status da execucao (2026-03-06)
- Smoke tecnico E2E concluido com sucesso via execucao local de backend + frontend.
- Revalidacao tecnica adicional concluida:
  - `npm run test:run` (8 testes) OK
  - `npm run build` OK
  - smoke HTTP com processos reais (`uvicorn` + `vite`) OK em `/health`, `/social/sources`, `/articles/NVDA/summary`, `/export/NVDA` e `/` do frontend
- Backlog tecnico da P8 concluido:
  - item 1: ordenacao/paginacao do feed
  - item 2: visualizacoes de eventos e sentimento por periodo
  - item 3: estados de carregamento granulares por painel
  - item 4: testes automatizados de componentes (Vitest + RTL)
- `npm run test:run` executado com sucesso (8 testes passando).
- `npm audit --json` executado com sucesso (0 vulnerabilidades).
- Repositorio Git inicializado em `main` com commits locais e CI remoto configurado em `.github/workflows/ci.yml`.
- Pendencia remanescente: validacao manual visual em browser para UX/interacoes.

## Checklist de bootstrap

1. Backend
```bash
cd "C:\Users\Jose\.claude\projects\corporate_intel_monitor"
uv pip install --system fastapi uvicorn
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

2. Frontend
```bash
cd "C:\Users\Jose\.claude\projects\corporate_intel_monitor\frontend"
npm install
npm run test:run
npm run dev
```
Observacao:
- Se PowerShell bloquear scripts, usar `npm.cmd run dev`.
- Se `npm`/`node` nao forem reconhecidos no shell, usar `C:\Program Files\nodejs\npm.cmd`.
- `npm run build` ja foi validado com sucesso em 2026-03-06.

## Smoke tests manuais (fechamento UX)
- Abrir `http://localhost:5173`
- Consultar `NVDA` com 7 dias
- Clicar `Coletar agora`
- Verificar painel social e feed
- Aplicar filtro por `source_type` e confirmar mudanca no feed
- Validar ordenacao do feed:
  - mais recentes
  - mais antigos
  - fonte A-Z
  - titulo A-Z
- Validar paginacao do feed:
  - indicador `Pagina X de Y`
  - botoes `Anterior/Proxima`
- Validar visualizacoes por periodo:
  - sentimento diario com barras
  - eventos no periodo com ranking
- Exportar CSV e validar download
- Adicionar ticker na watchlist, consultar por clique e remover ticker
- Verificar cards de tendencia social por fonte
- Abrir dialog `Identidade de login` e salvar alias de email
- Durante nova consulta, confirmar estados de loading por painel (sem travar toda a tela)

## Criterios de aceite da P8 (final)
- UI carrega sem erro fatal.
- Consulta de ticker retorna resumo + artigos.
- Endpoints sociais aparecem na interface.
- Fluxo de coleta manual funciona sem quebrar a UI.
- Watchlist funciona (listar/adicionar/remover + clique para consultar).
- Filtro por `source_type` altera o feed conforme esperado.
- Ordenacao e paginacao do feed funcionam conforme esperado.
- Visualizacoes por periodo mostram dados coerentes com o feed.
- Loading granular aparece por painel durante atualizacoes.
- Exportacao CSV abre download com dados do ticker selecionado.
- Dialog de identidade persiste email localmente e nao solicita senha/token.
- `npm run test:run` passa sem falhas.

## Proximo backlog apos fechamento da P8
1. Integracao automatizada iniciada: suite backend (`tests/test_api_integration.py`) ativa e passando (`python -m unittest tests.test_api_integration -v`).
2. Resiliencia backend iniciada com testes unitarios de retry/backoff (`tests/test_base_collector_resilience.py`) e `BaseCollector._get` atualizado.
3. Pipeline CI local implementado em `scripts/run_ci.ps1` e validado (frontend + backend).
4. CI remoto portado para GitHub Actions em `.github/workflows/ci.yml` (push + pull_request).
5. Evoluir para cenarios de resiliencia E2E de ponta a ponta (indisponibilidade parcial de coletores/endpoints em execucao integrada).

## Publicacao no GitHub (pendente)
1. Configurar remoto:
   - `git remote add origin <URL_DO_REPOSITORIO_GITHUB>`
2. Publicar branch:
   - `git push -u origin main`
3. Confirmar no GitHub Actions a execucao do workflow `CI`.

## Notas de seguranca
- Nao colocar segredos no frontend.
- Tokens/cookies ficam no backend ou em cofre de segredos.
- Manter alias de email separado por plataforma quando possivel.
