# Handoff: Insider & Politician Trading Collectors

## O que foi implementado

### 1. `collectors/insider_trading_collector.py`
Coleta transações de **Form 4** do SEC EDGAR (insiders: CEO, CFO, diretores, acionistas >10%).

**Como funciona:**
- Resolve CIK da empresa via `https://www.sec.gov/files/company_tickers.json`
- Busca submissions JSON do EDGAR para listar filings Form 4/4A
- Para cada filing: extrai URL do XML bruto (sem o prefixo XSLT `xslF345X05/`)
- Parseia o XML com `xml.etree.ElementTree` extraindo transações nonDerivative e derivative
- Emite um `RawArticle` por transação com `source_type="insider_trade"`

**Limitação conhecida:**
- TSM (Taiwan Semiconductor) é **Foreign Private Issuer** — não arquiva Form 4
  (FPIs usam 20-F/6-K e seus insiders são isentos do Section 16)
- Funciona para empresas americanas como NVDA, AAPL, MSFT, AMD

**Testado:**
- NVDA: retorna concessões e vendas de EVPs, CFO, General Counsel
- TSM: 0 resultados (esperado — empresa estrangeira)

### 2. `collectors/politician_trading_collector.py`
Coleta negociações de congressistas americanos (STOCK Act).

**Fonte primária:** Quiver Quantitative bulk endpoint (gratuito)
- URL: `https://api.quiverquant.com/beta/bulk/congresstrading`
- ~110k transações históricas, todos os campos: Chamber, Party, State, District, BioGuideID, Traded, Transaction, Trade_Size_USD, excess_return
- **Problema atual:** O endpoint retorna 401 intermitentemente (parece ter rate limiting por sessão ou IP)
- Quando retorna 200: TSM tem 142 transações, NVDA tem 610, AAPL tem 1073

**Pendente para a próxima sessão:**
1. Investigar o rate limiting do Quiver Quant:
   - Registrar API key gratuita em https://quiverquant.com e adicionar `QUIVER_API_KEY` ao `.env`
   - Adicionar o token como `Authorization: Token {key}` no header
   - Adicionar `quiver_api_key: str | None = None` em `config/settings.py`
   - Passar `settings` para `PoliticianTradingCollector` e usar a key quando disponível
2. Alternativa sem API key: Capitol Trades (https://capitoltrades.com) tem dados públicos via web scraping

### 3. `processors/event_classifier.py`
Adicionados 5 novos EventTypes:
- `insider_compra`, `insider_venda`, `insider_concessao`
- `politico_compra`, `politico_venda`

### 4. `main.py`
Integrado no `run_collection()` após betting collectors:
- `InsiderTradingCollector` — Form 4 EDGAR
- `PoliticianTradingCollector` — STOCK Act via Quiver Quant

## Próximos passos
1. Adicionar `QUIVER_API_KEY` ao `.env` e `config/settings.py`
2. Passar `settings` para `PoliticianTradingCollector.__init__`
3. Testar com `python main.py NVDA` (empresa americana, verifica Form 4 funcionando)
4. Para TSM: considerar scraping do 20-F para identificar major shareholders/insiders
5. Considerar adicionar coletor de dados da CVM-BR para insiders brasileiros

## Comandos de teste
```bash
cd C:\Users\José\.claude\projects\corporate_intel_monitor

# Teste Form 4 insiders (empresa americana)
python -c "
import asyncio
from collectors.insider_trading_collector import InsiderTradingCollector
async def t():
    async with InsiderTradingCollector() as c:
        count = 0
        async for art in c.collect('NVDA', days_back=30):
            print(art.title[:120])
            count += 1
            if count >= 5: break
asyncio.run(t())
" 2>/dev/null

# Teste políticos (quando Quiver Quant retornar 200)
python -c "
import asyncio
from collectors.politician_trading_collector import PoliticianTradingCollector
async def t():
    async with PoliticianTradingCollector() as c:
        count = 0
        async for art in c.collect('TSM', days_back=365):
            print(art.title[:120])
            count += 1
            if count >= 5: break
asyncio.run(t())
" 2>/dev/null

# Coleta completa
python main.py TSM 2>/dev/null
python main.py NVDA 2>/dev/null
```
