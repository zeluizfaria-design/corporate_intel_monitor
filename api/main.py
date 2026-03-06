"""FastAPI endpoints para o Corporate Intelligence Monitor."""
import io
import csv
import logging
from datetime import UTC, datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from config.settings import Settings
from storage.database import Database

app = FastAPI(
    title="Corporate Intelligence Monitor",
    description="API para consulta de inteligência corporativa coletada",
    version="1.0.0",
)

_db = Database()
_settings = Settings()

# Seed watchlist se estiver vazia
_db.seed_watchlist(_settings.target_tickers, _settings.dual_listed_map)


class ArticleResponse(BaseModel):
    id: str
    source: str
    source_type: str
    url: str
    title: str
    content: str
    published_at: datetime
    collected_at: datetime
    company_ticker: Optional[str]
    company_name: Optional[str]
    sentiment_label: Optional[str]
    sentiment_score: Optional[float]
    sentiment_compound: Optional[float]
    event_type: Optional[str]


class CollectionRequest(BaseModel):
    ticker: str
    days_back: int = 30


class WatchlistItem(BaseModel):
    ticker: str
    is_dual: bool = False
    us_ticker: Optional[str] = None


class SocialSourceStatus(BaseModel):
    source: str
    access_mode: str
    configured: bool
    enabled: bool
    security_notes: str
    compliance_notes: str


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(UTC).isoformat()}


@app.get("/articles/{ticker}", response_model=list[ArticleResponse])
def get_articles(
    ticker: str,
    days: int = Query(default=7, ge=1, le=365),
    source_type: Optional[str] = Query(default=None),
):
    """Retorna artigos coletados para um ticker nos últimos N dias."""
    source_types = [source_type] if source_type else None
    articles = _db.query_by_ticker(ticker.upper(), days=days, source_types=source_types)
    return articles


@app.get("/articles/{ticker}/summary")
def get_summary(ticker: str, days: int = Query(default=7, ge=1, le=30)):
    """Retorna resumo estatístico dos artigos de um ticker."""
    articles = _db.query_by_ticker(ticker.upper(), days=days)
    if not articles:
        raise HTTPException(status_code=404, detail=f"Nenhum artigo encontrado para {ticker}")

    sentiment_counts = {"POSITIVE": 0, "NEGATIVE": 0, "NEUTRAL": 0}
    event_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}

    for a in articles:
        label = a.get("sentiment_label", "NEUTRAL") or "NEUTRAL"
        sentiment_counts[label] = sentiment_counts.get(label, 0) + 1

        event = a.get("event_type", "outro") or "outro"
        event_counts[event] = event_counts.get(event, 0) + 1

        source = a.get("source", "unknown") or "unknown"
        source_counts[source] = source_counts.get(source, 0) + 1

    avg_compound = (
        sum(a.get("sentiment_compound", 0.0) or 0.0 for a in articles) / len(articles)
    )

    return {
        "ticker": ticker.upper(),
        "days": days,
        "total_articles": len(articles),
        "sentiment": sentiment_counts,
        "avg_sentiment_compound": round(avg_compound, 4),
        "event_types": event_counts,
        "sources": source_counts,
    }


@app.post("/collect")
async def trigger_collection(request: CollectionRequest, background_tasks: BackgroundTasks):
    """Dispara coleta assíncrona para um ticker."""
    background_tasks.add_task(_run_collection_bg, request.ticker, request.days_back)
    return {"status": "started", "ticker": request.ticker, "days_back": request.days_back}


@app.get("/watchlist", response_model=list[WatchlistItem])
def get_watchlist():
    """Retorna os tickers atualmente na watchlist."""
    return _db.get_watchlist()


@app.get("/social/sources", response_model=list[SocialSourceStatus])
def get_social_sources():
    """
    Lista o status das fontes sociais com foco em:
    - coleta gratuita/pública vs credencial
    - boas práticas de segurança/compliance
    """
    return [
        SocialSourceStatus(
            source="stocktwits",
            access_mode="public_api",
            configured=True,
            enabled=True,
            security_notes="Sem segredo no frontend; chamadas devem passar pelo backend.",
            compliance_notes="Usar limites de taxa e identificar user-agent de pesquisa.",
        ),
        SocialSourceStatus(
            source="twitter",
            access_mode="api_key_required",
            configured=bool(_settings.twitter_bearer_token),
            enabled=bool(_settings.twitter_bearer_token),
            security_notes="Armazenar token em cofre de segredos; evitar .env em clientes.",
            compliance_notes="Preferir endpoint oficial e respeitar limites de API.",
        ),
        SocialSourceStatus(
            source="reddit",
            access_mode="api_key_required",
            configured=bool(_settings.reddit_client_id and _settings.reddit_client_secret),
            enabled=bool(_settings.reddit_client_id and _settings.reddit_client_secret),
            security_notes="Credenciais devem ser rotacionadas e nunca expostas no browser.",
            compliance_notes="Usar API oficial e user-agent transparente para pesquisa.",
        ),
        SocialSourceStatus(
            source="discord",
            access_mode="bot_token_required",
            configured=bool(_settings.discord_bot_token and _settings.discord_channels),
            enabled=bool(_settings.discord_bot_token and _settings.discord_channels),
            security_notes="Bot token deve ficar em servidor e com escopo minimo.",
            compliance_notes="Coletar apenas canais permitidos e com finalidade declarada.",
        ),
        SocialSourceStatus(
            source="telegram",
            access_mode="api_credentials_required",
            configured=bool(
                _settings.telegram_api_id
                and _settings.telegram_api_hash
                and _settings.telegram_phone
            ),
            enabled=bool(
                _settings.telegram_api_id
                and _settings.telegram_api_hash
                and _settings.telegram_phone
            ),
            security_notes="Sessao deve ser protegida e chaves com validade curta quando possivel.",
            compliance_notes="Monitorar canais publicos e respeitar termos da plataforma.",
        ),
        SocialSourceStatus(
            source="linkedin",
            access_mode="session_cookie_required",
            configured=bool(_settings.linkedin_cookies_path),
            enabled=bool(_settings.linkedin_cookies_path),
            security_notes="Cookies de sessao sensiveis; armazenar cifrados e com expiracao.",
            compliance_notes="Scraping sujeito a termos da plataforma; revisar uso periodicamente.",
        ),
    ]


@app.get("/social/{ticker}/summary")
def get_social_summary(
    ticker: str,
    days: int = Query(default=7, ge=1, le=90),
):
    """Retorna resumo de dados sociais coletados por ticker."""
    rows = _db.query_by_ticker(ticker.upper(), days=days, source_types=["social"])

    source_counts: dict[str, int] = {}
    for row in rows:
        source = (row.get("source") or "unknown").lower()
        base_source = source.split("/")[0]
        source_counts[base_source] = source_counts.get(base_source, 0) + 1

    return {
        "ticker": ticker.upper(),
        "days": days,
        "total_social_articles": len(rows),
        "sources": source_counts,
        "public_sources": ["stocktwits"],
    }


@app.post("/watchlist")
def add_to_watchlist(item: WatchlistItem):
    """Adiciona um novo ticker à watchlist."""
    success = _db.add_to_watchlist(item.ticker, is_dual=item.is_dual, us_ticker=item.us_ticker)
    if not success:
        raise HTTPException(status_code=400, detail=f"Ticker {item.ticker} já existe na watchlist")
    return {"status": "added", "ticker": item.ticker.upper()}


@app.delete("/watchlist/{ticker}")
def remove_from_watchlist(ticker: str):
    """Remove um ticker da watchlist."""
    _db.remove_from_watchlist(ticker)
    return {"status": "removed", "ticker": ticker.upper()}


async def _run_collection_bg(ticker: str, days_back: int):
    run_collection = _get_run_collection()
    logger = logging.getLogger(__name__)
    ticker_upper = ticker.upper()
    try:
        summary = await run_collection(ticker_upper, _settings, days_back=days_back)
    except Exception:
        logger.exception("[API] collection failed for %s", ticker_upper)
        return

    logger.info(
        "[API] collection finished for %s (saved=%s, failed_collectors=%s)",
        ticker_upper,
        summary.get("saved_articles", 0),
        len(summary.get("collector_failures", [])),
    )


def _get_run_collection():
    from main import run_collection
    return run_collection


@app.get("/dashboard/{ticker}", response_class=HTMLResponse)
def get_dashboard(
    ticker: str,
    days: int = Query(default=30, ge=1, le=365),
):
    """Dashboard HTML com transações de insiders e políticos ordenadas por data."""
    ticker_upper = ticker.upper()
    articles = _db.query_by_ticker(
        ticker_upper,
        days=days,
        source_types=["insider_trade", "politician_trade"],
    )

    rows_html = ""
    for a in articles:
        source_type = a.get("source_type", "")
        badge_color = "#1a73e8" if source_type == "insider_trade" else "#e8710a"
        badge_label = "INSIDER" if source_type == "insider_trade" else "POLÍTICO"

        pub_date = a.get("published_at", "")
        if isinstance(pub_date, datetime):
            pub_date = pub_date.strftime("%d/%m/%Y")
        elif isinstance(pub_date, str) and "T" in pub_date:
            pub_date = pub_date[:10]

        sentiment = a.get("sentiment_label") or ""
        s_color = {"POSITIVE": "#1e8c3a", "NEGATIVE": "#c62828", "NEUTRAL": "#555"}.get(sentiment, "#555")

        title = a.get("title", "").replace("<", "&lt;").replace(">", "&gt;")
        url   = a.get("url", "#")
        source = a.get("source", "")

        rows_html += f"""
        <tr>
          <td>{pub_date}</td>
          <td><span style="background:{badge_color};color:#fff;padding:2px 6px;border-radius:4px;font-size:11px">{badge_label}</span></td>
          <td><a href="{url}" target="_blank" style="color:#1a73e8;text-decoration:none">{title[:120]}</a></td>
          <td style="color:{s_color};font-weight:bold">{sentiment}</td>
          <td style="color:#777;font-size:12px">{source}</td>
        </tr>"""

    total = len(articles)
    insiders  = sum(1 for a in articles if a.get("source_type") == "insider_trade")
    politicos = sum(1 for a in articles if a.get("source_type") == "politician_trade")

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <title>Dashboard — {ticker_upper}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; background: #f5f5f5; color: #333; }}
    .header {{ background: #1a1a2e; color: #fff; padding: 20px 30px; }}
    .header h1 {{ margin: 0; font-size: 24px; }}
    .header p  {{ margin: 4px 0 0; opacity: .7; font-size: 13px; }}
    .stats {{ display: flex; gap: 20px; padding: 20px 30px; }}
    .stat {{ background: #fff; border-radius: 8px; padding: 16px 24px; flex: 1; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
    .stat .num {{ font-size: 28px; font-weight: bold; color: #1a73e8; }}
    .stat .lbl {{ font-size: 13px; color: #777; }}
    .table-wrap {{ padding: 0 30px 30px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
    th {{ background: #1a1a2e; color: #fff; padding: 12px 14px; text-align: left; font-size: 13px; }}
    td {{ padding: 10px 14px; border-bottom: 1px solid #eee; font-size: 13px; vertical-align: top; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #f9f9f9; }}
    .empty {{ text-align: center; padding: 40px; color: #777; }}
  </style>
</head>
<body>
  <div class="header">
    <h1>Corporate Intelligence — {ticker_upper}</h1>
    <p>Últimos {days} dias &nbsp;|&nbsp; Insiders + Políticos &nbsp;|&nbsp; Gerado em {datetime.now(UTC).strftime("%d/%m/%Y %H:%M")} UTC</p>
  </div>
  <div class="stats">
    <div class="stat"><div class="num">{total}</div><div class="lbl">Total de transações</div></div>
    <div class="stat"><div class="num">{insiders}</div><div class="lbl">Insiders (Form 4 / CVM)</div></div>
    <div class="stat"><div class="num">{politicos}</div><div class="lbl">Políticos (STOCK Act)</div></div>
  </div>
  <div class="table-wrap">
    {"<p class='empty'>Nenhuma transação encontrada para os filtros selecionados.<br>Execute <code>python main.py " + ticker_upper + "</code> para coletar dados.</p>" if not articles else f"""
    <table>
      <thead>
        <tr>
          <th>Data</th><th>Tipo</th><th>Título</th><th>Sentimento</th><th>Fonte</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>"""}
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/export/{ticker}", response_class=Response)
def export_csv(
    ticker: str,
    days: int = Query(default=30, ge=1, le=365),
):
    """Exporta os dados coletados de um ticker para formato CSV."""
    ticker_upper = ticker.upper()
    articles = _db.query_by_ticker(ticker_upper, days=days)
    
    if not articles:
        raise HTTPException(status_code=404, detail=f"Nenhum artigo encontrado para {ticker_upper} nos últimos {days} dias.")
    
    output = io.StringIO()
    # Pega as chaves do primeiro dicionário como cabeçalho
    fieldnames = list(articles[0].keys())
    
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(articles)
    
    # Prepara a string de retorno
    csv_content = output.getvalue()
    
    headers = {
        "Content-Disposition": f"attachment; filename=export_{ticker_upper}.csv"
    }
    return Response(content=csv_content, media_type="text/csv", headers=headers)



@app.post("/alerts/check")
async def trigger_alert_check(background_tasks: BackgroundTasks):
    """Dispara verificação de alertas em background para todos os tickers configurados."""
    background_tasks.add_task(_run_alert_check_bg)
    return {"status": "started", "tickers": _settings.target_tickers}


@app.post("/alerts/check/{ticker}")
async def trigger_alert_check_ticker(ticker: str, background_tasks: BackgroundTasks):
    """Dispara verificação de alertas para um ticker específico."""
    background_tasks.add_task(_run_alert_check_bg, ticker.upper())
    return {"status": "started", "ticker": ticker.upper()}


async def _run_alert_check_bg(ticker: str | None = None):
    from alerts.checker import check_and_alert
    sent = await check_and_alert(_db, _settings, ticker=ticker)
    if sent:
        logging.getLogger(__name__).info(f"[API] {sent} alerta(s) enviado(s) para {ticker or 'todos'}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
