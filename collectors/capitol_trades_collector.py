"""
Coleta negociações de congressistas americanos via Capitol Trades.

Capitol Trades (https://capitoltrades.com) agrega os disclosure obrigatórios
do STOCK Act (2012), cobrindo Câmara e Senado. A API pública não requer
autenticação e é mais estável do que o Quiver Quant sem API key.

Endpoint: https://api.capitoltrades.com/trades
  Parâmetros: issuerTicker={ticker}&pageSize=100&page=0
  Retorna JSON com `data` (lista de trades) e `meta.pagination`

Este coletor é alternativo/complementar ao PoliticianTradingCollector (Quiver Quant).
Use ambos para cobertura máxima — Capitol Trades tem dados mais recentes,
Quiver Quant tem o campo `excess_return`.
"""
import hashlib
import logging
from datetime import datetime, timedelta
from typing import AsyncIterator

from .base_collector import BaseCollector, RawArticle

logger = logging.getLogger(__name__)

CAPITOL_TRADES_API = "https://api.capitoltrades.com/trades"

_HEADERS = {
    "User-Agent": "CorporateIntelMonitor research@example.com",
    "Accept":     "application/json",
    "Referer":    "https://capitoltrades.com",
}

_TYPE_LABELS: dict[str, str] = {
    "buy":      "COMPRA",
    "sell":     "VENDA",
    "sell_full": "VENDA TOTAL",
    "exchange": "TROCA",
    "receive":  "RECEBIMENTO",
}


class CapitolTradesCollector(BaseCollector):
    """
    Coleta negociações de congressistas americanos via Capitol Trades API pública.

    Vantagens sobre Quiver Quant:
      - Sem API key necessária
      - Dados mais recentes (atualizados diariamente)
      - Inclui link direto para o disclosure oficial

    Limitações:
      - Sem campo excess_return (retorno vs mercado)
      - Rate limit mais agressivo (usa delay de 1s entre requests)
    """

    def __init__(self, rate_limit_rps: float = 0.5):
        super().__init__(rate_limit_rps=rate_limit_rps)

    async def collect(
        self,
        ticker: str,
        days_back: int = 90,
    ) -> AsyncIterator[RawArticle]:
        """
        Coleta transações de congressistas para o ticker dentro do período.

        Args:
            ticker:    Símbolo na bolsa americana (ex: AAPL, NVDA, TSM)
            days_back: Quantos dias retroativos buscar (default: 90)
        """
        ticker_upper = ticker.upper()
        cutoff       = datetime.utcnow() - timedelta(days=days_back)

        page = 0
        while True:
            params = {
                "issuerTicker": ticker_upper,
                "pageSize":     100,
                "page":         page,
            }
            try:
                resp = await self._get(CAPITOL_TRADES_API, headers=_HEADERS, params=params)
                payload = resp.json()
            except Exception as exc:
                logger.warning("CapitolTrades: erro na página %d para %s: %s", page, ticker_upper, exc)
                break

            trades = payload.get("data", [])
            if not trades:
                break

            for trade in trades:
                article = self._trade_to_article(trade, ticker_upper, cutoff)
                if article is None:
                    continue
                # Sinal de que passamos do período — dados vêm em ordem decrescente de data
                if article is False:
                    return
                yield article

            # Paginação
            meta       = payload.get("meta", {})
            pagination = meta.get("pagination", {})
            total      = pagination.get("totalCount", 0)
            page_size  = pagination.get("pageSize", 100)
            if (page + 1) * page_size >= total:
                break
            page += 1

    # ------------------------------------------------------------------
    # Conversão de trade → RawArticle
    # ------------------------------------------------------------------

    @staticmethod
    def _trade_to_article(trade: dict, ticker: str, cutoff: datetime):
        """
        Retorna RawArticle, None (pular), ou False (parar paginação).
        """
        # Data da transação
        date_str = trade.get("txDate") or trade.get("reportedAt") or ""
        date     = _parse_date(date_str)
        if not date:
            return None
        if date < cutoff:
            return False  # dados em ordem decrescente → pare

        # Político
        politician_obj = trade.get("politician") or {}
        first  = politician_obj.get("firstName") or ""
        last   = politician_obj.get("lastName")  or ""
        name   = f"{first} {last}".strip() or politician_obj.get("name") or "N/D"
        party  = politician_obj.get("party") or ""
        state  = politician_obj.get("state") or ""
        chamber_raw = (
            politician_obj.get("chamber")
            or trade.get("chamber")
            or ""
        ).lower()

        if "house" in chamber_raw or "rep" in chamber_raw:
            chamber_label = "House (Câmara)"
            disclosure_base = "https://disclosures.house.gov"
        elif "senate" in chamber_raw or "sen" in chamber_raw:
            chamber_label = "Senate (Senado)"
            disclosure_base = "https://efts.senate.gov"
        else:
            chamber_label = chamber_raw or "Congress"
            disclosure_base = "https://capitoltrades.com"

        # Empresa / ticker
        issuer     = trade.get("issuer") or {}
        company    = issuer.get("name") or ticker

        # Tipo de transação
        tx_type_raw = (trade.get("txType") or "").lower()
        type_label  = _TYPE_LABELS.get(tx_type_raw, tx_type_raw.upper() or "TRANSAÇÃO")

        # Valor
        amount_raw = trade.get("amount") or trade.get("size") or ""
        amount_str = str(amount_raw) if amount_raw else "N/D"

        # Partido/estado
        party_str = f"({party[:1]}-{state})" if party and state else f"({party})" if party else ""

        # Filing
        filed_str  = trade.get("filedAt") or trade.get("reportedAt") or ""
        filed_date = _parse_date(filed_str[:10] if filed_str else "")

        title = (
            f"[POLÍTICO][{type_label}] {name} {party_str} — "
            f"{ticker} | {amount_str} | {chamber_label}"
        ).strip()

        lines = [
            f"Político:         {name}",
            f"Câmara:           {chamber_label}",
            f"Partido:          {party}",
        ]
        if state:
            lines.append(f"Estado:           {state}")
        lines += [
            f"Tipo:             {type_label} ({tx_type_raw})",
            f"Ticker:           {ticker}",
            f"Empresa:          {company}",
            f"Valor estimado:   {amount_str}",
            f"Data transação:   {date.strftime('%d/%m/%Y')}",
        ]
        if filed_date:
            lines.append(f"Data do filing:   {filed_date.strftime('%d/%m/%Y')}")

        # Capitol Trades fornece link para o filing original
        ct_link = trade.get("disclosureUrl") or trade.get("url") or ""
        if ct_link:
            lines.append(f"Disclosure:       {ct_link}")
        lines.append(f"Fonte:            Capitol Trades (capitoltrades.com)")

        content = "\n".join(lines)

        # URL única para deduplicação
        uid = hashlib.sha256(
            f"{name}|{date.isoformat()}|{ticker}|{tx_type_raw}|{amount_raw}".encode()
        ).hexdigest()[:20]

        disclosure_url = ct_link or f"{disclosure_base}#ct-{uid}"

        return RawArticle(
            source="Capitol Trades",
            source_type="politician_trade",
            url=disclosure_url,
            title=title,
            content=content,
            published_at=date,
            company_ticker=ticker,
            company_name=company,
            raw_metadata={
                "politician":        name,
                "party":             party,
                "state":             state,
                "chamber":           chamber_label,
                "transaction_type":  tx_type_raw,
                "transaction_label": type_label,
                "amount":            amount_raw,
                "filed_date":        filed_str,
                "disclosure_url":    ct_link,
            },
        )


def _parse_date(date_str: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None
