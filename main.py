"""Entry point do Corporate Intelligence Monitor."""
import asyncio
import hashlib
import json
import sys
from datetime import datetime

from collectors.market_router              import MaterialFactsRouter, detect_market
from collectors.news_collector             import NewsCollector
from collectors.social_collector           import build_social_collectors
from collectors.betting_collector          import build_betting_collectors
from collectors.insider_trading_collector  import InsiderTradingCollector
from collectors.politician_trading_collector import PoliticianTradingCollector
from collectors.capitol_trades_collector   import CapitolTradesCollector
from collectors.cvm_insider_collector      import CVMInsiderCollector
from processors.sentiment                  import SentimentAnalyzer
from processors.event_classifier           import classify_event
from storage.database                      import Database
from config.settings                       import Settings


async def run_collection(ticker: str, settings: Settings, days_back: int = 30):
    db        = Database()
    sentiment = SentimentAnalyzer()

    # --- Fatos Relevantes (BR via CVM  ou  US via SEC EDGAR) ---
    async with MaterialFactsRouter() as router:
        async for article in router.collect(ticker, days_back=days_back):
            _save(article, db, sentiment)

    # --- Notícias ---
    async with NewsCollector(rate_limit_rps=1.0) as collector:
        async for article in collector.collect(ticker):
            _save(article, db, sentiment)

    # --- Redes Sociais (X, Reddit, LinkedIn, Discord, Telegram, StockTwits) ---
    # Instancia apenas os coletores com credenciais configuradas no .env
    for collector in build_social_collectors(settings):
        try:
            if hasattr(collector, "__aenter__"):
                async with collector:
                    async for article in collector.collect(ticker):
                        _save(article, db, sentiment)
            else:
                async for article in collector.collect(ticker):
                    _save(article, db, sentiment)
        except Exception as e:
            print(f"[WARN] {collector.__class__.__name__} falhou: {e}")

    # --- Mercados de Previsão / Apostas ---
    for collector in build_betting_collectors(settings):
        try:
            if hasattr(collector, "__aenter__"):
                async with collector:
                    async for article in collector.collect(ticker):
                        _save(article, db, sentiment)
            else:
                async for article in collector.collect(ticker):
                    _save(article, db, sentiment)
        except Exception as e:
            print(f"[WARN] {collector.__class__.__name__} falhou: {e}")

    # --- Insiders: SEC EDGAR Form 4 (empresas US) ---
    market = detect_market(ticker)
    if market == "US":
        try:
            async with InsiderTradingCollector(rate_limit_rps=5.0) as collector:
                async for article in collector.collect(ticker, days_back=days_back):
                    _save(article, db, sentiment)
        except Exception as e:
            print(f"[WARN] InsiderTradingCollector falhou: {e}")

        # --- Políticos: STOCK Act via Quiver Quant (empresas US) ---
        try:
            async with PoliticianTradingCollector(
                rate_limit_rps=0.5, api_key=settings.quiver_api_key
            ) as collector:
                async for article in collector.collect(ticker, days_back=days_back):
                    _save(article, db, sentiment)
        except Exception as e:
            print(f"[WARN] PoliticianTradingCollector falhou: {e}")

        # --- Políticos: Capitol Trades (alternativa pública, sem API key) ---
        try:
            async with CapitolTradesCollector(rate_limit_rps=0.5) as collector:
                async for article in collector.collect(ticker, days_back=days_back):
                    _save(article, db, sentiment)
        except Exception as e:
            print(f"[WARN] CapitolTradesCollector falhou: {e}")

    # --- Insiders: CVM (empresas B3) ---
    if market == "BR":
        try:
            async with CVMInsiderCollector(rate_limit_rps=0.5) as collector:
                async for article in collector.collect(ticker, days_back=days_back):
                    _save(article, db, sentiment)
        except Exception as e:
            print(f"[WARN] CVMInsiderCollector falhou: {e}")


async def run_dual_listed(
    br_ticker: str,
    us_ticker: str,
    settings: Settings,
    days_back: int = 30,
):
    """
    Coleta para empresas com dupla listagem (ex: VALE3 + VALE, PETR4 + PBR).
    Combina Fatos Relevantes da CVM e do SEC EDGAR num único fluxo.
    """
    db        = Database()
    sentiment = SentimentAnalyzer()

    async with MaterialFactsRouter() as router:
        async for article in router.collect_dual_listed(br_ticker, us_ticker, days_back):
            _save(article, db, sentiment)


def _save(article, db: Database, sentiment: SentimentAnalyzer):
    """Enriquece com sentimento/evento e persiste no banco."""
    from processors.event_classifier import classify_event

    s     = sentiment.analyze(article.title + " " + article.content[:500])
    event = classify_event(article.title, article.content)

    record = {
        "id":                  hashlib.sha256(article.url.encode()).hexdigest()[:16],
        "source":              article.source,
        "source_type":         article.source_type,
        "url":                 article.url,
        "title":               article.title,
        "content":             article.content[:5000],
        "published_at":        article.published_at,
        "collected_at":        article.collected_at,
        "company_ticker":      article.company_ticker,
        "company_name":        article.company_name,
        "sentiment_label":     s.label,
        "sentiment_score":     s.score,
        "sentiment_compound":  s.compound,
        "event_type":          event.value,
        "raw_metadata":        json.dumps(article.raw_metadata),
    }
    inserted = db.upsert(record)
    if inserted:
        market = detect_market(article.company_ticker or "")
        line = f"[{market}][{article.source_type}][{article.source}] {article.title[:80]}"
        print(line.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8", errors="replace"))


if __name__ == "__main__":
    settings = Settings()

    # Modo 1: ticker único
    #   python main.py AAPL
    #   python main.py PETR4
    #   python main.py VALE          ← ADR brasileiro → EDGAR 6-K

    # Modo 2: dupla listagem
    #   python main.py VALE3 VALE
    #   python main.py PETR4 PBR

    if len(sys.argv) == 3:
        asyncio.run(run_dual_listed(sys.argv[1], sys.argv[2], settings))
    else:
        ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
        asyncio.run(run_collection(ticker, settings))
