"""
Coletores de Portais de Notícias Financeiras.

Categoria              | Portais
-----------------------|----------------------------------------------------------
Tempo Real / Macro     | Bloomberg, CNBC, Reuters, WSJ, MarketWatch
Análise Fundamentalista| Yahoo Finance, Seeking Alpha, Morningstar, Barchart
Gráficos / Screening   | TradingView (ideas), Finviz (news), Briefing.com
Brasil                 | InfoMoney, Valor Econômico, Investing.com BR, Broadcast

Estratégia por portal:
    RSS puro       → Reuters, MarketWatch, CNBC, InfoMoney, Investing.com BR, Valor
    API JSON       → Yahoo Finance (API pública), Seeking Alpha (API não-oficial)
    HTML scraping  → Finviz, Barchart, TradingView ideas, Briefing.com, Morningstar
    Playwright     → Bloomberg (JS pesado), WSJ (paywall parcial)

Dependências:
    pip install httpx feedparser selectolax playwright
    playwright install chromium
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import AsyncIterator

import feedparser
from selectolax.parser import HTMLParser

from .base_collector import BaseCollector, RawArticle

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_feed_date(entry) -> datetime:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _clean_html(html: str, selectors_remove: list[str] | None = None) -> str:
    """Remove tags de navegação/script e retorna texto limpo."""
    tree = HTMLParser(html)
    for sel in (selectors_remove or []) + [
        "script", "style", "nav", "header", "footer",
        "aside", "iframe", ".ad", ".advertisement",
    ]:
        for node in tree.css(sel):
            node.decompose()

    for sel in ["article", "main", "[class*='article']", "[class*='content']", "p"]:
        nodes = tree.css(sel)
        if nodes:
            return " ".join(n.text(strip=True) for n in nodes)[:4000]
    return (tree.root.text(strip=True) if tree.root else "")[:4000]


# =============================================================================
# BASE: COLETOR RSS GENÉRICO
# =============================================================================

class RSSCollector(BaseCollector):
    """
    Coletor genérico de feeds RSS/Atom.
    Filtra entradas que mencionem o ticker/empresa e opcionalmente
    baixa o conteúdo completo da página.
    """

    def __init__(
        self,
        source_name: str,
        feed_urls: list[str],
        rate_limit_rps: float = 1.0,
        fetch_full_content: bool = False,
    ):
        super().__init__(rate_limit_rps=rate_limit_rps)
        self._source      = source_name
        self._feed_urls   = feed_urls
        self._fetch_full  = fetch_full_content

    async def collect(
        self,
        ticker: str,
        company_aliases: list[str] | None = None,
    ) -> AsyncIterator[RawArticle]:
        terms = {ticker.upper()} | {t.lower() for t in (company_aliases or [])}

        for feed_url in self._feed_urls:
            try:
                resp = await self._get(feed_url)
                feed = feedparser.parse(resp.text)
            except Exception as exc:
                logger.warning("%s RSS %s: %s", self._source, feed_url, exc)
                continue

            for entry in feed.entries:
                title   = entry.get("title", "")
                summary = entry.get("summary", "")
                url     = entry.get("link", "")

                if not any(t in (title + summary).lower() for t in terms):
                    continue

                content = summary
                if self._fetch_full and url:
                    try:
                        page = await self._get(url)
                        content = _clean_html(page.text) or summary
                    except Exception:
                        content = summary

                yield RawArticle(
                    source=self._source,
                    source_type="news",
                    url=url,
                    title=title,
                    content=content,
                    published_at=_parse_feed_date(entry),
                    company_ticker=ticker,
                )


# =============================================================================
# REUTERS BUSINESS
# =============================================================================

class ReutersCollector(RSSCollector):
    """
    Reuters Business via RSS oficial.
    Conteúdo direto e isento — referência para fatos sem opinião.
    """
    FEEDS = [
        "https://feeds.reuters.com/reuters/businessNews",
        "https://feeds.reuters.com/reuters/companyNews",
        "https://feeds.reuters.com/reuters/technologyNews",
    ]

    def __init__(self):
        super().__init__("reuters", self.FEEDS, rate_limit_rps=1.0)


# =============================================================================
# MARKETWATCH
# =============================================================================

class MarketWatchCollector(RSSCollector):
    """
    MarketWatch — rápido, foco em investidores de varejo americanos.
    Feed RSS público com atualizações a cada ~15 min.
    """
    FEEDS = [
        "https://feeds.marketwatch.com/marketwatch/topstories/",
        "https://feeds.marketwatch.com/marketwatch/marketpulse/",
        "https://feeds.marketwatch.com/marketwatch/realtimeheadlines/",
    ]

    def __init__(self):
        super().__init__("marketwatch", self.FEEDS, rate_limit_rps=1.0)


# =============================================================================
# CNBC
# =============================================================================

class CNBCCollector(RSSCollector):
    """
    CNBC — breaking news e cobertura ao vivo do pregão americano.
    """
    FEEDS = [
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",   # top news
        "https://www.cnbc.com/id/10001147/device/rss/rss.html",    # earnings
        "https://www.cnbc.com/id/15839069/device/rss/rss.html",    # US markets
    ]

    def __init__(self):
        super().__init__("cnbc", self.FEEDS, rate_limit_rps=1.0)


# =============================================================================
# BLOOMBERG  (RSS público — headlines gerais de mercado)
# =============================================================================

class BloombergCollector(BaseCollector):
    """
    Bloomberg — referência para traders e market movers.

    Acesso:
        - RSS público (headlines sem paywall): feeds gerais de mercado
        - Busca por ticker: requer Playwright + conta Bloomberg (opcional)

    O RSS público não filtra por ticker — aplica-se busca textual nos títulos.
    Para cobertura por empresa específica, ative o modo Playwright com conta.
    """

    RSS_FEEDS = [
        "https://feeds.bloomberg.com/markets/news.rss",
        "https://feeds.bloomberg.com/technology/news.rss",
        "https://feeds.bloomberg.com/politics/news.rss",
    ]

    # URL de busca do Bloomberg (não requer login para ver snippets)
    SEARCH_URL = "https://www.bloomberg.com/search?query={ticker}&time=1_DAY"

    def __init__(self, use_playwright: bool = False, cookies_path: str | None = None):
        super().__init__(rate_limit_rps=0.5)
        self._use_playwright = use_playwright
        self._cookies_path   = cookies_path

    async def collect(self, ticker: str, **_) -> AsyncIterator[RawArticle]:
        # Modo 1: RSS público (sem auth, sem filtro por ticker)
        for feed_url in self.RSS_FEEDS:
            try:
                resp = await self._get(feed_url)
                feed = feedparser.parse(resp.text)
            except Exception as exc:
                logger.warning("Bloomberg RSS: %s", exc)
                continue

            for entry in feed.entries:
                title = entry.get("title", "")
                if ticker.upper() not in title.upper() and ticker.lower() not in title.lower():
                    continue

                yield RawArticle(
                    source="bloomberg",
                    source_type="news",
                    url=entry.get("link", ""),
                    title=title,
                    content=entry.get("summary", title),
                    published_at=_parse_feed_date(entry),
                    company_ticker=ticker,
                )

        # Modo 2: Playwright com sessão autenticada (opcional)
        if self._use_playwright and self._cookies_path:
            async for article in self._collect_playwright(ticker):
                yield article

    async def _collect_playwright(self, ticker: str) -> AsyncIterator[RawArticle]:
        """Coleta notícias Bloomberg por ticker via browser autenticado."""
        try:
            import json
            from pathlib import Path
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error("Playwright não instalado.")
            return

        cookies_file = Path(self._cookies_path)
        if not cookies_file.exists():
            logger.error("Bloomberg: cookies não encontrados em '%s'.", self._cookies_path)
            return

        with cookies_file.open() as f:
            cookies = json.load(f)

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context()
            await context.add_cookies(cookies)
            page = await context.new_page()

            url = self.SEARCH_URL.format(ticker=ticker)
            await page.goto(url, wait_until="domcontentloaded", timeout=20_000)

            articles = await page.query_selector_all("article, [data-type='article']")
            for el in articles[:15]:
                try:
                    title_el = await el.query_selector("h1, h2, h3, [class*='headline']")
                    title    = (await title_el.inner_text()).strip() if title_el else ""
                    link_el  = await el.query_selector("a[href]")
                    link     = await link_el.get_attribute("href") if link_el else url
                    summary_el = await el.query_selector("p, [class*='summary']")
                    summary    = (await summary_el.inner_text()).strip() if summary_el else ""

                    if not title:
                        continue

                    yield RawArticle(
                        source="bloomberg",
                        source_type="news",
                        url=link if link.startswith("http") else f"https://bloomberg.com{link}",
                        title=title,
                        content=summary or title,
                        published_at=datetime.now(timezone.utc),
                        company_ticker=ticker,
                    )
                except Exception:
                    continue

            await browser.close()


# =============================================================================
# WALL STREET JOURNAL
# =============================================================================

class WSJCollector(BaseCollector):
    """
    Wall Street Journal — análise profunda e política econômica.

    Estratégia:
        - RSS público de seções abertas (sem paywall)
        - Busca por ticker via URL pública (headline visível sem login)

    Para artigos completos, o WSJ requer assinatura.
    """

    RSS_FEEDS = [
        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml",
        "https://feeds.a.dj.com/rss/RSSWSJD.xml",         # tecnologia
    ]
    SEARCH_URL = "https://www.wsj.com/search?query={ticker}&mod=searchresults_viewallresults"

    async def collect(self, ticker: str, **_) -> AsyncIterator[RawArticle]:
        # RSS — headlines públicas
        for feed_url in self.RSS_FEEDS:
            try:
                resp = await self._get(feed_url)
                feed = feedparser.parse(resp.text)
            except Exception as exc:
                logger.warning("WSJ RSS: %s", exc)
                continue

            for entry in feed.entries:
                title = entry.get("title", "")
                if ticker.upper() not in title.upper():
                    continue

                yield RawArticle(
                    source="wsj",
                    source_type="news",
                    url=entry.get("link", ""),
                    title=title,
                    content=entry.get("summary", title),
                    published_at=_parse_feed_date(entry),
                    company_ticker=ticker,
                )

        # Página de busca pública (títulos visíveis sem login)
        try:
            resp = await self._get(self.SEARCH_URL.format(ticker=ticker))
            tree = HTMLParser(resp.text)
            for item in tree.css("article, [class*='WSJTheme--headline']")[:10]:
                title_el = item.css_first("h2, h3, [class*='headline']")
                link_el  = item.css_first("a[href]")
                if not title_el:
                    continue
                title = title_el.text(strip=True)
                link  = link_el.attributes.get("href", "") if link_el else ""

                yield RawArticle(
                    source="wsj",
                    source_type="news",
                    url=link if link.startswith("http") else f"https://www.wsj.com{link}",
                    title=title,
                    content=title,   # paywall — apenas o título
                    published_at=datetime.now(timezone.utc),
                    company_ticker=ticker,
                    raw_metadata={"paywalled": True},
                )
        except Exception as exc:
            logger.debug("WSJ search: %s", exc)


# =============================================================================
# YAHOO FINANCE  —  API JSON pública por ticker
# =============================================================================

class YahooFinanceCollector(BaseCollector):
    """
    Yahoo Finance — melhor fonte pública para notícias por ticker (gratuito).

    Usa a API interna do Yahoo Finance que retorna JSON estruturado.
    Não requer autenticação. Recomendado para múltiplos tickers simultâneos.
    """

    NEWS_API   = "https://query1.finance.yahoo.com/v1/finance/search"
    NEWS_API_2 = "https://query2.finance.yahoo.com/v2/finance/news"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    async def collect(self, ticker: str, count: int = 5, **_) -> AsyncIterator[RawArticle]:
        # Endpoint 1: search com notícias
        try:
            resp = await self._get(
                self.NEWS_API,
                params={"q": ticker, "newsCount": count, "enableFuzzyQuery": False},
                headers=self.HEADERS,
            )
            data = resp.json()
            news_items = data.get("news", [])
        except Exception as exc:
            logger.warning("Yahoo Finance API1: %s", exc)
            news_items = []

        # Endpoint 2: fallback direto por ticker
        if not news_items:
            try:
                resp = await self._get(
                    self.NEWS_API_2,
                    params={"tickers": ticker, "count": count},
                    headers=self.HEADERS,
                )
                news_items = resp.json().get("items", {}).get("result", [])
            except Exception as exc:
                logger.warning("Yahoo Finance API2: %s", exc)

        for item in news_items:
            ts = item.get("providerPublishTime") or item.get("published_at")
            published = (
                datetime.fromtimestamp(ts, tz=timezone.utc)
                if isinstance(ts, (int, float))
                else datetime.now(timezone.utc)
            )

            thumbnail = item.get("thumbnail", {})
            resolutions = thumbnail.get("resolutions", []) if thumbnail else []
            img_url = resolutions[0].get("url") if resolutions else None

            yield RawArticle(
                source="yahoo_finance",
                source_type="news",
                url=item.get("link", ""),
                title=item.get("title", ""),
                content=item.get("summary", item.get("title", "")),
                published_at=published,
                company_ticker=ticker,
                raw_metadata={
                    "publisher":  item.get("publisher"),
                    "source_url": item.get("link"),
                    "image_url":  img_url,
                    "uuid":       item.get("uuid"),
                },
            )


# =============================================================================
# SEEKING ALPHA
# =============================================================================

class SeekingAlphaCollector(BaseCollector):
    """
    Seeking Alpha — melhor fonte para transcrições de earnings calls,
    teses de investimento e análises de analistas independentes.

    Usa a API interna (não oficial) que retorna JSON estruturado.
    Acesso a artigos completos requer assinatura (Premium).
    Headlines e resumos são públicos.
    """

    API_BASE = "https://seekingalpha.com/api/v3"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://seekingalpha.com/",
    }

    async def collect(self, ticker: str, count: int = 5, **_) -> AsyncIterator[RawArticle]:
        # Notícias por símbolo
        async for article in self._collect_news(ticker, count):
            yield article

        # Análises (artigos de autores)
        async for article in self._collect_analysis(ticker, max(1, count // 2)):
            yield article

    async def _collect_news(self, ticker: str, count: int) -> AsyncIterator[RawArticle]:
        url = f"{self.API_BASE}/symbols/{ticker.upper()}/news"
        params = {"filter[since]": 0, "filter[until]": 0, "page[size]": count}

        try:
            resp = await self._get(url, params=params, headers=self.HEADERS)
            items = resp.json().get("data", [])
        except Exception as exc:
            logger.warning("Seeking Alpha news: %s", exc)
            return

        for item in items:
            attrs = item.get("attributes", {})
            ts    = attrs.get("publishOn") or attrs.get("lastModified", "")

            yield RawArticle(
                source="seekingalpha",
                source_type="news",
                url=f"https://seekingalpha.com{attrs.get('gettyImageUrl', '')}",
                title=attrs.get("title", ""),
                content=attrs.get("summary", attrs.get("title", "")),
                published_at=_parse_iso(ts),
                company_ticker=ticker,
                raw_metadata={
                    "type":       "news",
                    "source":     attrs.get("source", ""),
                    "sa_id":      item.get("id"),
                    "paywalled":  attrs.get("isPremium", False),
                },
            )

    async def _collect_analysis(self, ticker: str, count: int) -> AsyncIterator[RawArticle]:
        url = f"{self.API_BASE}/symbols/{ticker.upper()}/articles"
        params = {"filter[category]": "latest-articles", "page[size]": count}

        try:
            resp = await self._get(url, params=params, headers=self.HEADERS)
            items = resp.json().get("data", [])
        except Exception as exc:
            logger.debug("Seeking Alpha articles: %s", exc)
            return

        for item in items:
            attrs   = item.get("attributes", {})
            ts      = attrs.get("publishOn", "")
            slug    = attrs.get("slug", "")

            yield RawArticle(
                source="seekingalpha",
                source_type="news",
                url=f"https://seekingalpha.com/article/{slug}" if slug else "https://seekingalpha.com",
                title=attrs.get("title", ""),
                content=attrs.get("summary", attrs.get("title", "")),
                published_at=_parse_iso(ts),
                company_ticker=ticker,
                raw_metadata={
                    "type":      "analysis",
                    "author":    attrs.get("authorId"),
                    "sa_id":     item.get("id"),
                    "paywalled": attrs.get("isPremium", False),
                    "ratings":   attrs.get("ratings"),
                },
            )


# =============================================================================
# MORNINGSTAR
# =============================================================================

class MorningstarCollector(BaseCollector):
    """
    Morningstar — análise de valuation, fossos competitivos (moat) e fair value.

    Scraping da página de notícias pública por ticker.
    Dados de valuation e rating (estrelas) são públicos sem login.
    """

    NEWS_URL   = "https://www.morningstar.com/stocks/{exchange}/{ticker}/news"
    QUOTE_URL  = "https://api.morningstar.com/v2/analyst-reports/{ticker}"

    EXCHANGE_MAP = {
        # Mapeamento ticker → exchange code no Morningstar (XNAS/XNYS)
        "DEFAULT": "xnas",
    }

    async def collect(self, ticker: str, **_) -> AsyncIterator[RawArticle]:
        exchange = self.EXCHANGE_MAP.get(ticker.upper(), "xnas")
        url = self.NEWS_URL.format(exchange=exchange, ticker=ticker.lower())

        try:
            resp = await self._get(url)
            tree = HTMLParser(resp.text)
        except Exception as exc:
            logger.warning("Morningstar: %s", exc)
            return

        # Scraping de cards de notícias
        for card in tree.css("[class*='card'], article, [data-testid*='news']")[:15]:
            title_el = card.css_first("h2, h3, [class*='title'], [class*='headline']")
            link_el  = card.css_first("a[href]")
            date_el  = card.css_first("time, [class*='date'], [class*='time']")

            if not title_el:
                continue

            title    = title_el.text(strip=True)
            link     = link_el.attributes.get("href", url) if link_el else url
            date_str = date_el.text(strip=True) if date_el else ""

            if not link.startswith("http"):
                link = f"https://www.morningstar.com{link}"

            yield RawArticle(
                source="morningstar",
                source_type="news",
                url=link,
                title=title,
                content=title,
                published_at=_fuzzy_date(date_str),
                company_ticker=ticker,
                raw_metadata={"exchange": exchange},
            )


# =============================================================================
# BARCHART  —  Dados de opções, volatilidade e notícias
# =============================================================================

class BarchartCollector(BaseCollector):
    """
    Barchart — excelente para dados de opções, volatilidade implícita e notícias.

    Scraping da seção de notícias e dados de opções da página pública.
    Sem autenticação necessária para dados básicos.
    """

    NEWS_URL   = "https://www.barchart.com/stocks/quotes/{ticker}/news-headlines"
    OPTIONS_URL = "https://www.barchart.com/stocks/quotes/{ticker}/options"

    async def collect(self, ticker: str, **_) -> AsyncIterator[RawArticle]:
        # Notícias
        url = self.NEWS_URL.format(ticker=ticker.upper())
        try:
            resp = await self._get(url)
            tree = HTMLParser(resp.text)
        except Exception as exc:
            logger.warning("Barchart news: %s", exc)
            return

        for row in tree.css("table tr, [class*='news-item'], article")[:20]:
            link_el  = row.css_first("a[href*='/story/'], a[href*='/news/']")
            title_el = row.css_first("a, [class*='title']")
            date_el  = row.css_first("td:first-child, time, [class*='date']")

            if not title_el:
                continue

            title    = title_el.text(strip=True)
            link     = link_el.attributes.get("href", url) if link_el else url
            date_str = date_el.text(strip=True) if date_el else ""

            if not link.startswith("http"):
                link = f"https://www.barchart.com{link}"

            if not title or len(title) < 10:
                continue

            yield RawArticle(
                source="barchart",
                source_type="news",
                url=link,
                title=title,
                content=title,
                published_at=_fuzzy_date(date_str),
                company_ticker=ticker,
            )


# =============================================================================
# FINVIZ  —  Screener visual + notícias por ticker
# =============================================================================

class FinvizCollector(BaseCollector):
    """
    Finviz — o melhor screener visual + agregador de notícias por ação.

    A tabela de notícias do Finviz está na página pública de cotação
    sem necessidade de JavaScript (renderização server-side).
    Não requer autenticação.
    """

    QUOTE_URL = "https://finviz.com/quote.ashx?t={ticker}"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://finviz.com/",
    }

    async def collect(self, ticker: str, **_) -> AsyncIterator[RawArticle]:
        url = self.QUOTE_URL.format(ticker=ticker.upper())
        try:
            resp = await self._get(url, headers=self.HEADERS)
            tree = HTMLParser(resp.text)
        except Exception as exc:
            logger.warning("Finviz: %s", exc)
            return

        # Tabela de notícias — ID "news-table" na página
        news_table = tree.css_first("#news-table")
        if not news_table:
            logger.debug("Finviz: tabela de notícias não encontrada para %s", ticker)
            return

        current_date = datetime.now(timezone.utc).strftime("%b-%d-%y")

        for row in news_table.css("tr"):
            cells = row.css("td")
            if len(cells) < 2:
                continue

            date_cell = cells[0].text(strip=True)
            # Finviz usa "Jan-01-24" para nova data, "08:30AM" para mesma data
            if re.match(r"[A-Z][a-z]{2}-\d{2}-\d{2}", date_cell):
                current_date = date_cell

            link_el = cells[1].css_first("a[href]")
            source_el = cells[1].css_first("span[class*='news-link-right']")

            if not link_el:
                continue

            title  = link_el.text(strip=True)
            url_   = link_el.attributes.get("href", "")
            source = source_el.text(strip=True) if source_el else "finviz"

            try:
                date_str = f"{current_date} {date_cell}" if "AM" in date_cell or "PM" in date_cell else current_date
                published = datetime.strptime(date_str.strip(), "%b-%d-%y %I:%M%p")
                published = published.replace(tzinfo=timezone.utc)
            except ValueError:
                published = datetime.now(timezone.utc)

            yield RawArticle(
                source=f"finviz/{source.lower()}",
                source_type="news",
                url=url_,
                title=title,
                content=title,
                published_at=published,
                company_ticker=ticker,
                raw_metadata={"aggregated_source": source},
            )


# =============================================================================
# TRADINGVIEW  —  Ideas públicas de traders
# =============================================================================

class TradingViewCollector(BaseCollector):
    """
    TradingView — leader em análise técnica.
    Coleta "ideas" públicas de traders para um ticker específico.

    Dado único: inclui `signal` (LONG/SHORT/NEUTRAL) e `likes_count`,
    que representam o sentimento técnico da comunidade de analistas.
    """

    IDEAS_API = "https://pine-facade.tradingview.com/pine-facade/list/"
    SYMBOL_IDEAS_URL = "https://www.tradingview.com/symbols/{ticker}/ideas/"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.tradingview.com/",
    }

    async def collect(self, ticker: str, **_) -> AsyncIterator[RawArticle]:
        url = self.SYMBOL_IDEAS_URL.format(ticker=ticker.upper())
        try:
            resp = await self._get(url, headers=self.HEADERS)
            tree = HTMLParser(resp.text)
        except Exception as exc:
            logger.warning("TradingView: %s", exc)
            return

        for card in tree.css("[class*='card-'], [data-idea-id]")[:20]:
            title_el  = card.css_first("[class*='title'], h2, h3")
            link_el   = card.css_first("a[href*='/ideas/']")
            author_el = card.css_first("[class*='author'], [class*='username']")
            signal_el = card.css_first("[class*='signal'], [class*='label-']")
            likes_el  = card.css_first("[class*='likes'], [class*='agree']")

            if not title_el:
                continue

            title  = title_el.text(strip=True)
            link   = link_el.attributes.get("href", "") if link_el else url
            author = author_el.text(strip=True) if author_el else ""
            signal = signal_el.text(strip=True) if signal_el else ""
            likes  = likes_el.text(strip=True) if likes_el else "0"

            if not link.startswith("http"):
                link = f"https://www.tradingview.com{link}"

            yield RawArticle(
                source="tradingview",
                source_type="news",
                url=link,
                title=f"[TV/{signal}] {title}" if signal else title,
                content=title,
                published_at=datetime.now(timezone.utc),
                company_ticker=ticker,
                raw_metadata={
                    "signal": signal,   # LONG / SHORT / NEUTRAL
                    "author": author,
                    "likes":  likes,
                    "type":   "idea",
                },
            )


# =============================================================================
# BRIEFING.COM  —  Alertas técnicos e calendários de earnings
# =============================================================================

class BriefingCollector(BaseCollector):
    """
    Briefing.com — alertas de mercado em tempo real e calendário de balanços.

    Seções públicas: In Play (eventos do dia), calendário de earnings,
    economic calendar. Requer assinatura para alertas completos.
    """

    IN_PLAY_URL = "https://www.briefing.com/general/daily-stockwatch.htm"
    CALENDAR_URL = "https://www.briefing.com/investor/calendars/earnings/this-week.htm"

    async def collect(self, ticker: str, **_) -> AsyncIterator[RawArticle]:
        for url, section in [
            (self.IN_PLAY_URL,  "in_play"),
            (self.CALENDAR_URL, "earnings_calendar"),
        ]:
            try:
                resp = await self._get(url)
                tree = HTMLParser(resp.text)
            except Exception as exc:
                logger.warning("Briefing.com %s: %s", section, exc)
                continue

            for para in tree.css("p, td, li"):
                text = para.text(strip=True)
                if ticker.upper() not in text and ticker.lower() not in text.lower():
                    continue
                if len(text) < 15:
                    continue

                yield RawArticle(
                    source="briefing",
                    source_type="news",
                    url=url,
                    title=text[:200],
                    content=text[:1500],
                    published_at=datetime.now(timezone.utc),
                    company_ticker=ticker,
                    raw_metadata={"section": section},
                )


# =============================================================================
# PORTAIS BRASILEIROS
# =============================================================================

class InfoMoneyCollector(RSSCollector):
    """InfoMoney — maior portal de finanças pessoais do Brasil."""
    FEEDS = [
        "https://www.infomoney.com.br/feed/",
        "https://www.infomoney.com.br/mercados/acoes/feed/",
    ]

    def __init__(self):
        super().__init__("infomoney", self.FEEDS, rate_limit_rps=1.0)


class ValorEconomicoCollector(RSSCollector):
    """Valor Econômico — principal jornal de negócios do Brasil."""
    FEEDS = [
        "https://valor.globo.com/rss/valor-economico.xml",
        "https://valor.globo.com/rss/financas.xml",
        "https://valor.globo.com/rss/empresas.xml",
    ]

    def __init__(self):
        super().__init__("valor_economico", self.FEEDS, rate_limit_rps=0.5)


class InvestingBRCollector(RSSCollector):
    """Investing.com Brasil — cobertura ampla de mercados e criptomoedas."""
    FEEDS = [
        "https://br.investing.com/rss/news.rss",
        "https://br.investing.com/rss/market_overview_Fundamentals_Analysis.rss",
    ]

    def __init__(self):
        super().__init__("investing_br", self.FEEDS, rate_limit_rps=1.0)


# =============================================================================
# FACTORY  —  Instancia todos os coletores de notícias
# =============================================================================

def build_news_collectors(
    include_br: bool = True,
    include_us: bool = True,
    playwright_sources: dict | None = None,
) -> list[BaseCollector]:
    """
    Instancia e retorna todos os coletores de notícias disponíveis.

    Args:
        include_br:          Inclui portais brasileiros
        include_us:          Inclui portais americanos
        playwright_sources:  Dict com cookies para fontes que exigem Playwright.
                             Ex: {"bloomberg": "bloomberg_cookies.json"}
    """
    pw = playwright_sources or {}
    collectors: list[BaseCollector] = []

    if include_us:
        collectors += [
            # RSS puro — sem dependências extras
            ReutersCollector(),
            MarketWatchCollector(),
            CNBCCollector(),
            WSJCollector(),
            # API JSON pública
            YahooFinanceCollector(),
            SeekingAlphaCollector(),
            # HTML scraping sem JS
            FinvizCollector(),
            BarchartCollector(),
            TradingViewCollector(),
            BriefingCollector(),
            MorningstarCollector(),
            # Bloomberg: RSS público + Playwright opcional
            BloombergCollector(
                use_playwright=bool(pw.get("bloomberg")),
                cookies_path=pw.get("bloomberg"),
            ),
        ]

    if include_br:
        collectors += [
            InfoMoneyCollector(),
            ValorEconomicoCollector(),
            InvestingBRCollector(),
        ]

    return collectors


# Instância padrão para uso direto no main.py (mantém compatibilidade)
class NewsCollector(BaseCollector):
    """
    Facade que agrega todos os coletores de notícias num único `collect()`.
    Uso recomendado via `build_news_collectors()` para mais controle.
    """

    def __init__(self, rate_limit_rps: float = 1.0):
        super().__init__(rate_limit_rps=rate_limit_rps)
        self._sub_collectors: list[BaseCollector] = []

    async def __aenter__(self):
        await super().__aenter__()
        self._sub_collectors = build_news_collectors()
        for c in self._sub_collectors:
            await c.__aenter__()
        return self

    async def __aexit__(self, *args):
        for c in self._sub_collectors:
            await c.__aexit__(*args)
        await super().__aexit__(*args)

    async def collect(
        self, ticker: str, max_articles: int = 5, **kwargs
    ) -> AsyncIterator[RawArticle]:
        """
        Executa todos os sub-coletores em paralelo via asyncio.Queue.
        Retorna assim que `max_articles` forem coletados (early-exit),
        cancelando as tarefas restantes.
        """
        queue: asyncio.Queue[RawArticle | None] = asyncio.Queue()

        async def _drain(collector: BaseCollector) -> None:
            try:
                async for article in collector.collect(ticker, **kwargs):
                    await queue.put(article)
            except Exception as exc:
                logger.warning(
                    "%s.collect(%s): %s", type(collector).__name__, ticker, exc
                )
            finally:
                await queue.put(None)  # sentinela: este coletor terminou

        tasks = [
            asyncio.create_task(_drain(c)) for c in self._sub_collectors
        ]
        pending = len(tasks)
        collected = 0

        while pending > 0 and collected < max_articles:
            item = await queue.get()
            if item is None:
                pending -= 1
            else:
                collected += 1
                yield item

        # Cancela coletores que ainda estão rodando
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


# =============================================================================
# HELPERS INTERNOS
# =============================================================================

def _parse_iso(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)


def _fuzzy_date(text: str) -> datetime:
    """Tenta parsear strings de data informais ('Jan 5', '2 hours ago', etc.)."""
    now = datetime.now(timezone.utc)

    # "X hours ago"
    m = re.search(r"(\d+)\s+hour", text, re.I)
    if m:
        return now - timedelta(hours=int(m.group(1)))

    # "X days ago"
    m = re.search(r"(\d+)\s+day", text, re.I)
    if m:
        return now - timedelta(days=int(m.group(1)))

    # "Jan-05-24" ou "Jan 05, 2024"
    for fmt in ("%b-%d-%y", "%b %d, %Y", "%b %d %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip()[:15], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return now
