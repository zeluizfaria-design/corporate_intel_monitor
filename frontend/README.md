# Frontend React (Etapa P8)

SPA React + TypeScript para o Corporate Intelligence Monitor.

## Objetivo desta etapa

- Dashboard unico para artigos, resumo de sentimento e feed social.
- Visibilidade de fontes sociais gratuitas x fontes com credencial.
- Consumo via backend/proxy, sem exposicao de segredos no browser.
- Caixa de dialogo "Identidade de login" para salvar localmente um Gmail/alias de pesquisa.

## Como rodar

1. Inicie a API FastAPI na raiz do projeto:

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

2. No frontend:

```bash
cd frontend
npm install
npm run dev
```

Acesse `http://localhost:5173`.

## Diretrizes aplicadas

- Pesquisa/compliance: uso explicito de API publica quando disponivel, respeito a rate limits e transparencia de origem.
- Seguranca: credenciais nunca no frontend; usar cofre de segredos (Vault/Doppler/Secrets Manager) no backend.
- Escopo atual: P8 inicial com observabilidade social e backlog imediato de UX ja incorporado.

## Funcionalidades atuais da SPA

- Consulta por ticker e janela de dias.
- Filtro por `source_type` no feed.
- Trigger de coleta (`POST /collect`).
- Exportacao CSV por botao na interface.
- Cards de resumo e feed de artigos.
- Cards de tendencia social por fonte.
- Watchlist na UI (listar/adicionar/remover) com clique para consultar ticker.
- Painel de fontes sociais (gratuitas vs credenciais).
- Error Boundary de UI.
- Dialog "Identidade de login" para email de apoio (Gmail/alias), salvo em `localStorage`.

## Notas sobre Gmail no fluxo

- O email informado na dialog e salvo apenas em `localStorage` no navegador.
- O frontend nao coleta senha, token, cookie, passkey ou MFA.
- Para producao, preferir alias dedicado por portal e passkeys/FIDO2 quando disponivel.
