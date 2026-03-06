# Corporate Intelligence Monitor (CIM) — Contexto Completo do Projeto

> Este documento contém tudo que é necessário para continuar o desenvolvimento
> do projeto em uma nova janela de contexto: arquitetura, decisões de design,
> código-fonte completo de todos os arquivos já implementados e próximos passos.

---

## 1. Visão Geral

**Objetivo:** Sistema de raspagem e análise de inteligência corporativa que monitora
uma empresa específica coletando dados de múltiplas fontes e processando com NLP/IA.

**Fontes cobertas:**

| Categoria | Fontes |
|-----------|--------|
| Fatos Relevantes BR | CVM (API oficial) |
| Fatos Relevantes US | SEC EDGAR (8-K, 6-K, SC 13D/G) |
| Notícias Tempo Real | Reuters, CNBC, MarketWatch, Bloomberg, WSJ |
| Análise Fundamentalista | Yahoo Finance, Seeking Alpha, Morningstar, Barchart |
| Gráficos/Screening | TradingView (ideas), Finviz, Briefing.com |
| Notícias BR | InfoMoney, Valor Econômico, Investing.com BR |
| Redes Sociais | X/Twitter, Reddit, LinkedIn, Discord, Telegram, StockTwits |
| Apostas/Previsão | Polymarket, Kalshi, Metaculus, Betfair, Deriv, IQ Option |

---

## 2. Arquitetura

```
corporate_intel_monitor/
├── collectors/
│   ├── base_collector.py       # Classe base abstrata (A CRIAR)
│   ├── cvm_collector.py        # Fatos Relevantes CVM Brasil (A CRIAR)
│   ├── sec_edgar_collector.py  # Fatos Relevantes SEC EDGAR EUA (PRONTO)
│   ├── market_router.py        # Roteador BR/US automático (PRONTO)
│   ├── news_collector.py       # Todos os portais de notícias (PRONTO)
│   ├── social_collector.py     # Todas as redes sociais (PRONTO)
│   └── betting_collector.py    # Todos os mercados de apostas (PRONTO)
├── processors/
│   ├── sentiment.py            # FinBERT sentiment analysis (A CRIAR)
│   ├── event_classifier.py     # Classificador de tipo de evento (A CRIAR)
│   ├── deduplicator.py         # LSH deduplication (A CRIAR)
│   └── normalizer.py           # Normalização e scoring (A CRIAR)
├── storage/
│   └── database.py             # DuckDB schema e CRUD (A CRIAR)
├── api/
│   └── main.py                 # FastAPI endpoints (A CRIAR)
├── scheduler/
│   └── jobs.py                 # APScheduler jobs (A CRIAR)
├── config/
│   └── settings.py             # Configurações pydantic-settings (PRONTO)
├── main.py                     # Entry point (PRONTO)
└── .env.example                # Template de credenciais (PRONTO)
```

### Fluxo de dados

```
Ticker input
    │
    ├─► MaterialFactsRouter ──► CVM (BR) ou SEC EDGAR (US/ADR)
    ├─► NewsCollector       ──► 14 portais de notícias
    ├─► SocialCollectors    ──► 6 redes sociais
    └─► BettingCollectors   ──► 6 plataformas de apostas/previsão
            │
            ▼
    RawArticle (dataclass padronizado)
            │
            ▼
    Processors (sentiment + event_type + dedup)
            │
            ▼
    DuckDB (storage local, SQL analítico)
            │
            ▼
    FastAPI / Claude API briefing
```

---

## 3. Decisões de Design

- **`RawArticle`**: dataclass único que todos os coletores emitem — garante interface uniforme.
- **`BaseCollector`**: classe abstrata com rate limiting, retry automático e context manager `async with`.
- **`MaterialFactsRouter`**: detecta mercado pelo padrão do ticker (B3: `PETR4` → CVM; US: `AAPL` → EDGAR). ADRs brasileiros (`VALE`, `PBR`) → EDGAR 6-K.
- **`build_*_collectors(settings)`**: factory functions que instanciam apenas coletores com credenciais disponíveis no `.env`.
- **`NewsCollector` facade**: agrega todos os sub-coletores de notícias num único `async with collector`.
- **DuckDB**: banco embutido, sem infraestrutura, adequado para análise local.
- **Deduplicação**: SHA256 da URL como ID primário no banco (INSERT OR IGNORE).

---

## 4. Código-fonte Completo

### 4.1 `collectors/base_collector.py` (A CRIAR)

```python
"""Classe base para todos os coletores."""
import asyncio
import httpx
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator
import logging

logger = logging.getLogger(__name__)


@dataclass
class RawArticle:
    source: str
    source_type: str          # 'fato_relevante' | 'news' | 'social' | 'betting'
    url: str
    title: str
    content: str
    published_at: datetime
    company_ticker: str | None = None
    company_name: str | None = None
    raw_metadata: dict = field(default_factory=dict)
    collected_at: datetime = field(default_factory=datetime.utcnow)


class BaseCollector(ABC):
    """Coletor base com rate limiting e retry automático."""

    def __init__(self, rate_limit_rps: float = 1.0):
        self._delay = 1.0 / rate_limit_rps
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": "CorporateIntelMonitor/1.0 (research)"},
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    async def _get(self, url: str, **kwargs) -> httpx.Response:
        await asyncio.sleep(self._delay)
        for attempt in range(3):
            try:
                resp = await self._client.get(url, **kwargs)
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    await asyncio.sleep(2 ** attempt * 5)
                else:
                    raise
        raise RuntimeError(f"Failed after 3 attempts: {url}")

    @abstractmethod
    async def collect(self, ticker: str) -> AsyncIterator[RawArticle]:
        ...
```

---

### 4.2 `collectors/cvm_collector.py` (A CRIAR)

```python
"""Coleta Fatos Relevantes da CVM via API oficial."""
import httpx
from datetime import datetime, timedelta
from typing import AsyncIterator
from .base_collector import BaseCollector, RawArticle
import pdfplumber
import io


CVM_BUSCA_URL = "https://dados.cvm.gov.br/api/consulta/documento/busca/"


class CVMCollector(BaseCollector):
    """
    Coleta Fatos Relevantes e Comunicados da CVM.
    Documentação: https://dados.cvm.gov.br/
    """

    CATEGORIAS = {
        "fato_relevante": "30",
        "comunicado":     "48",
        "aviso_acionistas": "53",
    }

    async def collect(
        self,
        ticker: str,
        days_back: int = 30,
        categorias: list[str] | None = None,
    ) -> AsyncIterator[RawArticle]:

        categorias = categorias or list(self.CATEGORIAS.values())
        data_ini = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

        for cat in categorias:
            params = {
                "categoria": cat,
                "data_ini":  data_ini,
                "ticker":    ticker.upper(),
                "limit":     50,
            }
            resp = await self._get(CVM_BUSCA_URL, params=params)
            docs = resp.json().get("results", [])

            for doc in docs:
                content = await self._extract_pdf_content(doc.get("link_arquivo", ""))

                yield RawArticle(
                    source="CVM",
                    source_type="fato_relevante",
                    url=doc.get("link_arquivo", ""),
                    title=doc.get("assunto", "Sem título"),
                    content=content,
                    published_at=datetime.fromisoformat(doc["data_entrega"]),
                    company_ticker=ticker,
                    company_name=doc.get("nome_empresa"),
                    raw_metadata=doc,
                )

    async def _extract_pdf_content(self, url: str) -> str:
        if not url:
            return ""
        try:
            resp = await self._get(url)
            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                return "\n".join(
                    page.extract_text() or "" for page in pdf.pages
                )
        except Exception:
            return ""
```

---

### 4.3 `collectors/sec_edgar_collector.py` (PRONTO)

```python
"""
Coleta de Fatos Relevantes do mercado americano via SEC EDGAR.

Equivalência de formulários:
    8-K  → Fato Relevante de empresa doméstica (AAPL, MSFT, NVDA...)
    6-K  → Fato Relevante de empresa estrangeira com ADR (VALE, PBR, ITUB...)
    SC 13D/G → Mudança significativa de participação acionária
    Form 4   → Transações de insiders (diretores/officers)

API oficial do EDGAR — sem autenticação, respeitar 10 req/s.
Documentação: https://www.sec.gov/developer
"""

import asyncio
import re
from datetime import datetime, timedelta
from typing import AsyncIterator
from selectolax.parser import HTMLParser

from .base_collector import BaseCollector, RawArticle


TICKERS_URL       = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL   = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FILING_INDEX_URL  = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/"
EFTS_SEARCH_URL   = "https://efts.sec.gov/LATEST/search-index"

EDGAR_HEADERS = {
    "User-Agent": "CorporateIntelMonitor research@example.com",
    "Accept-Encoding": "gzip, deflate",
}

MATERIAL_FORMS = {"8-K", "8-K/A", "6-K", "6-K/A", "SC 13D", "SC 13G", "SC 13D/A"}

MATERIAL_8K_ITEMS = {
    "1.01": "Celebração de Acordo Material",
    "1.02": "Rescisão de Acordo Material",
    "1.03": "Falência ou Recuperação Judicial",
    "2.01": "Aquisição ou Alienação de Ativos",
    "2.02": "Resultados de Operações (Earnings)",
    "2.03": "Obrigação Financeira Relevante",
    "2.04": "Eventos Gatilho de Obrigação",
    "2.05": "Reestruturação / Demissões",
    "2.06": "Impairment Material",
    "3.01": "Aviso de Cancelamento de Listagem",
    "4.01": "Mudança de Auditor",
    "5.01": "Mudança de Controle Acionário",
    "5.02": "Saída/Entrada de Diretores ou Officers",
    "5.03": "Alteração Estatutária",
    "7.01": "Divulgação Regulation FD",
    "8.01": "Outros Eventos Relevantes",
}


class SECEdgarCollector(BaseCollector):
    _cik_cache: dict[str, int] = {}

    def __init__(self, rate_limit_rps: float = 5.0):
        super().__init__(rate_limit_rps=rate_limit_rps)

    async def collect(
        self,
        ticker: str,
        days_back: int = 30,
        forms: set[str] | None = None,
        extract_full_text: bool = True,
    ) -> AsyncIterator[RawArticle]:
        forms = forms or MATERIAL_FORMS
        cutoff = datetime.utcnow() - timedelta(days=days_back)

        cik = await self._resolve_cik(ticker)
        if cik is None:
            return

        submissions = await self._fetch_submissions(cik)
        if not submissions:
            return

        recent = submissions.get("filings", {}).get("recent", {})
        entity_name = submissions.get("name", ticker)
        filings = self._parse_filings_table(recent)

        for filing in filings:
            if filing["form"] not in forms:
                continue
            if filing["filing_date"] < cutoff:
                break

            content = ""
            if extract_full_text:
                content = await self._extract_document_text(cik, filing["accession"])

            items_desc = self._describe_items(filing.get("items", ""))
            title = self._build_title(entity_name, filing["form"], filing["filing_date"], items_desc)

            yield RawArticle(
                source="SEC EDGAR",
                source_type="fato_relevante",
                url=self._filing_url(cik, filing["accession"]),
                title=title,
                content=content or items_desc,
                published_at=filing["filing_date"],
                company_ticker=ticker.upper(),
                company_name=entity_name,
                raw_metadata={
                    "cik": cik,
                    "accession": filing["accession"],
                    "form": filing["form"],
                    "items": filing.get("items", ""),
                    "items_description": items_desc,
                    "primary_document": filing.get("primary_document", ""),
                    "report_date": filing.get("report_date"),
                    "size": filing.get("size"),
                },
            )

    async def _resolve_cik(self, ticker: str) -> int | None:
        ticker_upper = ticker.upper()
        if ticker_upper in self._cik_cache:
            return self._cik_cache[ticker_upper]
        resp = await self._get(TICKERS_URL, headers=EDGAR_HEADERS)
        data = resp.json()
        for entry in data.values():
            if entry.get("ticker", "").upper() == ticker_upper:
                cik = int(entry["cik_str"])
                self._cik_cache[ticker_upper] = cik
                return cik
        return await self._search_cik_fallback(ticker_upper)

    async def _search_cik_fallback(self, ticker: str) -> int | None:
        params = {
            "q": f'"{ticker}"', "forms": "10-K,20-F",
            "dateRange": "custom",
            "startdt": (datetime.utcnow() - timedelta(days=730)).strftime("%Y-%m-%d"),
            "enddt": datetime.utcnow().strftime("%Y-%m-%d"),
        }
        try:
            resp = await self._get(EFTS_SEARCH_URL, params=params, headers=EDGAR_HEADERS)
            hits = resp.json().get("hits", {}).get("hits", [])
            if hits:
                cik_str = hits[0].get("_source", {}).get("entity_id", "")
                return int(cik_str.lstrip("0")) if cik_str else None
        except Exception:
            pass
        return None

    async def _fetch_submissions(self, cik: int) -> dict | None:
        url = SUBMISSIONS_URL.format(cik=cik)
        try:
            resp = await self._get(url, headers=EDGAR_HEADERS)
            return resp.json()
        except Exception:
            return None

    @staticmethod
    def _parse_filings_table(recent: dict) -> list[dict]:
        keys = ["accessionNumber","filingDate","reportDate","form",
                "primaryDocument","primaryDocDescription","items","size"]
        columns = {k: recent.get(k, []) for k in keys}
        count = len(columns["accessionNumber"])
        filings = []
        for i in range(count):
            date_str = columns["filingDate"][i] or ""
            try:
                filing_date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue
            filings.append({
                "accession": columns["accessionNumber"][i],
                "filing_date": filing_date,
                "report_date": columns["reportDate"][i],
                "form": columns["form"][i],
                "primary_document": columns["primaryDocument"][i],
                "items": columns["items"][i] if columns["items"] else "",
                "size": columns["size"][i],
            })
        return filings

    async def _extract_document_text(self, cik: int, accession: str) -> str:
        acc_nodash = accession.replace("-", "")
        index_url = FILING_INDEX_URL.format(cik=cik, acc_nodash=acc_nodash)
        try:
            idx_json_url = f"{index_url}{acc_nodash}-index.json"
            resp = await self._get(idx_json_url, headers=EDGAR_HEADERS)
            docs = resp.json().get("documents", [])
            primary = next(
                (d for d in docs if d.get("type") in {"8-K","6-K","SC 13D","SC 13G"}),
                docs[0] if docs else None,
            )
            if primary:
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{primary['filename']}"
                return await self._fetch_and_clean_html(doc_url)
        except Exception:
            pass
        for ext in (".htm", ".html", ".txt"):
            candidate = f"{index_url}{accession}{ext}"
            try:
                return await self._fetch_and_clean_html(candidate)
            except Exception:
                continue
        return ""

    async def _fetch_and_clean_html(self, url: str) -> str:
        resp = await self._get(url, headers=EDGAR_HEADERS)
        content_type = resp.headers.get("content-type", "")
        if "html" in content_type or url.endswith((".htm", ".html")):
            tree = HTMLParser(resp.text)
            for tag in tree.css("script, style, ix\\:header, [style*='display:none']"):
                tag.decompose()
            body = tree.css_first("body") or tree.root
            text = body.text(separator="\n", strip=True) if body else ""
        else:
            text = resp.text
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        return text[:20_000]

    @staticmethod
    def _filing_url(cik: int, accession: str) -> str:
        acc_nodash = accession.replace("-", "")
        return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/"

    @staticmethod
    def _describe_items(items_str: str) -> str:
        if not items_str:
            return ""
        codes = re.findall(r"(\d+\.\d+)", items_str)
        descriptions = [f"Item {c}: {MATERIAL_8K_ITEMS[c]}" for c in codes if c in MATERIAL_8K_ITEMS]
        return " | ".join(descriptions) if descriptions else items_str

    @staticmethod
    def _build_title(entity_name: str, form: str, filing_date: datetime, items_desc: str) -> str:
        date_str = filing_date.strftime("%d/%m/%Y")
        if items_desc:
            return f"[{form}] {entity_name} ({date_str}): {items_desc}"
        return f"[{form}] {entity_name} — {date_str}"
```

---

### 4.4 `collectors/market_router.py` (PRONTO)

```python
"""
Roteador de mercado: detecta B3 (Brasil) ou NYSE/NASDAQ (EUA)
e despacha para o coletor correto de Fatos Relevantes.
"""

import re
from typing import AsyncIterator

from .base_collector import RawArticle
from .cvm_collector import CVMCollector
from .sec_edgar_collector import SECEdgarCollector, MATERIAL_FORMS


BRAZILIAN_ADRS: set[str] = {
    "VALE", "PBR", "PBRA", "ITUB", "BBD", "BBDO", "ABEV", "GGB",
    "SID", "ERJ", "CIG", "ELP", "SBS", "UGP", "BRFS", "TIMB",
    "VIVO", "CBD", "LND", "SUZ", "FBR",
}

_B3_PATTERN = re.compile(r"^[A-Z]{4}\d{1,2}[A-Z]?$")


def detect_market(ticker: str) -> str:
    t = ticker.upper().replace(".SA", "").strip()
    if t.endswith(".SA") or _B3_PATTERN.match(t):
        return "BR"
    return "US"


class MaterialFactsRouter:
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

    async def collect(self, ticker: str, days_back: int = 30, **kwargs) -> AsyncIterator[RawArticle]:
        market = detect_market(ticker)
        if market == "BR":
            async for article in self._cvm.collect(ticker, days_back=days_back, **kwargs):
                yield article
        else:
            forms = {"6-K", "6-K/A"} if ticker.upper() in BRAZILIAN_ADRS else MATERIAL_FORMS
            async for article in self._edgar.collect(ticker, days_back=days_back, forms=forms, **kwargs):
                yield article

    async def collect_dual_listed(self, br_ticker: str, us_ticker: str, days_back: int = 30) -> AsyncIterator[RawArticle]:
        async for article in self._cvm.collect(br_ticker, days_back=days_back):
            article.raw_metadata["dual_listed"] = True
            article.raw_metadata["counterpart_ticker"] = us_ticker
            yield article
        async for article in self._edgar.collect(us_ticker, days_back=days_back, forms={"6-K","6-K/A","20-F"}):
            article.raw_metadata["dual_listed"] = True
            article.raw_metadata["counterpart_ticker"] = br_ticker
            yield article
```

---

### 4.5 `collectors/news_collector.py` (PRONTO — arquivo completo em disco)

> Arquivo extenso (1004 linhas). Já existe em disco em
> `collectors/news_collector.py`. Classes implementadas:
>
> - `RSSCollector` (base genérica)
> - `ReutersCollector`, `MarketWatchCollector`, `CNBCCollector`
> - `BloombergCollector` (RSS + Playwright opcional)
> - `WSJCollector` (RSS + scraping público)
> - `YahooFinanceCollector` (API JSON pública)
> - `SeekingAlphaCollector` (API não-oficial)
> - `MorningstarCollector`, `BarchartCollector`
> - `FinvizCollector`, `TradingViewCollector`, `BriefingCollector`
> - `InfoMoneyCollector`, `ValorEconomicoCollector`, `InvestingBRCollector`
> - `NewsCollector` (facade aggregadora)
> - `build_news_collectors(include_br, include_us, playwright_sources)`

---

### 4.6 `collectors/social_collector.py` (PRONTO — arquivo completo em disco)

> Já existe em disco. Classes implementadas:
>
> - `TwitterCollector` — API v2 com Bearer Token
> - `StockTwitsCollector` — API pública sem auth
> - `RedditCollector` — PRAW OAuth2 (subreddits BR e US)
> - `LinkedInCollector` — Playwright com cookies de sessão
> - `DiscordCollector` — API REST v10 com Bot Token
> - `TelegramCollector` — Telethon (canais públicos)
> - `build_social_collectors(settings)` — factory

---

### 4.7 `collectors/betting_collector.py` (PRONTO — arquivo completo em disco)

> Já existe em disco. Classes implementadas:
>
> - `PolymarketCollector` — API pública, sem auth
> - `KalshiCollector` — API pública, auth opcional
> - `MetaculusCollector` — API pública, sem auth
> - `BetfairCollector` — API REST, requer app key
> - `DerivCollector` — WebSocket oficial, app_id público
> - `IQOptionCollector` — API não-oficial, requer conta
> - `build_betting_collectors(settings)` — factory

---

### 4.8 `processors/sentiment.py` (A CRIAR)

```python
"""Análise de sentimento usando FinBERT."""
from transformers import pipeline
from dataclasses import dataclass
import torch


@dataclass
class SentimentResult:
    label: str           # 'POSITIVE' | 'NEGATIVE' | 'NEUTRAL'
    score: float
    compound: float      # -1.0 a +1.0


class SentimentAnalyzer:
    def __init__(self, model_name: str = "lucas-leme/FinBERT-PT-BR"):
        device = 0 if torch.cuda.is_available() else -1
        self._pipe = pipeline(
            "text-classification",
            model=model_name,
            device=device,
            truncation=True,
            max_length=512,
        )
        self._label_map = {"POSITIVE": 1.0, "NEUTRAL": 0.0, "NEGATIVE": -1.0}

    def analyze(self, text: str) -> SentimentResult:
        result = self._pipe(text[:2000])[0]
        label = result["label"].upper()
        score = result["score"]
        return SentimentResult(
            label=label,
            score=score,
            compound=self._label_map.get(label, 0.0) * score,
        )
```

---

### 4.9 `processors/event_classifier.py` (A CRIAR)

```python
"""Classificador de tipo de evento corporativo por regex."""
import re
from enum import Enum


class EventType(str, Enum):
    RESULTADO_FINANCEIRO = "resultado_financeiro"
    FUSAO_AQUISICAO      = "fusao_aquisicao"
    DIVIDENDOS           = "dividendos"
    MUDANCA_GESTAO       = "mudanca_gestao"
    INVESTIGACAO_LEGAL   = "investigacao_legal"
    EMISSAO_ACOES        = "emissao_acoes"
    PARCERIA             = "parceria"
    PRODUTO_LANCAMENTO   = "produto_lancamento"
    MACRO_ECONOMICO      = "macro_economico"
    OUTRO                = "outro"


_PATTERNS: dict[EventType, list[str]] = {
    EventType.RESULTADO_FINANCEIRO: [r"\b(resultado|lucro|receita|ebitda|balanço|trimest)\b"],
    EventType.FUSAO_AQUISICAO:      [r"\b(aquisição|fusão|incorporação|merger|takeover|opa)\b"],
    EventType.DIVIDENDOS:           [r"\b(dividendo|jcp|juros capital próprio|provento)\b"],
    EventType.MUDANCA_GESTAO:       [r"\b(ceo|diretor|presidente|renúncia|nomeação|board)\b"],
    EventType.INVESTIGACAO_LEGAL:   [r"\b(investigação|processo|cvm|sec|multa|fraude)\b"],
    EventType.EMISSAO_ACOES:        [r"\b(emissão|follow.on|ipo|oferta|debênture)\b"],
}


def classify_event(title: str, content: str) -> EventType:
    text = (title + " " + content[:500]).lower()
    scores = {et: 0 for et in EventType}
    for event_type, patterns in _PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                scores[event_type] += 1
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else EventType.OUTRO
```

---

### 4.10 `storage/database.py` (A CRIAR)

```python
"""DuckDB schema e operações CRUD."""
import duckdb
from pathlib import Path
from datetime import datetime


DB_PATH = Path("data/corporate_intel.duckdb")

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id              VARCHAR PRIMARY KEY,
    source          VARCHAR NOT NULL,
    source_type     VARCHAR NOT NULL,
    url             VARCHAR UNIQUE,
    title           TEXT,
    content         TEXT,
    published_at    TIMESTAMP,
    collected_at    TIMESTAMP DEFAULT now(),
    company_ticker  VARCHAR,
    company_name    VARCHAR,
    sentiment_label VARCHAR,
    sentiment_score DOUBLE,
    sentiment_compound DOUBLE,
    event_type      VARCHAR,
    raw_metadata    JSON
);

CREATE INDEX IF NOT EXISTS idx_ticker_date
    ON articles (company_ticker, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_source_type
    ON articles (source_type, published_at DESC);
"""


class Database:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(path))
        self._conn.execute(SCHEMA)

    def upsert(self, article_dict: dict) -> bool:
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO articles VALUES ($id, $source, $source_type, "
                "$url, $title, $content, $published_at, $collected_at, "
                "$company_ticker, $company_name, $sentiment_label, $sentiment_score, "
                "$sentiment_compound, $event_type, $raw_metadata)",
                article_dict,
            )
            return True
        except duckdb.ConstraintException:
            return False

    def query_by_ticker(self, ticker: str, days: int = 7, source_types: list[str] | None = None) -> list[dict]:
        filters = ["company_ticker = ?", "published_at >= now() - INTERVAL ? DAY"]
        params = [ticker.upper(), days]
        if source_types:
            placeholders = ", ".join("?" * len(source_types))
            filters.append(f"source_type IN ({placeholders})")
            params.extend(source_types)
        sql = f"SELECT * FROM articles WHERE {' AND '.join(filters)} ORDER BY published_at DESC"
        return self._conn.execute(sql, params).fetchdf().to_dict("records")
```

---

### 4.11 `config/settings.py` (PRONTO)

```python
"""Configurações centrais via pydantic-settings."""
from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        case_sensitive=False, extra="ignore",
    )

    target_tickers: list[str] = Field(default=["PETR4", "VALE3", "AAPL"])

    # Redes Sociais
    twitter_bearer_token:  str | None = None
    reddit_client_id:      str | None = None
    reddit_client_secret:  str | None = None
    reddit_user_agent:     str = "CorporateIntelMonitor/1.0"
    discord_bot_token:     str | None = None
    discord_channels:      list[int] = Field(default=[])
    telegram_api_id:       int | None = None
    telegram_api_hash:     str | None = None
    telegram_phone:        str | None = None
    telegram_channels:     list[str] | None = None
    linkedin_cookies_path: str | None = None

    # Apostas
    kalshi_email:      str | None = None
    kalshi_password:   str | None = None
    betfair_username:  str | None = None
    betfair_password:  str | None = None
    betfair_app_key:   str | None = None
    deriv_app_id:      str = "1089"
    deriv_token:       str | None = None
    iq_option_email:   str | None = None
    iq_option_password: str | None = None

    # IA
    anthropic_api_key: str | None = None

    # Coleta
    days_back: int = 30
    dual_listed_map: dict[str, str] = Field(default_factory=dict)
```

---

### 4.12 `main.py` (PRONTO)

```python
"""Entry point do Corporate Intelligence Monitor."""
import asyncio
import hashlib
import json
import sys
from datetime import datetime

from collectors.market_router    import MaterialFactsRouter, detect_market
from collectors.news_collector   import NewsCollector
from collectors.social_collector import build_social_collectors
from collectors.betting_collector import build_betting_collectors
from processors.sentiment        import SentimentAnalyzer
from processors.event_classifier import classify_event
from storage.database            import Database
from config.settings             import Settings


async def run_collection(ticker: str, settings: Settings, days_back: int = 30):
    db        = Database()
    sentiment = SentimentAnalyzer()

    # Fatos Relevantes (BR via CVM ou US via SEC EDGAR)
    async with MaterialFactsRouter() as router:
        async for article in router.collect(ticker, days_back=days_back):
            _save(article, db, sentiment)

    # Notícias (14 portais)
    async with NewsCollector(rate_limit_rps=1.0) as collector:
        async for article in collector.collect(ticker):
            _save(article, db, sentiment)

    # Redes Sociais (X, Reddit, LinkedIn, Discord, Telegram, StockTwits)
    for collector in build_social_collectors(settings):
        if hasattr(collector, "__aenter__"):
            async with collector:
                async for article in collector.collect(ticker):
                    _save(article, db, sentiment)
        else:
            async for article in collector.collect(ticker):
                _save(article, db, sentiment)

    # Mercados de Apostas/Previsão (Polymarket, Kalshi, Metaculus, Betfair, Deriv, IQ Option)
    for collector in build_betting_collectors(settings):
        if hasattr(collector, "__aenter__"):
            async with collector:
                async for article in collector.collect(ticker):
                    _save(article, db, sentiment)
        else:
            async for article in collector.collect(ticker):
                _save(article, db, sentiment)


async def run_dual_listed(br_ticker: str, us_ticker: str, settings: Settings, days_back: int = 30):
    db        = Database()
    sentiment = SentimentAnalyzer()
    async with MaterialFactsRouter() as router:
        async for article in router.collect_dual_listed(br_ticker, us_ticker, days_back):
            _save(article, db, sentiment)


def _save(article, db: Database, sentiment: SentimentAnalyzer):
    s     = sentiment.analyze(article.title + " " + article.content[:500])
    event = classify_event(article.title, article.content)
    record = {
        "id":                 hashlib.sha256(article.url.encode()).hexdigest()[:16],
        "source":             article.source,
        "source_type":        article.source_type,
        "url":                article.url,
        "title":              article.title,
        "content":            article.content[:5000],
        "published_at":       article.published_at,
        "collected_at":       article.collected_at,
        "company_ticker":     article.company_ticker,
        "company_name":       article.company_name,
        "sentiment_label":    s.label,
        "sentiment_score":    s.score,
        "sentiment_compound": s.compound,
        "event_type":         event.value,
        "raw_metadata":       json.dumps(article.raw_metadata),
    }
    inserted = db.upsert(record)
    if inserted:
        market = detect_market(article.company_ticker or "")
        print(f"[{market}][{article.source_type}][{article.source}] {article.title[:80]}")


if __name__ == "__main__":
    settings = Settings()
    if len(sys.argv) == 3:
        asyncio.run(run_dual_listed(sys.argv[1], sys.argv[2], settings))
    else:
        ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
        asyncio.run(run_collection(ticker, settings))
```

---

### 4.13 `.env.example` (PRONTO)

```env
# Tickers a monitorar
TARGET_TICKERS=PETR4,VALE3,AAPL,NVDA
DAYS_BACK=30
DUAL_LISTED_MAP={"VALE3":"VALE","PETR4":"PBR","ITUB4":"ITUB","BBDC4":"BBD"}

# Twitter/X — https://developer.twitter.com
TWITTER_BEARER_TOKEN=

# Reddit — https://www.reddit.com/prefs/apps (tipo: script)
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=CorporateIntelMonitor/1.0

# Discord — https://discord.com/developers/applications
DISCORD_BOT_TOKEN=
DISCORD_CHANNELS=123456789012345678,987654321098765432

# Telegram — https://my.telegram.org/apps
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_PHONE=+5511999990000
TELEGRAM_CHANNELS=investidoresbr,bolsanoticias,valoreconomico

# LinkedIn (cookies após login manual)
LINKEDIN_COOKIES_PATH=linkedin_cookies.json

# Kalshi — https://kalshi.com
KALSHI_EMAIL=
KALSHI_PASSWORD=

# Betfair — https://developer.betfair.com
BETFAIR_USERNAME=
BETFAIR_PASSWORD=
BETFAIR_APP_KEY=

# Deriv — https://app.deriv.com/account/api-token
DERIV_APP_ID=1089
DERIV_TOKEN=

# IQ Option (prefira Deriv como alternativa oficial)
IQ_OPTION_EMAIL=
IQ_OPTION_PASSWORD=

# Claude API — https://console.anthropic.com
ANTHROPIC_API_KEY=
```

---

## 5. Dependências (`requirements.txt` a criar)

```txt
# HTTP & Scraping
httpx>=0.27
playwright>=1.44
selectolax>=0.3
feedparser>=6.0
pdfplumber>=0.11
websockets>=12.0

# NLP & ML
transformers>=4.41
torch>=2.3
spacy>=3.7

# Redes Sociais
praw>=7.7          # Reddit
telethon>=1.36     # Telegram
discord.py>=2.3    # Discord

# Apostas
betfairlightweight>=3.18  # Betfair
iqoptionapi>=1.0.0         # IQ Option (opcional)

# Storage
duckdb>=0.10

# Config & API
pydantic-settings>=2.2
python-dotenv>=1.0
fastapi>=0.111
uvicorn>=0.30

# Scheduler
apscheduler>=3.10

# Deduplicação
datasketch>=1.6

# Claude API
anthropic>=0.28
```

---

## 6. Setup Inicial

```bash
# 1. Criar ambiente virtual
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Linux/Mac

# 2. Instalar dependências essenciais (MVP)
pip install httpx selectolax feedparser pdfplumber duckdb transformers pydantic-settings

# 3. Instalar Playwright
pip install playwright
playwright install chromium

# 4. Configurar credenciais
cp .env.example .env
# editar .env com suas credenciais

# 5. Exportar cookies do LinkedIn (opcional)
python -c "from collectors.social_collector import LinkedInCollector; LinkedInCollector.export_session_helper()"

# 6. Rodar coleta
python main.py AAPL          # empresa americana
python main.py PETR4         # empresa brasileira
python main.py VALE3 VALE    # dupla listagem
```

---

## 7. Arquivos Ainda a Criar

| Arquivo | Prioridade | Descrição |
|---------|-----------|-----------|
| `collectors/base_collector.py` | CRÍTICA | Sem isso nada funciona |
| `collectors/cvm_collector.py` | CRÍTICA | Fatos Relevantes BR |
| `processors/sentiment.py` | ALTA | FinBERT sentiment |
| `processors/event_classifier.py` | ALTA | Classificador de eventos |
| `storage/database.py` | ALTA | DuckDB storage |
| `collectors/__init__.py` | MÉDIA | Package init |
| `processors/__init__.py` | MÉDIA | Package init |
| `storage/__init__.py` | MÉDIA | Package init |
| `config/__init__.py` | MÉDIA | Package init |
| `processors/deduplicator.py` | MÉDIA | LSH dedup avançado |
| `api/main.py` | BAIXA | FastAPI endpoints |
| `scheduler/jobs.py` | BAIXA | APScheduler coleta automática |

---

## 8. Próximos Passos Sugeridos

1. **Criar os arquivos faltantes** na ordem da tabela acima
2. **Testar o pipeline básico**:
   ```bash
   python main.py AAPL
   # Deve criar data/corporate_intel.duckdb e imprimir artigos coletados
   ```
3. **Validar cada coletor individualmente** com um ticker conhecido
4. **Implementar o briefing com Claude API** em `processors/briefing.py`
5. **Adicionar APScheduler** para coleta automática a cada 4 horas
6. **Implementar FastAPI** para expor os dados via REST

---

## 9. Exemplo de Uso com Claude API (Síntese)

```python
import anthropic
from storage.database import Database

def synthesize_daily_briefing(ticker: str) -> str:
    db = Database()
    articles = db.query_by_ticker(ticker, days=1)

    content = "\n\n".join(
        f"[{a['source_type'].upper()} | {a['source']}]\n{a['title']}\n{a['content'][:300]}"
        for a in articles[:20]
    )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": (
                f"Você é um analista de mercado sênior. "
                f"Com base nas informações coletadas sobre {ticker} nas últimas 24h, "
                f"produza um briefing executivo com: "
                f"(1) principais eventos, (2) sentimento geral do mercado, "
                f"(3) pontos de atenção críticos.\n\n{content}"
            )
        }]
    )
    return response.content[0].text
```

---

## 10. Mapeamento Completo de Fontes

### Probabilidade implícita nos mercados de apostas

```
Polymarket  →  outcomePrices: ["0.72", "0.28"]  = 72% SIM / 28% NÃO
Kalshi      →  yes_bid=68, yes_ask=70 centavos  = ~69% prob. YES
Betfair     →  back_odds=1.45  → 1/1.45 = 68.9% prob. implícita
Deriv       →  stake $100 → payout $148  → $100/$148 = 67.6% prob. CALL
IQ Option   →  8/10 candles bullish = 80% win rate CALL (proxy)
```

### ADRs brasileiros (EDGAR 6-K, não 8-K)

```python
BRAZILIAN_ADRS = {
    "VALE", "PBR", "PBRA", "ITUB", "BBD", "BBDO", "ABEV", "GGB",
    "SID", "ERJ", "CIG", "ELP", "SBS", "UGP", "BRFS", "TIMB",
    "VIVO", "CBD", "LND", "SUZ", "FBR"
}
```

### Itens 8-K mais relevantes

| Item | Evento |
|------|--------|
| 2.02 | Resultados de Operações (Earnings) |
| 2.01 | Aquisição ou Alienação de Ativos |
| 5.02 | Saída/Entrada de Diretores ou Officers |
| 5.01 | Mudança de Controle Acionário |
| 1.01 | Celebração de Acordo Material |
| 7.01 | Divulgação Regulation FD |

---

## 11. Otimizações de Performance (2026-03-05)

### Problema
Pipeline de notícias muito lento por três razões:
1. `fetch_full_content=True` — cada artigo RSS fazia GET adicional na página completa
2. Execução sequencial de 15 coletores, cada um com delay de rate-limit de 1s
3. Sem limite de artigos — coletava tudo antes de retornar

### Solução aplicada em `collectors/news_collector.py`

| Mudança | Arquivo | Detalhe |
|---------|---------|---------|
| `fetch_full_content=False` | `RSSCollector.__init__` | Usa summary do RSS, elimina GETs extras |
| `count=5` | `YahooFinanceCollector.collect()` | Limite por fonte (era 30) |
| `count=5` | `SeekingAlphaCollector.collect()` | Limite por fonte (era 20) |
| Execução concorrente + early-exit | `NewsCollector.collect()` | `asyncio.Queue` + `create_task`: todos os coletores correm em paralelo, para ao atingir `max_articles=5` |

### Comportamento após a mudança
- Todos os 15 coletores disparam simultaneamente via `asyncio.create_task()`
- Um `asyncio.Queue` centralizado recebe artigos de qualquer coletor
- Ao coletar 5 artigos, as tasks restantes são canceladas
- Tempo esperado: ~2-5s (vs minutos antes)

*Documento gerado em 2026-03-05. Projeto em desenvolvimento ativo.*
