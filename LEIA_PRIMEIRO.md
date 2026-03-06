# Corporate Intelligence Monitor — Guia de Instalação

## O que é isso?

Sistema de raspagem e análise de inteligência corporativa que monitora empresas
coletando dados de múltiplas fontes (CVM, SEC EDGAR, notícias, redes sociais,
mercados de apostas) e processando com IA (FinBERT + Claude API).

Após instalado, fica disponível como **servidor MCP** no Claude Code / VS Code,
permitindo uso direto em prompts como:
- "Colete dados de AAPL e me dê um briefing"
- "Mostre o sentimento do mercado para PETR4 nos últimos 7 dias"

---

## Instalação rápida (Windows)

### Pré-requisitos
- Python 3.11 ou superior: https://python.org/downloads
- VS Code com extensão Claude Code

### Passos

1. **Execute o instalador:**
   ```
   Clique duas vezes em: install.bat
   ```
   Isso instala todas as dependências e registra o servidor MCP.

2. **Reinicie o VS Code** para o Claude Code carregar o servidor MCP.

3. **Teste:**
   ```bash
   python main.py AAPL
   ```
   Deve criar `data/corporate_intel.duckdb` e imprimir artigos coletados.

---

## Ferramentas MCP disponíveis após instalação

| Ferramenta | Descrição |
|-----------|-----------|
| `cim_collect` | Coleta dados de uma empresa (ticker) |
| `cim_dual_collect` | Coleta dupla listagem BR+US (ex: VALE3/VALE) |
| `cim_query` | Consulta artigos salvos no banco |
| `cim_summary` | Resumo de sentimento e eventos |
| `cim_briefing` | Briefing executivo via Claude API |

---

## Configuração de credenciais (opcional)

Edite o arquivo `.env` para ativar fontes adicionais:

```env
# Para briefings com IA (necessário para cim_briefing)
ANTHROPIC_API_KEY=sk-ant-...

# Para coleta de redes sociais
TWITTER_BEARER_TOKEN=...
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
```

Sem credenciais, o sistema coleta de fontes públicas:
CVM, SEC EDGAR, Yahoo Finance, Finviz, Seeking Alpha, TradingView, Polymarket.

---

## Uso via linha de comando

```bash
# Empresa americana
python main.py AAPL

# Empresa brasileira
python main.py PETR4

# Dupla listagem (B3 + NYSE)
python main.py VALE3 VALE

# API REST (acesso por qualquer aplicação)
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

---

## Estrutura de arquivos

```
corporate_intel_monitor/
├── install.bat              ← Execute primeiro
├── main.py                  ← Entry point
├── mcp_server.py            ← Servidor MCP para Claude Code
├── requirements.txt         ← Dependências
├── .env.example             ← Template de credenciais
├── collectors/              ← Coletores de dados
├── processors/              ← NLP e classificação
├── storage/                 ← Banco DuckDB
├── api/                     ← FastAPI REST
├── scheduler/               ← Coleta automática
├── models/finbert-pt-br/    ← Modelo FinBERT (incluído)
└── config/                  ← Configurações
```

---

## Modelo FinBERT incluído

O modelo de análise de sentimento financeiro (lucas-leme/FinBERT-PT-BR)
está incluído na pasta `models/finbert-pt-br/` — não é necessário baixá-lo.

## Pipeline CI local (frontend + backend)

Para validar rapidamente o projeto completo em ambiente local:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_ci.ps1
```

Opcao para pular reinstalacao de dependencias Node:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_ci.ps1 -SkipNpmCi
```

## CI remoto (GitHub Actions)

Workflow disponivel em `.github/workflows/ci.yml`, executado em:
- `push` (qualquer branch)
- `pull_request`

Etapas do workflow:
- Frontend: `npm ci` -> `npm run test:run` -> `npm run build`
- Backend: `python -m unittest tests.test_base_collector_resilience tests.test_api_integration -v`
