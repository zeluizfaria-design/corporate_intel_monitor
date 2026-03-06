"""
Coletores de Redes Sociais para o Corporate Intelligence Monitor.

Rede          | Método            | Autenticação        | Velocidade
--------------|-------------------|---------------------|------------
X (Twitter)   | API v2 oficial    | Bearer Token        | Altíssima
Reddit        | PRAW (API oficial)| Client ID + Secret  | Média
LinkedIn      | Playwright        | Cookie de sessão    | Baixa
Discord       | discord.py        | Bot Token           | Alta
Telegram      | Telethon          | API ID + Hash       | Alta
StockTwits    | API pública       | Sem autenticação    | Alta

Dependências:
    pip install httpx praw playwright discord.py telethon selectolax
    playwright install chromium
"""

from __future__ import annotations

import asyncio
import logging
import re
from abc import abstractmethod
from datetime import datetime, timezone
from typing import AsyncIterator

import httpx

from .base_collector import BaseCollector, RawArticle

logger = logging.getLogger(__name__)


# =============================================================================
# X / TWITTER
# =============================================================================

class TwitterCollector(BaseCollector):
    """
    Coleta tweets via API v2 com busca recente.

    Limite free tier: 500k tweets/mês | 10 req/15min por endpoint.
    Documentação: https://developer.twitter.com/en/docs/twitter-api

    Config:
        TWITTER_BEARER_TOKEN = "AAA..."
    """

    SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"

    # Subreddits financeiros brasileiros e internacionais
    FINANCIAL_ACCOUNTS = [
        "InvestNewsB3", "valoreconomico", "InfoMoney",
        "B3_Bolsa", "CVM_Noticias",
    ]

    def __init__(self, bearer_token: str, rate_limit_rps: float = 0.5):
        super().__init__(rate_limit_rps=rate_limit_rps)
        self._bearer = bearer_token

    async def collect(
        self,
        ticker: str,
        max_results: int = 100,
        lang: str | None = None,
    ) -> AsyncIterator[RawArticle]:
        """
        Busca tweets recentes mencionando o ticker.

        Args:
            ticker:      Símbolo (ex: PETR4, AAPL)
            max_results: Máx 100 por requisição (limite da API)
            lang:        'pt' para filtrar somente português, None = sem filtro
        """
        lang_filter = f" lang:{lang}" if lang else ""
        query = f"(${ticker} OR #{ticker} OR \"{ticker}\") -is:retweet{lang_filter}"

        params = {
            "query": query,
            "max_results": min(max_results, 100),
            "tweet.fields": "created_at,author_id,public_metrics,context_annotations,entities",
            "expansions": "author_id",
            "user.fields": "name,username,verified,public_metrics",
        }
        headers = {"Authorization": f"Bearer {self._bearer}"}

        resp = await self._get(self.SEARCH_URL, params=params, headers=headers)
        data = resp.json()

        users_by_id = {
            u["id"]: u
            for u in data.get("includes", {}).get("users", [])
        }

        for tweet in data.get("data", []):
            author = users_by_id.get(tweet.get("author_id", ""), {})
            metrics = tweet.get("public_metrics", {})

            yield RawArticle(
                source="twitter",
                source_type="social",
                url=f"https://twitter.com/i/web/status/{tweet['id']}",
                title=tweet["text"][:140],
                content=tweet["text"],
                published_at=datetime.fromisoformat(
                    tweet["created_at"].replace("Z", "+00:00")
                ),
                company_ticker=ticker,
                raw_metadata={
                    "author_username": author.get("username"),
                    "author_verified":  author.get("verified", False),
                    "author_followers": author.get("public_metrics", {}).get("followers_count", 0),
                    "likes":     metrics.get("like_count", 0),
                    "retweets":  metrics.get("retweet_count", 0),
                    "replies":   metrics.get("reply_count", 0),
                    "impressions": metrics.get("impression_count", 0),
                },
            )


# =============================================================================
# STOCKTWITS
# =============================================================================

class StockTwitsCollector(BaseCollector):
    """
    StockTwits — rede social exclusiva de traders.
    API pública sem autenticação para leitura de stream por símbolo.

    Foco: Sentimento de curto prazo de traders de varejo.
    Documentação: https://api.stocktwits.com/developers/docs
    """

    STREAM_URL = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"

    async def collect(self, ticker: str, **_) -> AsyncIterator[RawArticle]:
        # Some public endpoints reject generic automation headers; use browser-like headers.
        resp = await self._get(
            self.STREAM_URL.format(ticker=ticker.upper()),
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json,text/plain,*/*",
                "Referer": f"https://stocktwits.com/symbol/{ticker.upper()}",
            },
        )
        data = resp.json()

        if data.get("response", {}).get("status") != 200:
            logger.warning("StockTwits: símbolo '%s' não encontrado", ticker)
            return

        for msg in data.get("messages", []):
            sentiment_raw = (msg.get("entities") or {}).get("sentiment") or {}
            user = msg.get("user", {})

            yield RawArticle(
                source="stocktwits",
                source_type="social",
                url=f"https://stocktwits.com/message/{msg['id']}",
                title=msg["body"][:140],
                content=msg["body"],
                published_at=datetime.fromisoformat(
                    msg["created_at"].replace("Z", "+00:00")
                ),
                company_ticker=ticker,
                raw_metadata={
                    "sentiment_label":  sentiment_raw.get("basic"),  # 'Bullish'|'Bearish'|None
                    "likes":            msg.get("likes", {}).get("total", 0),
                    "author_username":  user.get("username"),
                    "author_followers": user.get("followers", 0),
                    "official_account": user.get("official", False),
                },
            )


# =============================================================================
# REDDIT
# =============================================================================

class RedditCollector(BaseCollector):
    """
    Coleta posts e comentários do Reddit via PRAW (API oficial).

    Subreddits monitorados por mercado:
        Brasil: r/investimentos, r/acoes, r/dividendos, r/bolsadevalores
        EUA:    r/investing, r/wallstreetbets, r/stocks, r/SecurityAnalysis

    Autenticação: App de script no Reddit (gratuito).
    Criar em: https://www.reddit.com/prefs/apps

    Config:
        REDDIT_CLIENT_ID     = "abc123"
        REDDIT_CLIENT_SECRET = "xyz789"
        REDDIT_USER_AGENT    = "CorporateIntelMonitor/1.0"
    """

    # Subreddits por categoria de mercado
    SUBREDDITS_BR = [
        "investimentos", "acoes", "dividendos",
        "bolsadevalores", "fundosimobiliarios",
    ]
    SUBREDDITS_US = [
        "investing", "wallstreetbets", "stocks",
        "SecurityAnalysis", "ValueInvesting", "options",
    ]

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str = "CorporateIntelMonitor/1.0",
        rate_limit_rps: float = 1.0,
    ):
        super().__init__(rate_limit_rps=rate_limit_rps)
        self._client_id     = client_id
        self._client_secret = client_secret
        self._user_agent    = user_agent
        self._access_token: str | None = None

    async def _ensure_token(self):
        """Obtém token OAuth2 de aplicação (sem conta de usuário)."""
        if self._access_token:
            return
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "client_credentials"},
                auth=(self._client_id, self._client_secret),
                headers={"User-Agent": self._user_agent},
            )
            resp.raise_for_status()
            self._access_token = resp.json()["access_token"]

    async def collect(
        self,
        ticker: str,
        market: str = "auto",
        limit: int = 50,
        sort: str = "new",
    ) -> AsyncIterator[RawArticle]:
        """
        Busca posts mencionando o ticker nos subreddits financeiros.

        Args:
            ticker: Símbolo da ação (ex: PETR4, AAPL)
            market: 'BR', 'US' ou 'auto' (detecta pelo padrão do ticker)
            limit:  Máximo de posts por subreddit
            sort:   'new' | 'hot' | 'top' | 'relevance'
        """
        await self._ensure_token()

        # Detecta mercado pelo padrão do ticker
        if market == "auto":
            market = "BR" if re.match(r"^[A-Z]{4}\d", ticker.upper()) else "US"

        subreddits = self.SUBREDDITS_BR if market == "BR" else self.SUBREDDITS_US

        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "User-Agent": self._user_agent,
        }

        for subreddit in subreddits:
            url = f"https://oauth.reddit.com/r/{subreddit}/search"
            params = {
                "q":          ticker,
                "restrict_sr": "true",
                "sort":        sort,
                "limit":       limit,
                "t":           "week",   # última semana
            }
            try:
                resp = await self._get(url, params=params, headers=headers)
                posts = resp.json().get("data", {}).get("children", [])
            except Exception as exc:
                logger.warning("Reddit r/%s: %s", subreddit, exc)
                continue

            for post_wrap in posts:
                post = post_wrap.get("data", {})
                # Filtra posts que realmente mencionam o ticker
                text = (post.get("title", "") + " " + post.get("selftext", "")).lower()
                if ticker.lower() not in text:
                    continue

                ts = post.get("created_utc", 0)
                published = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.utcnow()

                yield RawArticle(
                    source=f"reddit/r/{subreddit}",
                    source_type="social",
                    url=f"https://reddit.com{post.get('permalink', '')}",
                    title=post.get("title", "")[:200],
                    content=(post.get("selftext") or post.get("title", ""))[:3000],
                    published_at=published,
                    company_ticker=ticker,
                    raw_metadata={
                        "subreddit":   subreddit,
                        "score":       post.get("score", 0),
                        "upvote_ratio": post.get("upvote_ratio", 0.5),
                        "num_comments": post.get("num_comments", 0),
                        "author":      post.get("author"),
                        "flair":       post.get("link_flair_text"),
                        "awards":      post.get("total_awards_received", 0),
                    },
                )


# =============================================================================
# LINKEDIN
# =============================================================================

class LinkedInCollector(BaseCollector):
    """
    Coleta posts públicos do LinkedIn via Playwright (automação de browser).

    ATENÇÃO: O LinkedIn restringe scraping em seus Termos de Serviço.
    Este coletor é fornecido para fins de pesquisa. Verifique as políticas
    antes de uso em produção. Alternativa oficial: LinkedIn Marketing API
    (requer parceria aprovada pela empresa).

    Configuração necessária:
        1. Instale Playwright: `playwright install chromium`
        2. Exporte cookies de sessão do LinkedIn (após login manual) para
           o arquivo `linkedin_cookies.json` na raiz do projeto.
        3. Use a ferramenta de exportação de cookies do seu browser ou
           rode `python -c "from collectors.social_collector import LinkedInCollector; LinkedInCollector.export_session_helper()"`.

    Foco: Posts de executivos (C-suite), páginas corporativas, artigos
          de analistas sobre a empresa monitorada.
    """

    COMPANY_POSTS_URL = "https://www.linkedin.com/company/{slug}/posts/"
    SEARCH_URL        = "https://www.linkedin.com/search/results/content/?keywords={query}&origin=SWITCH_SEARCH_VERTICAL"

    def __init__(
        self,
        cookies_path: str = "linkedin_cookies.json",
        rate_limit_rps: float = 0.2,   # muito conservador para evitar bloqueio
    ):
        super().__init__(rate_limit_rps=rate_limit_rps)
        self._cookies_path = cookies_path

    async def collect(
        self,
        ticker: str,
        company_slug: str | None = None,
        max_posts: int = 20,
    ) -> AsyncIterator[RawArticle]:
        """
        Coleta posts do LinkedIn para uma empresa.

        Args:
            ticker:       Símbolo da ação
            company_slug: Slug da página corporativa (ex: 'petrobras', 'apple')
                          Se não fornecido, apenas a busca por keyword é feita.
            max_posts:    Máximo de posts a coletar
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error(
                "Playwright não instalado. Execute: pip install playwright && playwright install chromium"
            )
            return

        import json
        from pathlib import Path

        cookies_file = Path(self._cookies_path)
        if not cookies_file.exists():
            logger.error(
                "Arquivo de cookies '%s' não encontrado. "
                "Faça login no LinkedIn no Chrome, exporte os cookies "
                "e salve em '%s'.",
                self._cookies_path, self._cookies_path,
            )
            return

        with cookies_file.open() as f:
            cookies = json.load(f)

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            await context.add_cookies(cookies)
            page = await context.new_page()

            collected = 0

            # --- Página corporativa ---
            if company_slug and collected < max_posts:
                url = self.COMPANY_POSTS_URL.format(slug=company_slug)
                async for article in self._scrape_feed_page(
                    page, url, ticker, max_posts - collected
                ):
                    collected += 1
                    yield article

            # --- Busca por keyword ---
            if collected < max_posts:
                search_url = self.SEARCH_URL.format(query=ticker)
                async for article in self._scrape_feed_page(
                    page, search_url, ticker, max_posts - collected
                ):
                    yield article

            await browser.close()

    async def _scrape_feed_page(
        self,
        page,
        url: str,
        ticker: str,
        limit: int,
    ) -> AsyncIterator[RawArticle]:
        """Extrai posts de uma página de feed do LinkedIn."""
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(3)  # aguarda lazy load

        # Scroll para carregar mais posts
        for _ in range(min(limit // 5, 4)):
            await page.evaluate("window.scrollBy(0, 1500)")
            await asyncio.sleep(1.5)

        # Seleciona containers de post (selector estável do LinkedIn)
        posts = await page.query_selector_all(
            "div.feed-shared-update-v2, div[data-urn*='activity']"
        )

        count = 0
        for post_el in posts[:limit]:
            if count >= limit:
                break
            try:
                # Texto do post
                text_el = await post_el.query_selector(
                    "div.feed-shared-text, span.break-words"
                )
                text = (await text_el.inner_text()) if text_el else ""
                if not text.strip():
                    continue

                # Autor
                author_el = await post_el.query_selector(
                    "span.feed-shared-actor__name, span.update-components-actor__name"
                )
                author = (await author_el.inner_text()) if author_el else "Desconhecido"

                # Título do cargo/empresa do autor
                title_el = await post_el.query_selector(
                    "span.feed-shared-actor__description"
                )
                author_title = (await title_el.inner_text()) if title_el else ""

                # Contagem de reações
                reactions_el = await post_el.query_selector(
                    "span.social-details-social-counts__reactions-count"
                )
                reactions = (await reactions_el.inner_text()) if reactions_el else "0"

                # Link do post
                link_el = await post_el.query_selector("a.app-aware-link[href*='activity']")
                post_url = (await link_el.get_attribute("href")) if link_el else url

                yield RawArticle(
                    source="linkedin",
                    source_type="social",
                    url=post_url or url,
                    title=f"[LinkedIn] {author}: {text[:100]}",
                    content=text[:3000],
                    published_at=datetime.utcnow(),  # LinkedIn não expõe timestamp facilmente
                    company_ticker=ticker,
                    raw_metadata={
                        "author":       author.strip(),
                        "author_title": author_title.strip(),
                        "reactions":    reactions.strip(),
                        "platform":     "linkedin",
                    },
                )
                count += 1

            except Exception as exc:
                logger.debug("LinkedIn post parse error: %s", exc)
                continue

    @staticmethod
    def export_session_helper():
        """
        Abre o Chrome com o LinkedIn para que o usuário faça login e exporte
        cookies automaticamente para linkedin_cookies.json.

        Executar uma vez manualmente:
            python -c "from collectors.social_collector import LinkedInCollector; import asyncio; asyncio.run(LinkedInCollector._run_export_helper())"
        """
        import json
        import asyncio
        from playwright.sync_api import sync_playwright

        print("Abrindo browser. Faça login no LinkedIn e pressione Enter quando terminar...")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto("https://www.linkedin.com/login")
            input("Pressione Enter após completar o login no browser...")
            cookies = context.cookies()
            with open("linkedin_cookies.json", "w") as f:
                json.dump(cookies, f, indent=2)
            print(f"Cookies salvos: {len(cookies)} entradas em linkedin_cookies.json")
            browser.close()


# =============================================================================
# DISCORD
# =============================================================================

class DiscordCollector:
    """
    Coleta mensagens de canais Discord via bot (discord.py).

    Arquitetura: O Discord usa WebSocket (event-driven), não polling.
    Este coletor inicia o bot, monitora canais por um período, e
    retorna as mensagens coletadas naquele janela de tempo.

    Para coleta contínua, use o método `start_monitor()` com APScheduler.

    Config:
        DISCORD_BOT_TOKEN = "MTxx..."

    Setup:
        1. Crie um bot em https://discord.com/developers/applications
        2. Habilite "Message Content Intent" nas configurações do bot
        3. Convide o bot para os servidores com permissão de "Read Messages"
        4. Configure MONITORED_CHANNELS com os IDs dos canais relevantes

    Canais típicos a monitorar:
        - #alertas-b3, #fatos-relevantes, #analises
        - #market-news, #trading-alerts, #earnings
    """

    def __init__(
        self,
        bot_token: str,
        monitored_channels: list[int],
        collect_window_seconds: int = 300,
    ):
        """
        Args:
            bot_token:              Token do bot Discord
            monitored_channels:     Lista de channel IDs (inteiros) a monitorar
            collect_window_seconds: Janela de coleta em segundos (padrão: 5min)
        """
        self._token    = bot_token
        self._channels = set(monitored_channels)
        self._window   = collect_window_seconds
        self._buffer:  list[RawArticle] = []

    async def collect(self, ticker: str, **_) -> AsyncIterator[RawArticle]:
        """
        Conecta ao Discord, coleta mensagens históricas recentes dos canais
        monitorados que mencionem o ticker, e retorna.

        Usa a API REST do Discord (sem necessidade do bot estar online).
        """
        headers = {
            "Authorization": f"Bot {self._token}",
            "User-Agent": "CorporateIntelMonitor (research, 1.0)",
        }

        async with httpx.AsyncClient(timeout=20) as client:
            for channel_id in self._channels:
                url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
                params = {"limit": 100}

                try:
                    resp = await client.get(url, headers=headers, params=params)
                    resp.raise_for_status()
                    messages = resp.json()
                except Exception as exc:
                    logger.warning("Discord canal %s: %s", channel_id, exc)
                    continue

                # Busca informação do canal para o nome
                channel_name = str(channel_id)
                try:
                    ch_resp = await client.get(
                        f"https://discord.com/api/v10/channels/{channel_id}",
                        headers=headers,
                    )
                    channel_name = ch_resp.json().get("name", str(channel_id))
                except Exception:
                    pass

                for msg in messages:
                    content = msg.get("content", "").strip()
                    if not content:
                        continue

                    # Filtra mensagens irrelevantes
                    if ticker.lower() not in content.lower():
                        continue

                    ts_str = msg.get("timestamp", "")
                    try:
                        published = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    except ValueError:
                        published = datetime.utcnow()

                    author = msg.get("author", {})
                    embeds = msg.get("embeds", [])
                    # Inclui texto de embeds (links, previews)
                    embed_text = " ".join(
                        e.get("title", "") + " " + e.get("description", "")
                        for e in embeds
                    )

                    yield RawArticle(
                        source=f"discord/#{channel_name}",
                        source_type="social",
                        url=f"https://discord.com/channels/@me/{channel_id}/{msg['id']}",
                        title=content[:140],
                        content=(content + "\n" + embed_text).strip()[:3000],
                        published_at=published,
                        company_ticker=ticker,
                        raw_metadata={
                            "channel_id":    channel_id,
                            "channel_name":  channel_name,
                            "author":        author.get("username"),
                            "author_bot":    author.get("bot", False),
                            "reactions":     [
                                {"emoji": r["emoji"].get("name"), "count": r["count"]}
                                for r in msg.get("reactions", [])
                            ],
                            "has_embeds":    len(embeds) > 0,
                        },
                    )


# =============================================================================
# TELEGRAM
# =============================================================================

class TelegramCollector:
    """
    Coleta mensagens de canais públicos do Telegram via Telethon.

    Pode ler qualquer canal/grupo público sem ser membro.
    Para canais privados, o usuário precisa ser membro.

    Config:
        TELEGRAM_API_ID   = 123456        (obtido em https://my.telegram.org)
        TELEGRAM_API_HASH = "abc123..."   (obtido em https://my.telegram.org)
        TELEGRAM_PHONE    = "+5511999..."  (número de telefone da conta)

    Canais financeiros BR sugeridos:
        @investidoresbr, @bolsadevaloresbr, @fatos_relevantes_cvm,
        @economiafinancas, @valoreconomico, @infomoneynoticias

    Canais financeiros US sugeridos:
        @wallstreetbets_official, @investing_news, @financial_times
    """

    # Canais públicos padrão para monitoramento
    DEFAULT_CHANNELS_BR = [
        "investidoresbr",
        "bolsanoticias",
        "economiafinancas",
        "valoreconomico",
    ]
    DEFAULT_CHANNELS_US = [
        "investing_news",
        "marketwatchnews",
    ]

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        phone: str,
        channels: list[str] | None = None,
        session_name: str = "cim_telegram",
    ):
        """
        Args:
            api_id:       ID da aplicação Telegram (https://my.telegram.org)
            api_hash:     Hash da aplicação Telegram
            phone:        Número de telefone da conta (com código país: +5511...)
            channels:     Lista de usernames de canais (@channel) ou IDs
            session_name: Nome do arquivo de sessão Telethon (.session)
        """
        self._api_id      = api_id
        self._api_hash    = api_hash
        self._phone       = phone
        self._channels    = channels
        self._session     = session_name

    async def collect(
        self,
        ticker: str,
        days_back: int = 7,
        limit_per_channel: int = 200,
        market: str = "auto",
    ) -> AsyncIterator[RawArticle]:
        """
        Coleta mensagens dos canais configurados que mencionem o ticker.

        Na primeira execução, o Telethon pedirá o código de verificação
        enviado ao seu Telegram. Após isso, a sessão é salva localmente.
        """
        try:
            from telethon import TelegramClient
            from telethon.tl.types import Message
        except ImportError:
            logger.error(
                "Telethon não instalado. Execute: pip install telethon"
            )
            return

        # Detecta canais padrão pelo mercado
        if self._channels is None:
            if market == "auto":
                market = "BR" if re.match(r"^[A-Z]{4}\d", ticker.upper()) else "US"
            self._channels = (
                self.DEFAULT_CHANNELS_BR if market == "BR"
                else self.DEFAULT_CHANNELS_US
            )

        from datetime import timedelta
        cutoff = datetime.utcnow().replace(tzinfo=timezone.utc) - timedelta(days=days_back)

        client = TelegramClient(self._session, self._api_id, self._api_hash)
        await client.start(phone=self._phone)

        try:
            for channel in self._channels:
                try:
                    entity = await client.get_entity(channel)
                except Exception as exc:
                    logger.warning("Telegram canal '%s': %s", channel, exc)
                    continue

                async for msg in client.iter_messages(
                    entity,
                    limit=limit_per_channel,
                    offset_date=None,
                    reverse=False,
                ):
                    if not isinstance(msg, Message):
                        continue
                    if msg.date < cutoff:
                        break

                    text = msg.text or msg.message or ""
                    if not text or ticker.lower() not in text.lower():
                        continue

                    # Resolve nome do canal
                    channel_title = getattr(entity, "title", channel)
                    channel_username = getattr(entity, "username", channel)

                    yield RawArticle(
                        source=f"telegram/@{channel_username}",
                        source_type="social",
                        url=f"https://t.me/{channel_username}/{msg.id}",
                        title=text[:140],
                        content=text[:3000],
                        published_at=msg.date.replace(tzinfo=timezone.utc),
                        company_ticker=ticker,
                        raw_metadata={
                            "channel":      channel_username,
                            "channel_title": channel_title,
                            "views":        getattr(msg, "views", 0) or 0,
                            "forwards":     getattr(msg, "forwards", 0) or 0,
                            "replies":      getattr(msg.replies, "replies", 0) if msg.replies else 0,
                            "has_media":    msg.media is not None,
                        },
                    )
        finally:
            await client.disconnect()


# =============================================================================
# FACTORY — cria coletores a partir de Settings
# =============================================================================

def build_social_collectors(settings) -> list:
    """
    Instancia os coletores de redes sociais com base nas configurações
    disponíveis. Pula silenciosamente os que não têm credenciais configuradas.

    Retorna lista de instâncias prontas para uso com `async with`.
    """
    collectors = []

    # StockTwits — sem autenticação, sempre disponível
    collectors.append(StockTwitsCollector(rate_limit_rps=2.0))

    # Twitter/X
    if getattr(settings, "twitter_bearer_token", None):
        collectors.append(
            TwitterCollector(
                bearer_token=settings.twitter_bearer_token,
                rate_limit_rps=0.5,
            )
        )
    else:
        logger.info("Twitter: TWITTER_BEARER_TOKEN não configurado, pulando.")

    # Reddit
    if getattr(settings, "reddit_client_id", None) and getattr(settings, "reddit_client_secret", None):
        collectors.append(
            RedditCollector(
                client_id=settings.reddit_client_id,
                client_secret=settings.reddit_client_secret,
                rate_limit_rps=1.0,
            )
        )
    else:
        logger.info("Reddit: credenciais não configuradas, pulando.")

    # Discord
    if getattr(settings, "discord_bot_token", None) and getattr(settings, "discord_channels", None):
        collectors.append(
            DiscordCollector(
                bot_token=settings.discord_bot_token,
                monitored_channels=settings.discord_channels,
            )
        )
    else:
        logger.info("Discord: DISCORD_BOT_TOKEN ou DISCORD_CHANNELS não configurados, pulando.")

    # Telegram
    if (
        getattr(settings, "telegram_api_id", None)
        and getattr(settings, "telegram_api_hash", None)
        and getattr(settings, "telegram_phone", None)
    ):
        collectors.append(
            TelegramCollector(
                api_id=settings.telegram_api_id,
                api_hash=settings.telegram_api_hash,
                phone=settings.telegram_phone,
                channels=getattr(settings, "telegram_channels", None),
            )
        )
    else:
        logger.info("Telegram: credenciais não configuradas, pulando.")

    # LinkedIn
    if getattr(settings, "linkedin_cookies_path", None):
        collectors.append(
            LinkedInCollector(
                cookies_path=settings.linkedin_cookies_path,
                rate_limit_rps=0.2,
            )
        )
    else:
        logger.info("LinkedIn: LINKEDIN_COOKIES_PATH não configurado, pulando.")

    return collectors
