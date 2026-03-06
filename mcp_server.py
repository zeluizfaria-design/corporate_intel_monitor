"""
Corporate Intelligence Monitor — MCP Server

Expõe o CIM como ferramentas para uso por prompts e aplicações Claude
neste computador. Registrado em ~/.claude/settings.json.

Ferramentas disponíveis:
  - cim_collect       : Coleta dados de uma empresa (ticker)
  - cim_query         : Consulta artigos salvos no banco
  - cim_summary       : Resumo de sentimento e eventos por ticker
  - cim_briefing      : Briefing executivo gerado pela Claude API
  - cim_dual_collect  : Coleta dupla listagem (B3 + NYSE/NASDAQ)
"""

import asyncio
import json
import sys
import os

# Garante que o projeto está no path
sys.path.insert(0, os.path.dirname(__file__))

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

from config.settings import Settings
from storage.database import Database

app = Server("corporate-intel-monitor")
_settings = Settings()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db() -> Database:
    return Database()


def _fmt_articles(articles: list[dict], max_items: int = 20) -> str:
    if not articles:
        return "Nenhum artigo encontrado."
    lines = []
    for a in articles[:max_items]:
        ts = str(a.get("published_at", ""))[:16]
        sentiment = a.get("sentiment_label", "?")
        compound = a.get("sentiment_compound", 0.0) or 0.0
        event = a.get("event_type", "outro")
        source = a.get("source", "?")
        title = a.get("title", "")[:120]
        url = a.get("url", "")
        lines.append(
            f"[{ts}] [{sentiment} {compound:+.2f}] [{event}] [{source}]\n"
            f"  {title}\n"
            f"  {url}"
        )
    total = len(articles)
    shown = min(max_items, total)
    return f"Mostrando {shown}/{total} artigos:\n\n" + "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: cim_collect
# ---------------------------------------------------------------------------

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:

    if name == "cim_collect":
        ticker = arguments.get("ticker", "").upper()
        days_back = int(arguments.get("days_back", 30))
        if not ticker:
            return [types.TextContent(type="text", text="Erro: parâmetro 'ticker' obrigatório.")]

        from main import run_collection
        from processors.sentiment import SentimentAnalyzer
        from storage.database import Database as DB

        db = DB()
        before = db._conn.execute(
            "SELECT COUNT(*) FROM articles WHERE company_ticker=?", [ticker]
        ).fetchone()[0]

        try:
            await run_collection(ticker, _settings, days_back=days_back)
        except Exception as e:
            return [types.TextContent(type="text", text=f"Coleta parcialmente concluída. Erro: {e}")]

        after = db._conn.execute(
            "SELECT COUNT(*) FROM articles WHERE company_ticker=?", [ticker]
        ).fetchone()[0]
        novos = after - before
        return [types.TextContent(
            type="text",
            text=f"Coleta concluída para {ticker}. Novos artigos inseridos: {novos} (total: {after})."
        )]

    # -----------------------------------------------------------------------
    elif name == "cim_dual_collect":
        br_ticker = arguments.get("br_ticker", "").upper()
        us_ticker = arguments.get("us_ticker", "").upper()
        days_back = int(arguments.get("days_back", 30))
        if not br_ticker or not us_ticker:
            return [types.TextContent(type="text", text="Erro: 'br_ticker' e 'us_ticker' são obrigatórios.")]

        from main import run_dual_listed
        try:
            await run_dual_listed(br_ticker, us_ticker, _settings, days_back=days_back)
        except Exception as e:
            return [types.TextContent(type="text", text=f"Erro na coleta dual: {e}")]
        return [types.TextContent(
            type="text",
            text=f"Coleta dual concluída: {br_ticker} (CVM) + {us_ticker} (SEC EDGAR)."
        )]

    # -----------------------------------------------------------------------
    elif name == "cim_query":
        ticker = arguments.get("ticker", "").upper()
        days = int(arguments.get("days", 7))
        source_type = arguments.get("source_type")  # opcional: news | fato_relevante | social | betting
        limit = int(arguments.get("limit", 20))

        if not ticker:
            return [types.TextContent(type="text", text="Erro: parâmetro 'ticker' obrigatório.")]

        db = _db()
        source_types = [source_type] if source_type else None
        articles = db.query_by_ticker(ticker, days=days, source_types=source_types)
        return [types.TextContent(type="text", text=_fmt_articles(articles, max_items=limit))]

    # -----------------------------------------------------------------------
    elif name == "cim_summary":
        ticker = arguments.get("ticker", "").upper()
        days = int(arguments.get("days", 7))

        if not ticker:
            return [types.TextContent(type="text", text="Erro: parâmetro 'ticker' obrigatório.")]

        db = _db()
        articles = db.query_by_ticker(ticker, days=days)
        if not articles:
            return [types.TextContent(
                type="text",
                text=f"Nenhum dado para {ticker} nos últimos {days} dias. Execute cim_collect primeiro."
            )]

        sentiment_counts: dict[str, int] = {}
        event_counts: dict[str, int] = {}
        source_counts: dict[str, int] = {}
        compounds = []

        for a in articles:
            lbl = (a.get("sentiment_label") or "NEUTRAL").upper()
            sentiment_counts[lbl] = sentiment_counts.get(lbl, 0) + 1

            ev = a.get("event_type") or "outro"
            event_counts[ev] = event_counts.get(ev, 0) + 1

            src = a.get("source") or "?"
            source_counts[src] = source_counts.get(src, 0) + 1

            c = a.get("sentiment_compound")
            if c is not None:
                compounds.append(float(c))

        avg = sum(compounds) / len(compounds) if compounds else 0.0
        overall = "POSITIVO" if avg > 0.1 else "NEGATIVO" if avg < -0.1 else "NEUTRO"

        top_events = sorted(event_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        top_sources = sorted(source_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        summary = (
            f"# Resumo CIM — {ticker} (últimos {days} dias)\n\n"
            f"**Total de artigos:** {len(articles)}\n"
            f"**Sentimento geral:** {overall} (compound médio: {avg:+.3f})\n\n"
            f"**Distribuição de sentimento:**\n"
            + "\n".join(f"  - {k}: {v}" for k, v in sorted(sentiment_counts.items()))
            + f"\n\n**Top eventos detectados:**\n"
            + "\n".join(f"  - {e}: {c}" for e, c in top_events)
            + f"\n\n**Principais fontes:**\n"
            + "\n".join(f"  - {s}: {c}" for s, c in top_sources)
        )
        return [types.TextContent(type="text", text=summary)]

    # -----------------------------------------------------------------------
    elif name == "cim_briefing":
        ticker = arguments.get("ticker", "").upper()
        days = int(arguments.get("days", 1))
        api_key = arguments.get("anthropic_api_key") or _settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")

        if not ticker:
            return [types.TextContent(type="text", text="Erro: parâmetro 'ticker' obrigatório.")]
        if not api_key:
            return [types.TextContent(
                type="text",
                text="Erro: ANTHROPIC_API_KEY não configurada. Adicione ao .env ou passe como parâmetro."
            )]

        db = _db()
        articles = db.query_by_ticker(ticker, days=days)
        if not articles:
            return [types.TextContent(
                type="text",
                text=f"Sem dados para {ticker} nos últimos {days} dias. Execute cim_collect primeiro."
            )]

        content_block = "\n\n".join(
            f"[{a.get('source_type','').upper()} | {a.get('source','')}] "
            f"[{a.get('sentiment_label','?')} {(a.get('sentiment_compound') or 0):+.2f}] "
            f"[{a.get('event_type','outro')}]\n"
            f"{a.get('title','')}\n"
            f"{(a.get('content') or '')[:300]}"
            for a in articles[:25]
        )

        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": (
                    f"Você é um analista de mercado sênior. Com base nas informações coletadas "
                    f"sobre {ticker} nas últimas {days*24}h, produza um briefing executivo conciso com:\n"
                    f"1. Principais eventos e notícias\n"
                    f"2. Sentimento geral do mercado\n"
                    f"3. Pontos de atenção críticos\n"
                    f"4. Probabilidades implícitas dos mercados de previsão (se disponível)\n\n"
                    f"Dados coletados:\n\n{content_block}"
                )
            }]
        )
        return [types.TextContent(type="text", text=response.content[0].text)]

    else:
        return [types.TextContent(type="text", text=f"Ferramenta desconhecida: {name}")]


# ---------------------------------------------------------------------------
# Tool listing
# ---------------------------------------------------------------------------

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="cim_collect",
            description=(
                "Coleta dados de inteligência corporativa para um ticker: fatos relevantes (CVM/SEC EDGAR), "
                "notícias (14 portais), redes sociais e mercados de apostas/previsão. "
                "Armazena tudo no banco local DuckDB. Use antes de cim_query ou cim_briefing."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Ticker da empresa. Ex: AAPL, PETR4, VALE3"},
                    "days_back": {"type": "integer", "description": "Janela de coleta em dias (padrão: 30)", "default": 30},
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="cim_dual_collect",
            description=(
                "Coleta dados de empresa com dupla listagem: ticker B3 (CVM) + ticker NYSE/NASDAQ (SEC EDGAR 6-K). "
                "Exemplos: VALE3/VALE, PETR4/PBR, ITUB4/ITUB."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "br_ticker": {"type": "string", "description": "Ticker B3. Ex: VALE3"},
                    "us_ticker": {"type": "string", "description": "Ticker NYSE/NASDAQ. Ex: VALE"},
                    "days_back": {"type": "integer", "default": 30},
                },
                "required": ["br_ticker", "us_ticker"],
            },
        ),
        types.Tool(
            name="cim_query",
            description=(
                "Consulta artigos já coletados no banco local para um ticker. "
                "Retorna título, fonte, sentimento, tipo de evento e URL."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Ticker da empresa"},
                    "days": {"type": "integer", "description": "Janela de consulta em dias (padrão: 7)", "default": 7},
                    "source_type": {
                        "type": "string",
                        "description": "Filtrar por tipo: news | fato_relevante | social | betting",
                        "enum": ["news", "fato_relevante", "social", "betting"],
                    },
                    "limit": {"type": "integer", "description": "Máximo de artigos retornados (padrão: 20)", "default": 20},
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="cim_summary",
            description=(
                "Retorna resumo estatístico de sentimento e eventos para um ticker: "
                "distribuição POSITIVE/NEGATIVE/NEUTRAL, compound médio, top eventos e fontes."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "days": {"type": "integer", "default": 7},
                },
                "required": ["ticker"],
            },
        ),
        types.Tool(
            name="cim_briefing",
            description=(
                "Gera um briefing executivo em português sobre a empresa usando a Claude API. "
                "Sintetiza os dados coletados em: principais eventos, sentimento de mercado, "
                "pontos de atenção e probabilidades implícitas. Requer ANTHROPIC_API_KEY no .env."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "days": {"type": "integer", "description": "Janela de dados para o briefing (padrão: 1 dia)", "default": 1},
                    "anthropic_api_key": {"type": "string", "description": "Opcional: sobrescreve a chave do .env"},
                },
                "required": ["ticker"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
