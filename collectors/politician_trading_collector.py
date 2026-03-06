"""
Coleta negociações de ações por congressistas americanos (STOCK Act).

Fonte: Quiver Quantitative bulk congressional trading dataset
  https://api.quiverquant.com/beta/bulk/congresstrading
  (endpoint público, sem autenticação, ~110k transações)

O STOCK Act (2012) obriga congressistas a divulgar transações de ativos
financeiros em até 45 dias. Os dados incluem nome, partido, câmara,
ticker negociado, tipo (compra/venda) e valor estimado.

O campo `excess_return` indica o retorno da ação nos dias seguintes
à transação vs. o mercado — útil para detectar trades informativos.

Mapeamento de comitês regulatórios por setor (metadado informativo):
  Semicondutores/Tech: Senate Commerce | House Science & Technology
                       Senate Armed Services | House Armed Services
  Finanças:            Senate Banking  | House Financial Services
  Energia:             Senate Energy   | House Energy & Commerce
  Saúde:               Senate HELP     | Senate Finance
  Defesa:              Senate Armed Services | House Armed Services
"""
import hashlib
import logging
from datetime import datetime, timedelta
from typing import AsyncIterator

from .base_collector import BaseCollector, RawArticle

logger = logging.getLogger(__name__)

QUIVER_BULK_URL = "https://api.quiverquant.com/beta/bulk/congresstrading"

_HEADERS = {"User-Agent": "CorporateIntelMonitor research@example.com"}

# Mapeamento de comitês regulatórios relevantes por setor
REGULATORY_COMMITTEES: dict[str, list[str]] = {
    "semiconductor": [
        "Senate Commerce, Science, and Transportation",
        "House Science, Space, and Technology",
        "Senate Armed Services",
        "House Armed Services",
    ],
    "finance": [
        "Senate Banking, Housing, and Urban Affairs",
        "House Financial Services",
        "Senate Finance",
    ],
    "energy": [
        "Senate Energy and Natural Resources",
        "House Energy and Commerce",
        "Senate Environment and Public Works",
    ],
    "healthcare": [
        "Senate Health, Education, Labor, and Pensions (HELP)",
        "Senate Finance",
        "House Energy and Commerce",
    ],
    "defense": [
        "Senate Armed Services",
        "House Armed Services",
        "Senate Appropriations",
        "House Appropriations",
    ],
    "telecom": [
        "Senate Commerce, Science, and Transportation",
        "House Energy and Commerce",
    ],
}

# Tickers mapeados por setor (para enriquecer metadados com comitês relevantes)
_SECTOR_MAP: dict[str, str] = {
    "TSM": "semiconductor",  "NVDA": "semiconductor", "INTC": "semiconductor",
    "AMD": "semiconductor",  "QCOM": "semiconductor", "AMAT": "semiconductor",
    "LRCX": "semiconductor", "KLAC": "semiconductor", "ASML": "semiconductor",
    "MU":  "semiconductor",  "AVGO": "semiconductor", "MCHP": "semiconductor",
    "AAPL": "semiconductor", "MSFT": "semiconductor", "GOOGL": "semiconductor",
    "META": "semiconductor", "AMZN": "semiconductor",
    "JPM":  "finance",  "BAC": "finance",  "GS": "finance",
    "MS":   "finance",  "C":   "finance",  "WFC": "finance",  "BLK": "finance",
    "XOM":  "energy",   "CVX": "energy",   "COP": "energy",   "SLB": "energy",
    "JNJ":  "healthcare", "PFE": "healthcare", "MRK": "healthcare",
    "ABBV": "healthcare", "UNH": "healthcare", "LLY": "healthcare",
    "LMT":  "defense",  "RTX": "defense",  "NOC": "defense",
    "GD":   "defense",  "BA":  "defense",  "HII": "defense",
}


class PoliticianTradingCollector(BaseCollector):
    """
    Coleta negociações de congressistas americanos filtradas por ticker.

    Usa o dataset bulk do Quiver Quantitative (gratuito, sem autenticação),
    que agrega Câmara e Senado com ~110k transações históricas.

    Emite um RawArticle por transação, com:
      - Título:  [POLÍTICO][COMPRA/VENDA] Nome (Partido) — TICKER | $Valor | Câmara
      - Campos:  câmara, partido, estado, distrito, BioGuideID, tipo, valor,
                 excess_return (retorno vs mercado pós-transação)
      - Metadado: comitês regulatórios relevantes para o setor da empresa

    API key do Quiver Quant (gratuita em https://quiverquant.com):
      Sem key: endpoint bulk pode retornar 401 por rate limiting de IP
      Com key:  acesso estável via Authorization: Token {key}
    """

    def __init__(self, rate_limit_rps: float = 0.5, api_key: str | None = None):
        super().__init__(rate_limit_rps=rate_limit_rps)
        self._api_key = api_key

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    async def collect(
        self,
        ticker: str,
        days_back: int = 30,
    ) -> AsyncIterator[RawArticle]:
        """
        Coleta transações de congressistas para o ticker dentro do período.

        Args:
            ticker:    Símbolo na bolsa americana (ex: AAPL, TSM, NVDA)
            days_back: Quantos dias retroativos buscar (default: 30)
        """
        ticker_upper  = ticker.upper()
        cutoff        = datetime.utcnow() - timedelta(days=days_back)
        sector        = _SECTOR_MAP.get(ticker_upper)
        rel_committees = REGULATORY_COMMITTEES.get(sector, []) if sector else []

        headers = dict(_HEADERS)
        if self._api_key:
            headers["Authorization"] = f"Token {self._api_key}"

        try:
            resp     = await self._get(QUIVER_BULK_URL, headers=headers)
            all_txns = resp.json()
            if not isinstance(all_txns, list):
                logger.warning(
                    "PoliticianTrading: Quiver retornou resposta inesperada (status %s). "
                    "Configure QUIVER_API_KEY no .env (gratuito em quiverquant.com).",
                    resp.status_code,
                )
                return
        except Exception as exc:
            logger.warning("PoliticianTrading: falhou ao buscar Quiver bulk: %s", exc)
            return

        for txn in all_txns:
            # ── Filtra por ticker ───────────────────────────────────────
            raw_ticker = str(txn.get("Ticker") or "").strip().upper()
            if raw_ticker != ticker_upper:
                continue

            # ── Filtra por data ─────────────────────────────────────────
            date = self._parse_date(txn.get("Traded") or txn.get("Filed") or "")
            if not date or date < cutoff:
                continue

            # ── Normalização de campos ───────────────────────────────────
            politician = (txn.get("Name") or "N/D").strip()
            party      = txn.get("Party") or ""
            state      = txn.get("State") or ""
            district   = txn.get("District") or ""
            chamber    = txn.get("Chamber") or ""
            bio_id     = txn.get("BioGuideID") or ""
            txn_type   = str(txn.get("Transaction") or "").strip()
            trade_usd  = txn.get("Trade_Size_USD")
            exc_return = txn.get("excess_return")
            filed_date = self._parse_date(txn.get("Filed") or "")

            # Formata o valor
            try:
                amount_str = f"${float(trade_usd):,.0f}" if trade_usd else "N/D"
            except (ValueError, TypeError):
                amount_str = str(trade_usd) if trade_usd else "N/D"

            # Label normalizado do tipo de transação
            type_label = self._type_label(txn_type)

            # Câmara normalizada
            if "rep" in chamber.lower():
                chamber_label = "House (Câmara)"
            elif "sen" in chamber.lower():
                chamber_label = "Senate (Senado)"
            else:
                chamber_label = chamber or "Congress"

            if district and district != "nan":
                try:
                    dist_str = f" D-{int(float(district))}"
                except (ValueError, TypeError):
                    dist_str = f" {district}"
            else:
                dist_str = ""

            party_str = f"({party[:1]}-{state})" if party and state else f"({party})" if party else ""

            title = (
                f"[POLÍTICO][{type_label}] {politician} {party_str}{dist_str} — "
                f"{ticker_upper} | {amount_str} | {chamber_label}"
            ).strip()

            lines = [
                f"Político:         {politician}",
                f"Câmara:           {chamber_label}",
                f"Partido:          {party}",
            ]
            if state:
                lines.append(f"Estado:           {state}")
            if district and district != "nan":
                try:
                    lines.append(f"Distrito:         {int(float(district))}")
                except (ValueError, TypeError):
                    lines.append(f"Distrito:         {district}")
            lines += [
                f"BioGuide ID:      {bio_id}",
                f"Tipo:             {type_label} ({txn_type})",
                f"Ticker:           {ticker_upper}",
                f"Valor estimado:   {amount_str}",
                f"Data da transação:{date.strftime('%d/%m/%Y')}",
            ]
            if filed_date:
                lines.append(f"Data do filing:   {filed_date.strftime('%d/%m/%Y')}")
            if exc_return is not None:
                try:
                    lines.append(f"Excess return:    {float(exc_return):+.2f}% vs mercado")
                except (ValueError, TypeError):
                    pass
            lines.append(f"Fonte:            STOCK Act via Quiver Quantitative")
            if rel_committees:
                lines.append(
                    f"Comitês regulatórios do setor ({sector}): "
                    + ", ".join(rel_committees)
                )

            content = "\n".join(lines)

            # URL única por transação (para deduplicação no banco)
            uid = hashlib.sha256(
                f"{politician}|{date.isoformat()}|{ticker_upper}|{txn_type}|{trade_usd}".encode()
            ).hexdigest()[:20]
            disclosure_url = (
                f"https://disclosures.house.gov#quiver-{uid}"
                if "rep" in chamber.lower()
                else f"https://efts.senate.gov#quiver-{uid}"
            )

            yield RawArticle(
                source="Quiver Quant Congress",
                source_type="politician_trade",
                url=disclosure_url,
                title=title,
                content=content,
                published_at=date,
                company_ticker=ticker_upper,
                company_name=txn.get("Company") or ticker_upper,
                raw_metadata={
                    "chamber":              chamber_label,
                    "politician":           politician,
                    "party":                party,
                    "state":                state,
                    "district":             district,
                    "bio_guide_id":         bio_id,
                    "transaction_type":     txn_type,
                    "transaction_label":    type_label,
                    "trade_size_usd":       trade_usd,
                    "excess_return":        exc_return,
                    "filed_date":           txn.get("Filed"),
                    "sector":               sector,
                    "regulatory_committees": rel_committees,
                },
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _type_label(txn_type: str) -> str:
        t = txn_type.lower()
        if "purchase" in t:
            return "COMPRA"
        if "sale" in t:
            return "VENDA"
        if "exchange" in t:
            return "TROCA"
        if "receive" in t or "gift" in t:
            return "RECEBIMENTO"
        return txn_type.upper() or "TRANSAÇÃO"

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%B %d, %Y"):
            try:
                return datetime.strptime(date_str.strip(), fmt)
            except (ValueError, AttributeError):
                continue
        return None
