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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
TICKERS_URL       = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL   = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FILING_INDEX_URL  = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/"
EFTS_SEARCH_URL   = "https://efts.sec.gov/LATEST/search-index"

# Cabeçalho obrigatório pela política do EDGAR
EDGAR_HEADERS = {
    "User-Agent": "CorporateIntelMonitor research@example.com",
    "Accept-Encoding": "gzip, deflate",
}

# Formulários que equivalem a "Fatos Relevantes"
MATERIAL_FORMS = {"8-K", "8-K/A", "6-K", "6-K/A", "SC 13D", "SC 13G", "SC 13D/A"}

# Itens do 8-K mais relevantes para análise de mercado
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
    """
    Coleta 8-K e 6-K do SEC EDGAR para empresas listadas nos EUA.

    Para tickers brasileiros com ADR (ex: VALE, PBR), usa automaticamente
    os formulários 20-F / 6-K.

    Fluxo:
        1. Ticker → CIK  (cache local em memória)
        2. CIK → lista de filings recentes (submissions JSON)
        3. Filtra por tipo de formulário e período
        4. Extrai texto do documento principal de cada filing
        5. Emite RawArticle com metadados estruturados do 8-K
    """

    # Cache de ticker → CIK para evitar re-downloads
    _cik_cache: dict[str, int] = {}

    def __init__(self, rate_limit_rps: float = 5.0):
        # EDGAR permite até 10 req/s; usamos 5 para segurança
        super().__init__(rate_limit_rps=rate_limit_rps)

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    async def collect(
        self,
        ticker: str,
        days_back: int = 30,
        forms: set[str] | None = None,
        extract_full_text: bool = True,
    ) -> AsyncIterator[RawArticle]:
        """
        Coleta filings materiais para um ticker americano.

        Args:
            ticker:           Símbolo na bolsa americana (ex: AAPL, VALE, PBR)
            days_back:        Quantos dias retroativos buscar
            forms:            Conjunto de formulários a incluir (default: MATERIAL_FORMS)
            extract_full_text: Se True, baixa e extrai o texto completo do documento
        """
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
                break  # a lista vem em ordem decrescente de data

            content = ""
            if extract_full_text:
                content = await self._extract_document_text(cik, filing["accession"])

            items_desc = self._describe_items(filing.get("items", ""))

            title = self._build_title(
                entity_name, filing["form"], filing["filing_date"], items_desc
            )

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

    # ------------------------------------------------------------------
    # Resolução de Ticker → CIK
    # ------------------------------------------------------------------

    async def _resolve_cik(self, ticker: str) -> int | None:
        """
        Converte ticker para CIK usando o mapa oficial da SEC.
        CIK (Central Index Key) é o identificador único da empresa no EDGAR.
        """
        ticker_upper = ticker.upper()

        if ticker_upper in self._cik_cache:
            return self._cik_cache[ticker_upper]

        resp = await self._get(TICKERS_URL, headers=EDGAR_HEADERS)
        data = resp.json()

        # O JSON é {index: {cik_str, ticker, title}} — index é irrelevante
        for entry in data.values():
            if entry.get("ticker", "").upper() == ticker_upper:
                cik = int(entry["cik_str"])
                self._cik_cache[ticker_upper] = cik
                return cik

        # Fallback: busca via full-text search do EDGAR
        cik = await self._search_cik_fallback(ticker_upper)
        if cik:
            self._cik_cache[ticker_upper] = cik
        return cik

    async def _search_cik_fallback(self, ticker: str) -> int | None:
        """Fallback: busca o CIK via EDGAR full-text search."""
        params = {
            "q": f'"{ticker}"',
            "forms": "10-K,20-F",
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

    # ------------------------------------------------------------------
    # Fetch de submissions
    # ------------------------------------------------------------------

    async def _fetch_submissions(self, cik: int) -> dict | None:
        """
        Baixa o JSON de submissions da empresa.
        Contém nome, SIC, endereço e até 1000 filings recentes.
        """
        url = SUBMISSIONS_URL.format(cik=cik)
        try:
            resp = await self._get(url, headers=EDGAR_HEADERS)
            return resp.json()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Parse da tabela de filings
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_filings_table(recent: dict) -> list[dict]:
        """
        O EDGAR retorna as colunas do array separadas em listas paralelas.
        Esta função transpõe para uma lista de dicts por filing.
        """
        keys = [
            "accessionNumber", "filingDate", "reportDate",
            "form", "primaryDocument", "primaryDocDescription",
            "items", "size",
        ]
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
                "accession":       columns["accessionNumber"][i],
                "filing_date":     filing_date,
                "report_date":     columns["reportDate"][i],
                "form":            columns["form"][i],
                "primary_document": columns["primaryDocument"][i],
                "items":           columns["items"][i] if columns["items"] else "",
                "size":            columns["size"][i],
            })

        return filings  # já vem em ordem decrescente de data

    # ------------------------------------------------------------------
    # Extração do texto do documento
    # ------------------------------------------------------------------

    async def _extract_document_text(self, cik: int, accession: str) -> str:
        """
        Baixa e extrai o texto do documento principal do filing.

        Estratégia:
            1. Busca o índice do filing para achar o arquivo .htm/.txt principal
            2. Faz o download do arquivo
            3. Extrai texto via selectolax (descarta tags HTML)
        """
        acc_nodash = accession.replace("-", "")
        index_url = FILING_INDEX_URL.format(cik=cik, acc_nodash=acc_nodash)

        # Tenta o arquivo de índice JSON (mais confiável)
        try:
            idx_json_url = f"{index_url}{acc_nodash}-index.json"
            resp = await self._get(idx_json_url, headers=EDGAR_HEADERS)
            docs = resp.json().get("documents", [])
            primary = next(
                (d for d in docs if d.get("type") in {"8-K", "6-K", "SC 13D", "SC 13G"}),
                docs[0] if docs else None,
            )
            if primary:
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{primary['filename']}"
                return await self._fetch_and_clean_html(doc_url)
        except Exception:
            pass

        # Fallback: tenta o documento .htm mais provável pelo padrão de nome
        for ext in (".htm", ".html", ".txt"):
            candidate = f"{index_url}{accession}{ext}"
            try:
                return await self._fetch_and_clean_html(candidate)
            except Exception:
                continue

        return ""

    async def _fetch_and_clean_html(self, url: str) -> str:
        """Faz download de HTML/TXT e remove marcação, retornando texto limpo."""
        resp = await self._get(url, headers=EDGAR_HEADERS)
        content_type = resp.headers.get("content-type", "")

        if "html" in content_type or url.endswith((".htm", ".html")):
            tree = HTMLParser(resp.text)
            for tag in tree.css("script, style, ix\\:header, [style*='display:none']"):
                tag.decompose()
            # Prefere a seção do body
            body = tree.css_first("body") or tree.root
            text = body.text(separator="\n", strip=True) if body else ""
        else:
            # Arquivo .txt puro (SGML ou plain text)
            text = resp.text

        # Normaliza espaços em branco excessivos
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)

        return text[:20_000]  # limita para não sobrecarregar o storage

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filing_url(cik: int, accession: str) -> str:
        acc_nodash = accession.replace("-", "")
        return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/"

    @staticmethod
    def _describe_items(items_str: str) -> str:
        """
        Converte 'Item 2.02,Item 5.02' → descrição legível em português.
        O campo 'items' do EDGAR pode vir como '2.02,5.02' ou 'Item 2.02,Item 5.02'.
        """
        if not items_str:
            return ""

        # Normaliza para extrair apenas os números (ex: '2.02')
        codes = re.findall(r"(\d+\.\d+)", items_str)
        descriptions = [
            f"Item {c}: {MATERIAL_8K_ITEMS[c]}"
            for c in codes
            if c in MATERIAL_8K_ITEMS
        ]
        return " | ".join(descriptions) if descriptions else items_str

    @staticmethod
    def _build_title(
        entity_name: str,
        form: str,
        filing_date: datetime,
        items_desc: str,
    ) -> str:
        date_str = filing_date.strftime("%d/%m/%Y")
        if items_desc:
            return f"[{form}] {entity_name} ({date_str}): {items_desc}"
        return f"[{form}] {entity_name} — {date_str}"
