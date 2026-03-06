# Proxima Sessao - Etapa P8 (Frontend React)

## Entrada recomendada
- Ler primeiro `RESUMO_CONTEXTO_JANELA.md` para snapshot da retomada.

## Objetivo
Executar apenas o sign-off visual/manual final em browser para encerramento formal da P8.

## Status da execucao (2026-03-06)
- Validacao final desta continuidade:
  - `powershell -ExecutionPolicy Bypass -File .\scripts\run_ci.ps1` -> pipeline completo OK.
  - backend `24/24` passando.
  - frontend `14/14` passando + build OK.
  - smoke HTTP reexecutado com processos reais:
    - `/health` -> `200`
    - `/social/sources` -> `200`
    - `/articles/NVDA/summary?days=7` -> `200`
    - `/export/NVDA?days=7` -> `200`
    - frontend `/` -> `200` (`text/html`)
- Revalidacao de fechamento desta janela:
  - backend: `python -m unittest tests.test_base_collector_resilience tests.test_api_integration tests.test_api_background_tasks -v` -> `24/24` passando.
  - frontend: `npm run test:run` -> `14/14` passando; `npm run build` -> OK.
  - observacao de ambiente do shell atual: pode ocorrer `EPERM` em `esbuild` dentro de sandbox (validacao frontend concluida com execucao escalada nesta janela).
- Smoke tecnico E2E concluido com sucesso via execucao local de backend + frontend.
- Revalidacao tecnica adicional concluida:
  - `npm run test:run` (14 testes) OK
  - `npm run build` OK
  - smoke HTTP com processos reais (`uvicorn` + `vite`) OK em `/health`, `/social/sources`, `/articles/NVDA/summary`, `/export/NVDA` e `/` do frontend
- Backlog tecnico da P8 concluido:
  - item 1: ordenacao/paginacao do feed
  - item 2: visualizacoes de eventos e sentimento por periodo
  - item 3: estados de carregamento granulares por painel
  - item 4: testes automatizados de componentes (Vitest + RTL)
- `npm run test:run` executado com sucesso (14 testes passando).
- `npm audit --json` executado com sucesso (0 vulnerabilidades).
- Repositorio publicado no GitHub (`origin`: `https://github.com/zeluizfaria-design/corporate_intel_monitor.git`) com CI remoto verde em `main`.
- Pendencia remanescente: validacao manual visual humana em browser para UX/interacoes.
- Evolucao backend nesta janela:
  - `POST /collect` retorna `job_id`.
  - novo endpoint `GET /collect/{job_id}` com status de execucao (`queued`, `running`, `completed`, `failed`), erro e resumo.
  - retencao automatica de jobs em memoria no `POST /collect` (TTL 24h para jobs finalizados + limite de 500 entradas).
  - suites backend atualizadas para `24/24` passando (`test_base_collector_resilience`, `test_api_integration`, `test_api_background_tasks`).
  - cobertura E2E de resiliencia ampliada em `tests/test_api_integration.py`:
    - falha parcial real em social
    - falha parcial real em betting
    - degradacao multipla social + betting
    - degradacao multipla total (secundarios indisponiveis, `saved_articles=0`)
- Evolucao frontend nesta janela:
  - polling de `GET /collect/{job_id}` integrado no fluxo do botao `Coletar agora`.
  - card de status da coleta na UI (estado, `job_id`, ticker, janela e timestamps).
  - tratamento de erro para falha de status/polling no frontend com feedback explicito.
  - acao manual `Atualizar status` para reconsultar o mesmo `job_id` apos timeout/falha.
  - aviso de `sucesso parcial` na UI quando job finaliza `completed` com `collector_failures`.

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
- Se a porta `5173` estiver ocupada, o Vite sobe automaticamente em `5174` (ajustar URL de validacao manual).

## Smoke tests manuais (fechamento UX)
- Abrir `http://localhost:5173`
- Consultar `NVDA` com 7 dias
- Clicar `Coletar agora`
- Validar fluxo de status de coleta no backend:
  - capturar `job_id` retornado no `POST /collect`
  - consultar `GET /collect/{job_id}` e confirmar transicao de status ate `completed` (ou `failed` com `error`)
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
- Fluxo de coleta permite observabilidade de status por `job_id` sem erro no backend, incluindo reconsulta manual na UI.
- Fluxo de coleta sinaliza `sucesso parcial` quando aplicavel (job `completed` com `collector_failures`).
- Watchlist funciona (listar/adicionar/remover + clique para consultar).
- Filtro por `source_type` altera o feed conforme esperado.
- Ordenacao e paginacao do feed funcionam conforme esperado.
- Visualizacoes por periodo mostram dados coerentes com o feed.
- Loading granular aparece por painel durante atualizacoes.
- Exportacao CSV abre download com dados do ticker selecionado.
- Dialog de identidade persiste email localmente e nao solicita senha/token.
- `npm run test:run` passa sem falhas.

## Proximo backlog apos fechamento da P8
1. Executar validacao manual visual final da UX de coleta (transicao de status e legibilidade em desktop/mobile).
2. Manter CI local/remoto alinhados com as suites backend atuais (`24/24` baseline) e frontend (`14` testes).

## Saida esperada desta proxima janela (template de registro)
- Resultado da validacao manual P8: `APROVADO` ou `REPROVADO`.
- Evidencias executadas:
  - URL validada: `http://localhost:5173`
  - ticker(s) usados: `NVDA` (obrigatorio) + opcional (`AAPL`, `PETR4`)
  - comportamento do fluxo `Coletar agora`/polling (`job_id`) observado.
  - exportacao CSV, watchlist, filtro, ordenacao, paginacao, visualizacoes e loading granular validados.
- Se reprovado:
  - listar ajustes residuais com prioridade (`alta`, `media`, `baixa`) e impacto na UX.

## Publicacao no GitHub (status)
- Concluido:
  - remoto `origin` configurado
  - `main` publicada
  - workflow `CI` executando automaticamente com sucesso

## Notas de seguranca
- Nao colocar segredos no frontend.
- Tokens/cookies ficam no backend ou em cofre de segredos.
- Manter alias de email separado por plataforma quando possivel.
