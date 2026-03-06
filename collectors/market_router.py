"""
Roteador de mercado: detecta se o ticker pertence à B3 (Brasil) ou NYSE/NASDAQ (EUA)
e despacha para o coletor correto de Fatos Relevantes.

Regras de detecção:
    - Ticker terminado em  número + letra (.SA ou padrão B3) → Brasil
      ex: PETR4, VALE3, ITUB4, BBDC3, WEGE3
    - Ticker com sufixo '.SA' explícito → Brasil
    - Ticker puro de letras (1-5 chars)  → EUA
      ex: AAPL, MSFT, NVDA, VALE (ADR), PBR (ADR)
    - Lista de ADRs brasileiros conhecidos → roteia para EDGAR (6-K)
"""

import re
from typing import AsyncIterator

from .base_collector import RawArticle
from .cvm_collector import CVMCollector
from .sec_edgar_collector import SECEdgarCollector, MATERIAL_FORMS


# ADRs de empresas brasileiras listadas na NYSE/NASDAQ
# Esses tickers usam formulário 6-K no EDGAR (não 8-K)
BRAZILIAN_ADRS: set[str] = {
    "VALE",   # Vale S.A.
    "PBR",    # Petrobras
    "PBRA",   # Petrobras (preferred)
    "ITUB",   # Itaú Unibanco
    "BBD",    # Bradesco
    "BBDO",   # Bradesco (preferred)
    "ABEV",   # Ambev
    "GGB",    # Gerdau
    "SID",    # CSN
    "ERJ",    # Embraer
    "CIG",    # Cemig
    "ELP",    # Copel
    "SBS",    # SABESP
    "UGP",    # Ultrapar
    "BRFS",   # BRF
    "TIMB",   # TIM
    "VIVO",   # Telefônica Brasil
    "CBD",    # Grupo Pão de Açúcar
    "LND",    # Brasilagro
    "SUZ",    # Suzano
    "FBR",    # Fibria (incorporada Suzano)
}

# Padrão B3: 4 letras + 1 dígito (ações ON/PN) ou + F (BDRs)
_B3_PATTERN = re.compile(r"^[A-Z]{4}\d{1,2}[A-Z]?$")


def detect_market(ticker: str) -> str:
    """
    Retorna 'BR' para B3/CVM ou 'US' para NYSE/NASDAQ/EDGAR.
    """
    t = ticker.upper().replace(".SA", "").strip()

    if t.endswith(".SA") or _B3_PATTERN.match(t):
        return "BR"

    return "US"


class MaterialFactsRouter:
    """
    Fachada única para coletar Fatos Relevantes independente do mercado.

    Uso:
        async with MaterialFactsRouter() as router:
            async for article in router.collect("PETR4", days_back=30):
                ...
            async for article in router.collect("AAPL", days_back=30):
                ...
            async for article in router.collect("VALE", days_back=30):
                # ADR brasileiro → roteia para EDGAR com 6-K
                ...
    """

    def __init__(self):
        self._cvm   = CVMCollector(rate_limit_rps=0.5)
        self._edgar = SECEdgarCollector(rate_limit_rps=5.0)

    async def __aenter__(self):
        await self._cvm.__aenter__()
        await self._edgar.__aenter__()
        return self

    async def __aexit__(self, *args):
        await self._cvm.__aexit__(*args)
        await self._edgar.__aexit__(*args)

    async def collect(
        self,
        ticker: str,
        days_back: int = 30,
        **kwargs,
    ) -> AsyncIterator[RawArticle]:
        """
        Detecta o mercado do ticker e delega para o coletor correto.

        Para ADRs brasileiros (ex: VALE, PBR), coleta do EDGAR usando
        formulários 6-K (equivalente ao Fato Relevante da CVM).
        """
        market = detect_market(ticker)

        if market == "BR":
            async for article in self._cvm.collect(ticker, days_back=days_back, **kwargs):
                yield article

        else:
            # ADRs brasileiros: filtra apenas 6-K
            forms = (
                {"6-K", "6-K/A"}
                if ticker.upper() in BRAZILIAN_ADRS
                else MATERIAL_FORMS
            )
            async for article in self._edgar.collect(
                ticker, days_back=days_back, forms=forms, **kwargs
            ):
                yield article

    async def collect_dual_listed(
        self,
        br_ticker: str,
        us_ticker: str,
        days_back: int = 30,
    ) -> AsyncIterator[RawArticle]:
        """
        Para empresas com dupla listagem (ex: VALE3 na B3 + VALE na NYSE),
        coleta de ambas as fontes e marca a origem.

        Uso:
            async for article in router.collect_dual_listed("VALE3", "VALE"):
                print(article.source, article.title)
        """
        # Coleta da CVM
        async for article in self._cvm.collect(br_ticker, days_back=days_back):
            article.raw_metadata["dual_listed"] = True
            article.raw_metadata["counterpart_ticker"] = us_ticker
            yield article

        # Coleta do EDGAR (6-K para emissores estrangeiros)
        async for article in self._edgar.collect(
            us_ticker,
            days_back=days_back,
            forms={"6-K", "6-K/A", "20-F"},
        ):
            article.raw_metadata["dual_listed"] = True
            article.raw_metadata["counterpart_ticker"] = br_ticker
            yield article
