"""
Coletores de Mercados de Aposta / Previsão para o Corporate Intelligence Monitor.

Perfil de uso de cada plataforma:

Plataforma     | Perfil                              | Tipo de dado capturado
---------------|-------------------------------------|-------------------------------------
Polymarket     | Aposta pura em eventos/notícias     | Probabilidade implícita (CLOB)
Kalshi         | Aposta regulada em eventos          | Probabilidade implícita (CFTC)
Metaculus      | Previsão coletiva de longo prazo    | Mediana comunitária de probabilidade
Betfair        | Apostas entre usuários (exchange)   | Odds peer-to-peer, back/lay
Deriv          | Aposta técnica em gráficos          | Cotação de binary option (prob. direcional)
IQ Option      | Aposta técnica curto prazo          | Payout/prob. de binary option

Notas de compliance:
    - Polymarket: mercado descentralizado (Polygon). Sem KYC para leitura.
    - Kalshi: regulado pela CFTC (EUA). Requer conta verificada para negociar,
              mas a API de leitura de mercados é pública.
    - Betfair: leitura de odds via API pública com app key gratuita (não-apostas).
    - Deriv / IQ Option: plataformas de derivativos offshore. Consulte a legislação
              vigente antes de usar para tomada de decisão de investimento.

Dependências:
    pip install httpx websockets betfairlightweight
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import AsyncIterator

import httpx

from .base_collector import BaseCollector, RawArticle

logger = logging.getLogger(__name__)


# =============================================================================
# POLYMARKET  —  Mercado de previsão descentralizado (Polygon)
# API pública: https://gamma-api.polymarket.com
# =============================================================================

class PolymarketCollector(BaseCollector):
    """
    Coleta mercados abertos do Polymarket relacionados a um ticker/empresa.

    Dado chave: `outcomePrices` — cada preço é a probabilidade implícita
    de aquele outcome ocorrer (0.00–1.00 = 0%–100%).

    Exemplo de mercado relevante:
        "Will NVIDIA report revenue above $26B in Q1 2025?"
        Prices: ["0.72", "0.28"]  → 72% chance de SIM
    """

    API_URL = "https://gamma-api.polymarket.com/markets"

    async def collect(self, ticker: str, **_) -> AsyncIterator[RawArticle]:
        params = {
            "search":  ticker,
            "active":  "true",
            "closed":  "false",
            "limit":   30,
            "order":   "volume",
            "ascending": "false",
        }
        try:
            resp = await self._get(self.API_URL, params=params)
            markets = resp.json()
        except Exception as exc:
            logger.warning("Polymarket: %s", exc)
            return

        for market in markets:
            raw_prices = market.get("outcomePrices") or "[]"
            raw_outcomes = market.get("outcomes") or "[]"

            # outcomePrices pode vir como string JSON ou como lista
            if isinstance(raw_prices, str):
                try:
                    prices = json.loads(raw_prices)
                except json.JSONDecodeError:
                    prices = []
            else:
                prices = raw_prices

            if isinstance(raw_outcomes, str):
                try:
                    outcomes = json.loads(raw_outcomes)
                except json.JSONDecodeError:
                    outcomes = []
            else:
                outcomes = raw_outcomes

            # Monta tabela legível de probabilidades
            prob_table = " | ".join(
                f"{o}: {float(p):.1%}"
                for o, p in zip(outcomes, prices)
                if p is not None
            )

            volume   = float(market.get("volume")   or 0)
            liquidity = float(market.get("liquidity") or 0)

            content = (
                f"Mercado: {market.get('question')}\n"
                f"Probabilidades: {prob_table}\n"
                f"Volume negociado: ${volume:,.0f} | Liquidez: ${liquidity:,.0f}\n"
                f"Encerra: {market.get('endDate', 'N/A')}"
            )

            yield RawArticle(
                source="polymarket",
                source_type="betting",
                url=f"https://polymarket.com/event/{market.get('slug', '')}",
                title=market.get("question", "")[:200],
                content=content,
                published_at=_parse_dt(market.get("startDate")),
                company_ticker=ticker,
                raw_metadata={
                    "platform":       "polymarket",
                    "outcomes":       outcomes,
                    "outcome_prices": prices,
                    "prob_table":     prob_table,
                    "volume_usd":     volume,
                    "liquidity_usd":  liquidity,
                    "end_date":       market.get("endDate"),
                    "condition_id":   market.get("conditionId"),
                },
            )


# =============================================================================
# KALSHI  —  Mercado de previsão regulado (CFTC, EUA)
# API pública: https://trading-api.kalshi.com/trade-api/v2
# Documentação: https://trading-api.kalshi.com/trade-api/v2/openapi.json
# =============================================================================

class KalshiCollector(BaseCollector):
    """
    Coleta mercados abertos do Kalshi relacionados a um ticker/empresa.

    Kalshi é regulado pela CFTC — os contratos são legalmente reconhecidos
    como instrumentos de hedge nos EUA (ex: "Will AAPL beat earnings?").

    Autenticação:
        - Leitura pública: sem autenticação (mercados abertos visíveis).
        - Negociação: requer email + senha → token JWT.

    Config (opcional para acesso a dados privados):
        KALSHI_EMAIL    = "user@example.com"
        KALSHI_PASSWORD = "..."
    """

    BASE_URL  = "https://trading-api.kalshi.com/trade-api/v2"
    LOGIN_URL = f"{BASE_URL}/login"

    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
        rate_limit_rps: float = 2.0,
    ):
        super().__init__(rate_limit_rps=rate_limit_rps)
        self._email    = email
        self._password = password
        self._token:   str | None = None

    async def _ensure_auth(self):
        """Login opcional — necessário apenas para dados de portfólio."""
        if self._token or not (self._email and self._password):
            return
        try:
            resp = await self._get(
                self.LOGIN_URL,
                # POST via _get não funciona; usa client diretamente
            )
        except Exception:
            pass

        if self._client and self._email and self._password:
            try:
                resp = await self._client.post(
                    self.LOGIN_URL,
                    json={"email": self._email, "password": self._password},
                )
                resp.raise_for_status()
                self._token = resp.json().get("token")
            except Exception as exc:
                logger.warning("Kalshi auth: %s", exc)

    def _auth_headers(self) -> dict:
        if self._token:
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    async def collect(self, ticker: str, **_) -> AsyncIterator[RawArticle]:
        await self._ensure_auth()

        # Kalshi não tem busca full-text por ticker diretamente.
        # Estratégia: busca eventos abertos e filtra pelo nome da empresa.
        params = {
            "limit":  200,
            "status": "open",
        }
        try:
            resp = await self._get(
                f"{self.BASE_URL}/events",
                params=params,
                headers=self._auth_headers(),
            )
            events = resp.json().get("events", [])
        except Exception as exc:
            logger.warning("Kalshi events: %s", exc)
            return

        ticker_lower = ticker.lower()

        for event in events:
            title = event.get("title", "") or ""
            subtitle = event.get("sub_title", "") or ""
            series   = event.get("series_ticker", "") or ""

            # Filtra por relevância ao ticker
            haystack = (title + subtitle + series).lower()
            if ticker_lower not in haystack:
                continue

            # Busca os mercados individuais do evento
            event_ticker = event.get("event_ticker", "")
            markets = await self._fetch_event_markets(event_ticker)

            for market in markets:
                yes_bid  = market.get("yes_bid",  0) / 100   # Kalshi usa centavos
                yes_ask  = market.get("yes_ask",  0) / 100
                no_bid   = market.get("no_bid",   0) / 100
                volume   = market.get("volume",   0)
                open_interest = market.get("open_interest", 0)

                yes_mid = (yes_bid + yes_ask) / 2 if yes_bid and yes_ask else yes_bid or yes_ask

                content = (
                    f"Mercado Kalshi: {market.get('title', title)}\n"
                    f"Probabilidade YES: {yes_mid:.1%} "
                    f"(bid {yes_bid:.1%} / ask {yes_ask:.1%})\n"
                    f"Volume de contratos: {volume:,} | "
                    f"Open interest: {open_interest:,}\n"
                    f"Encerra: {market.get('close_time', 'N/A')}"
                )

                yield RawArticle(
                    source="kalshi",
                    source_type="betting",
                    url=f"https://kalshi.com/markets/{event_ticker}",
                    title=f"[Kalshi] {market.get('title', title)[:180]}",
                    content=content,
                    published_at=_parse_dt(market.get("open_time")),
                    company_ticker=ticker,
                    raw_metadata={
                        "platform":       "kalshi",
                        "event_ticker":   event_ticker,
                        "market_ticker":  market.get("ticker"),
                        "yes_bid":        yes_bid,
                        "yes_ask":        yes_ask,
                        "yes_mid":        yes_mid,
                        "no_bid":         no_bid,
                        "volume":         volume,
                        "open_interest":  open_interest,
                        "close_time":     market.get("close_time"),
                        "result":         market.get("result"),
                        "status":         market.get("status"),
                    },
                )

    async def _fetch_event_markets(self, event_ticker: str) -> list[dict]:
        """Busca os mercados individuais de um evento Kalshi."""
        if not event_ticker:
            return []
        try:
            resp = await self._get(
                f"{self.BASE_URL}/events/{event_ticker}",
                headers=self._auth_headers(),
            )
            return resp.json().get("markets", [])
        except Exception:
            return []


# =============================================================================
# METACULUS  —  Previsão coletiva colaborativa
# API pública: https://www.metaculus.com/api2
# =============================================================================

class MetaculusCollector(BaseCollector):
    """
    Metaculus — plataforma de forecasting colaborativo.

    Dado chave: `community_prediction.full.q2` (mediana das previsões).
    Foco: eventos de médio/longo prazo (resultados, regulação, M&A).

    Sem autenticação necessária para leitura.
    """

    API_URL = "https://www.metaculus.com/api2/questions/"

    async def collect(self, ticker: str, **_) -> AsyncIterator[RawArticle]:
        params = {
            "search":   ticker,
            "status":   "open",
            "order_by": "-activity",
            "limit":    20,
        }
        try:
            resp = await self._get(self.API_URL, params=params)
            questions = resp.json().get("results", [])
        except Exception as exc:
            logger.warning("Metaculus: %s", exc)
            return

        for q in questions:
            community = (q.get("community_prediction") or {})
            full = (community.get("full") or {})
            prob = full.get("q2")  # mediana

            prob_str = f"{prob:.1%}" if prob is not None else "sem previsão ainda"

            content = (
                f"Pergunta: {q['title']}\n"
                f"Probabilidade comunitária (mediana): {prob_str}\n"
                f"Previsores: {q.get('number_of_predictions', 0)}\n"
                f"Resolução esperada: {q.get('resolve_time', 'N/A')}\n\n"
                + (q.get("description") or "")[:600]
            )

            yield RawArticle(
                source="metaculus",
                source_type="betting",
                url=f"https://www.metaculus.com{q['page_url']}",
                title=q["title"][:200],
                content=content,
                published_at=_parse_dt(q.get("created_time")),
                company_ticker=ticker,
                raw_metadata={
                    "platform":        "metaculus",
                    "probability":     prob,
                    "num_predictions": q.get("number_of_predictions", 0),
                    "resolve_time":    q.get("resolve_time"),
                    "q1":              full.get("q1"),   # percentil 25
                    "q3":              full.get("q3"),   # percentil 75
                    "status":          q.get("status"),
                    "resolution":      q.get("resolution"),
                },
            )


# =============================================================================
# BETFAIR  —  Maior exchange de apostas peer-to-peer do mundo
# API REST: https://api.betfair.com/exchange/betting/rest/v1.0/
# Documentação: https://developer.betfair.com
# =============================================================================

class BetfairCollector(BaseCollector):
    """
    Coleta odds de mercados financeiros no Betfair Exchange.

    O Betfair tem uma seção de "Financial Spreads" e mercados de eventos
    corporativos (resultados de empresas, movimentação de CEOs).

    Dado chave: back/lay prices — a diferença entre as odds implica a
    margem de probabilidade do mercado peer-to-peer.

    Autenticação:
        - App Key gratuita (leitura sem negociar): https://developer.betfair.com
        - Login via API com usuário + senha + certificado SSL

    Config:
        BETFAIR_USERNAME   = "user@example.com"
        BETFAIR_PASSWORD   = "..."
        BETFAIR_APP_KEY    = "abc123"   # delayed data key (gratuita)
    """

    LOGIN_URL  = "https://identitysso-cert.betfair.com/api/certlogin"
    API_URL    = "https://api.betfair.com/exchange/betting/rest/v1.0"

    # IDs de categorias relevantes no Betfair
    # 6423 = Financial Spreads | 6231 = Politics | 26420299 = Current Affairs
    FINANCIAL_EVENT_TYPE_ID = "6423"

    def __init__(
        self,
        username: str,
        password: str,
        app_key: str,
        rate_limit_rps: float = 2.0,
    ):
        super().__init__(rate_limit_rps=rate_limit_rps)
        self._username = username
        self._password = password
        self._app_key  = app_key
        self._session_token: str | None = None

    async def _login(self):
        """Autentica na Betfair API via certificado SSL (app não interativa)."""
        if self._session_token:
            return

        # Betfair exige certificado SSL p/ login de app — usa endpoint simplificado
        data = {"username": self._username, "password": self._password}
        headers = {"X-Application": self._app_key, "Content-Type": "application/x-www-form-urlencoded"}

        try:
            resp = await self._client.post(
                "https://identitysso.betfair.com/api/login",
                data=data,
                headers=headers,
            )
            result = resp.json()
            if result.get("status") == "SUCCESS":
                self._session_token = result["token"]
            else:
                logger.error("Betfair login falhou: %s", result.get("error"))
        except Exception as exc:
            logger.error("Betfair login: %s", exc)

    def _api_headers(self) -> dict:
        return {
            "X-Application":   self._app_key,
            "X-Authentication": self._session_token or "",
            "Content-Type":    "application/json",
            "Accept":          "application/json",
        }

    async def _post(self, endpoint: str, payload: dict) -> dict:
        url = f"{self.API_URL}/{endpoint}/"
        resp = await self._client.post(
            url,
            json=payload,
            headers=self._api_headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def collect(self, ticker: str, **_) -> AsyncIterator[RawArticle]:
        await self._login()
        if not self._session_token:
            logger.warning("Betfair: sem sessão ativa, pulando coleta.")
            return

        # Busca eventos com o ticker no nome
        try:
            events = await self._post("listEvents", {
                "filter": {
                    "textQuery": ticker,
                    "eventTypeIds": [self.FINANCIAL_EVENT_TYPE_ID],
                },
                "locale": "en",
            })
        except Exception as exc:
            logger.warning("Betfair listEvents: %s", exc)
            return

        for event_result in events:
            event = event_result.get("event", {})
            event_id = event.get("id")
            if not event_id:
                continue

            # Busca mercados do evento
            try:
                markets = await self._post("listMarketCatalogue", {
                    "filter": {"eventIds": [event_id]},
                    "marketProjection": ["RUNNER_DESCRIPTION", "MARKET_START_TIME"],
                    "maxResults": 20,
                })
            except Exception:
                continue

            for market in markets:
                market_id = market.get("marketId")
                if not market_id:
                    continue

                # Busca odds atuais (back/lay)
                try:
                    books = await self._post("listMarketBook", {
                        "marketIds": [market_id],
                        "priceProjection": {"priceData": ["EX_BEST_OFFERS"]},
                    })
                    book = books[0] if books else {}
                except Exception:
                    book = {}

                runners_summary = []
                for runner in book.get("runners", []):
                    ex = runner.get("ex", {})
                    best_back = ex.get("availableToBack", [{}])[0].get("price")
                    best_lay  = ex.get("availableToLay",  [{}])[0].get("price")

                    # Converte odds decimais para probabilidade implícita
                    prob_back = (1 / best_back) if best_back else None
                    prob_lay  = (1 / best_lay)  if best_lay  else None

                    runner_name = next(
                        (r["runnerName"] for r in market.get("runners", [])
                         if r.get("selectionId") == runner.get("selectionId")),
                        str(runner.get("selectionId", "?")),
                    )
                    runners_summary.append({
                        "name":      runner_name,
                        "back_odds": best_back,
                        "lay_odds":  best_lay,
                        "prob_back": prob_back,
                        "prob_lay":  prob_lay,
                    })

                prob_lines = "\n".join(
                    f"  {r['name']}: back {r['back_odds']} "
                    f"({r['prob_back']:.1%} impl.)" if r["prob_back"] else f"  {r['name']}: sem odds"
                    for r in runners_summary
                )

                content = (
                    f"Mercado Betfair: {market.get('marketName', '')} "
                    f"({event.get('name', '')})\n"
                    f"Tipo: {market.get('marketType', 'N/A')}\n"
                    f"Runners e probabilidades implícitas:\n{prob_lines}\n"
                    f"Status: {book.get('status', 'N/A')} | "
                    f"Volume em jogo: £{book.get('totalMatched', 0):,.0f}"
                )

                start_time = market.get("marketStartTime", "")

                yield RawArticle(
                    source="betfair",
                    source_type="betting",
                    url=f"https://www.betfair.com/exchange/plus/en/betting-event-{event_id}",
                    title=f"[Betfair] {event.get('name', '')} — {market.get('marketName', '')}",
                    content=content,
                    published_at=_parse_dt(start_time),
                    company_ticker=ticker,
                    raw_metadata={
                        "platform":       "betfair",
                        "event_id":       event_id,
                        "market_id":      market_id,
                        "market_name":    market.get("marketName"),
                        "market_type":    market.get("marketType"),
                        "total_matched":  book.get("totalMatched", 0),
                        "runners":        runners_summary,
                        "status":         book.get("status"),
                    },
                )


# =============================================================================
# DERIV  —  Binary options / CFD (aposta técnica direcional de curto prazo)
# WebSocket API: wss://ws.binaryws.com/websockets/v3?app_id=1089
# Documentação: https://api.deriv.com
# =============================================================================

class DerivCollector:
    """
    Coleta cotações de binary options (contratos de curto prazo) via Deriv API.

    O PREÇO de um binary call option = probabilidade implícita de mercado
    de que o ativo estará ACIMA do preço atual na expiração.

    Exemplo:
        CALL em AAPL expirando em 1h custando $0.67 → mercado atribui
        67% de chance de AAPL subir na próxima hora.

    Isso captura o **sentimento técnico de curtíssimo prazo** de traders
    especializados, complementando o sentimento fundamental das notícias.

    Tipos de contrato capturados:
        CALL/PUT    → direção de preço (subir/cair)
        ONETOUCH    → se o ativo tocar determinado nível
        RANGE/EXITE → se o ativo fica dentro/fora de uma faixa

    Config:
        DERIV_APP_ID = "1089"   (ID público para leitura; crie o seu em binary.com/app_register)
        DERIV_TOKEN  = "..."    (opcional, necessário para negociar)

    Dependências:
        pip install websockets
    """

    WS_URL = "wss://ws.binaryws.com/websockets/v3?app_id={app_id}"

    # Mapa de ticker → símbolo Deriv
    # Lista completa: https://api.deriv.com/api-explorer/#active_symbols
    SYMBOL_MAP: dict[str, str] = {
        # Índices US
        "SPX":    "R_100",    # S&P 500 Synthetic (proxy)
        "NDX":    "R_75",     # Nasdaq Synthetic
        # Ações via CFD (Deriv oferece CFDs em ações selecionadas)
        "AAPL":   "AAPL",
        "MSFT":   "MSFT",
        "NVDA":   "NVDA",
        "TSLA":   "TSLA",
        "AMZN":   "AMZN",
        "GOOGL":  "GOOGL",
        "META":   "META",
        # Forex (correlação com ativos BR)
        "USDBRL": "frxUSDBRL",
        "EURUSD": "frxEURUSD",
    }

    # Durações para cotação (em segundos)
    DURATIONS = [
        (3600,  "1h"),
        (86400, "1d"),
    ]

    def __init__(self, app_id: str = "1089", token: str | None = None):
        self._app_id = app_id
        self._token  = token

    async def collect(
        self, ticker: str, **_
    ) -> AsyncIterator[RawArticle]:
        """
        Solicita cotações de binary CALL e PUT para o ticker,
        extraindo a probabilidade implícita de curto prazo.
        """
        try:
            import websockets
        except ImportError:
            logger.error("websockets não instalado: pip install websockets")
            return

        symbol = self.SYMBOL_MAP.get(ticker.upper())
        if not symbol:
            logger.info(
                "Deriv: símbolo '%s' não mapeado. Adicione em SYMBOL_MAP.", ticker
            )
            return

        ws_url = self.WS_URL.format(app_id=self._app_id)

        try:
            async with websockets.connect(ws_url, ping_interval=None) as ws:
                if self._token:
                    await ws.send(json.dumps({"authorize": self._token}))
                    await ws.recv()

                for duration_sec, duration_label in self.DURATIONS:
                    for contract_type in ("CALL", "PUT"):
                        request = {
                            "proposal": 1,
                            "amount":   100,
                            "basis":    "stake",
                            "contract_type": contract_type,
                            "currency": "USD",
                            "duration": duration_sec,
                            "duration_unit": "s",
                            "symbol": symbol,
                        }
                        await ws.send(json.dumps(request))
                        raw = await asyncio.wait_for(ws.recv(), timeout=10)
                        data = json.loads(raw)

                        if "error" in data:
                            logger.debug(
                                "Deriv %s %s: %s",
                                contract_type, symbol, data["error"]["message"]
                            )
                            continue

                        proposal = data.get("proposal", {})
                        payout   = float(proposal.get("payout", 0))
                        stake    = 100.0
                        # Probabilidade implícita = stake / payout
                        implied_prob = (stake / payout) if payout > 0 else None

                        direction = "SUBIR" if contract_type == "CALL" else "CAIR"
                        prob_str  = f"{implied_prob:.1%}" if implied_prob else "N/A"

                        content = (
                            f"Binary {contract_type} — {symbol} em {duration_label}\n"
                            f"Probabilidade implícita de {direction}: {prob_str}\n"
                            f"Cotação: ${stake:.0f} stake → ${payout:.2f} payout\n"
                            f"Spot: {proposal.get('spot', 'N/A')} | "
                            f"Barreira: {proposal.get('barrier', 'N/A')}"
                        )

                        yield RawArticle(
                            source="deriv",
                            source_type="betting",
                            url=f"https://app.deriv.com/",
                            title=f"[Deriv] {symbol} {contract_type} {duration_label} — prob. {prob_str}",
                            content=content,
                            published_at=datetime.now(timezone.utc),
                            company_ticker=ticker,
                            raw_metadata={
                                "platform":       "deriv",
                                "symbol":         symbol,
                                "contract_type":  contract_type,
                                "duration_label": duration_label,
                                "duration_sec":   duration_sec,
                                "implied_prob":   implied_prob,
                                "payout":         payout,
                                "stake":          stake,
                                "spot":           proposal.get("spot"),
                                "barrier":        proposal.get("barrier"),
                                "id":             proposal.get("id"),
                            },
                        )

                        await asyncio.sleep(0.5)

        except Exception as exc:
            logger.warning("Deriv WebSocket: %s", exc)


# =============================================================================
# IQ OPTION  —  Plataforma de binary options e digital options
# WebSocket API (não oficial): via iqoptionapi
# =============================================================================

class IQOptionCollector:
    """
    Coleta dados de probabilidade implícita de binary/digital options na IQ Option.

    O preço de uma digital option = probabilidade implícita do movimento.
    Foco: sentimento direcional de curtíssimo prazo (1–5 minutos).

    AVISO: A IQ Option não disponibiliza API oficial pública.
    Esta implementação usa a biblioteca iqoptionapi (engenharia reversa do WebSocket).
    Verifique os Termos de Serviço antes de usar.

    Alternativa recomendada: use DerivCollector, que tem API oficial.

    Config:
        IQ_OPTION_EMAIL    = "user@example.com"
        IQ_OPTION_PASSWORD = "..."

    Dependências:
        pip install iqoptionapi
    """

    # Mapa de ticker → ativo IQ Option
    ASSET_MAP: dict[str, str] = {
        "AAPL":   "AAPL",
        "MSFT":   "MSFT",
        "NVDA":   "NVDA",
        "TSLA":   "TSLA",
        "GOOGL":  "GOOGL",
        "AMZN":   "AMZN",
        "META":   "META",
        "USDBRL": "USDBRL",
    }

    def __init__(self, email: str, password: str):
        self._email    = email
        self._password = password

    async def collect(self, ticker: str, **_) -> AsyncIterator[RawArticle]:
        asset = self.ASSET_MAP.get(ticker.upper())
        if not asset:
            logger.info("IQ Option: ativo '%s' não mapeado.", ticker)
            return

        try:
            from iqoptionapi.stable_api import IQ_Option
        except ImportError:
            logger.error(
                "iqoptionapi não instalado: pip install iqoptionapi\n"
                "Alternativa oficial: use DerivCollector."
            )
            return

        api = IQ_Option(self._email, self._password)
        check, reason = api.connect()

        if not check:
            logger.error("IQ Option: falha no login — %s", reason)
            return

        try:
            for duration_min in (1, 5):
                # Busca dados do candle atual para calcular win rate implícito
                candles = api.get_candles(asset, 60 * duration_min, 10, time=None)
                if not candles:
                    continue

                # Win rate = % de candles de alta nos últimos 10 períodos
                bullish = sum(1 for c in candles if c["close"] > c["open"])
                win_rate_call = bullish / len(candles) if candles else 0.5
                win_rate_put  = 1 - win_rate_call

                content = (
                    f"IQ Option — {asset} (expiração {duration_min}min)\n"
                    f"Win rate implícito CALL (alta): {win_rate_call:.1%}\n"
                    f"Win rate implícito PUT (baixa): {win_rate_put:.1%}\n"
                    f"Baseado em {len(candles)} candles recentes de {duration_min}min"
                )

                yield RawArticle(
                    source="iqoption",
                    source_type="betting",
                    url="https://iqoption.com/",
                    title=f"[IQ Option] {asset} {duration_min}min — CALL {win_rate_call:.1%} / PUT {win_rate_put:.1%}",
                    content=content,
                    published_at=datetime.now(timezone.utc),
                    company_ticker=ticker,
                    raw_metadata={
                        "platform":        "iqoption",
                        "asset":           asset,
                        "duration_min":    duration_min,
                        "win_rate_call":   win_rate_call,
                        "win_rate_put":    win_rate_put,
                        "candles_sampled": len(candles),
                    },
                )
        finally:
            api.close()


# =============================================================================
# FACTORY  —  Instancia coletores a partir das Settings
# =============================================================================

def build_betting_collectors(settings) -> list:
    """
    Instancia os coletores de apostas/previsão com base nas configurações.
    Coletores sem credenciais obrigatórias são sempre incluídos.
    """
    collectors = []

    # Polymarket — sem autenticação
    collectors.append(PolymarketCollector(rate_limit_rps=1.0))

    # Metaculus — sem autenticação
    collectors.append(MetaculusCollector(rate_limit_rps=1.0))

    # Kalshi — leitura pública disponível sem auth
    collectors.append(KalshiCollector(
        email=getattr(settings, "kalshi_email", None),
        password=getattr(settings, "kalshi_password", None),
        rate_limit_rps=2.0,
    ))

    # Betfair — requer app key + conta
    if (
        getattr(settings, "betfair_username", None)
        and getattr(settings, "betfair_password", None)
        and getattr(settings, "betfair_app_key", None)
    ):
        collectors.append(BetfairCollector(
            username=settings.betfair_username,
            password=settings.betfair_password,
            app_key=settings.betfair_app_key,
        ))
    else:
        logger.info("Betfair: credenciais não configuradas, pulando.")

    # Deriv — app_id público disponível, token opcional
    collectors.append(DerivCollector(
        app_id=getattr(settings, "deriv_app_id", "1089"),
        token=getattr(settings, "deriv_token", None),
    ))

    # IQ Option — requer conta
    if (
        getattr(settings, "iq_option_email", None)
        and getattr(settings, "iq_option_password", None)
    ):
        collectors.append(IQOptionCollector(
            email=settings.iq_option_email,
            password=settings.iq_option_password,
        ))
    else:
        logger.info("IQ Option: credenciais não configuradas, pulando.")

    return collectors


# =============================================================================
# HELPERS
# =============================================================================

def _parse_dt(value: str | None) -> datetime:
    """Converte string ISO 8601 para datetime, com fallback para agora."""
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)
