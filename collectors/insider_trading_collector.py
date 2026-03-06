"""
Coleta transações de insiders via SEC EDGAR Form 4.

Form 4 é obrigatório para:
  - Officers (CEO, CFO, COO, VP, Controller, Treasurer, Secretary...)
  - Directors (membros do Conselho de Administração)
  - Acionistas com > 10% das ações (major shareholders)

Deve ser arquivado em até 2 dias úteis após a transação.

Códigos de transação:
  P = Purchase       — compra no mercado aberto   ★ Alta relevância
  S = Sale           — venda no mercado aberto     ★ Alta relevância
  A = Award/Grant    — concessão de ações/opções
  D = Return         — devolução ao emissor
  F = Tax Withhold   — retenção para pagamento de imposto (exercício de opção)
  G = Gift           — doação
  X = Exercise       — exercício de derivativo (valor geralmente conhecido)
  M = Exercise(OTM)  — exercício de opção fora do dinheiro
  C = Conversion     — conversão de instrumento
  E = Expiration     — expiração de derivativo
  W = Inheritance    — aquisição por herança
"""
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import AsyncIterator

from .base_collector import BaseCollector, RawArticle
from .sec_edgar_collector import (
    EDGAR_HEADERS,
    SUBMISSIONS_URL,
    TICKERS_URL,
)

logger = logging.getLogger(__name__)

# Transações que indicam compra/venda real no mercado aberto
OPEN_MARKET_CODES: set[str] = {"P", "S"}

# Todos os códigos considerados relevantes para monitoramento de insiders
RELEVANT_CODES: set[str] = {"P", "S", "A", "X", "M", "F", "G", "W"}

# Relevance score por código de transação (1–3)
_RELEVANCE_SCORE: dict[str, int] = {
    "P": 3,  # compra mercado aberto — alta relevância
    "S": 3,  # venda mercado aberto  — alta relevância
    "A": 2,  # concessão/award       — média relevância
    "D": 1, "F": 1, "G": 1, "X": 1, "M": 1, "C": 1, "E": 1, "W": 1,
}


def _calc_relevance(code: str, total_value: float | None) -> int:
    """Calcula relevance_score (1–3). +1 bônus se valor > $1M."""
    score = _RELEVANCE_SCORE.get(code, 1)
    if total_value and total_value > 1_000_000:
        score = min(score + 1, 3)
    return score

_TRANSACTION_LABELS: dict[str, str] = {
    "P": "COMPRA",
    "S": "VENDA",
    "A": "CONCESSÃO",
    "D": "DEVOLUÇÃO",
    "F": "RETENÇÃO FISCAL",
    "G": "DOAÇÃO",
    "X": "EXERC. DERIVATIVO",
    "M": "EXERC. OPÇÃO",
    "C": "CONVERSÃO",
    "E": "EXPIRAÇÃO",
    "W": "HERANÇA",
    "J": "OUTRA",
    "Z": "CONFIANÇA",
}


class InsiderTradingCollector(BaseCollector):
    """
    Coleta e interpreta Form 4 do SEC EDGAR para um ticker específico.

    Para cada transação no Form 4, emite um RawArticle com:
      - Título: "[COMPRA/VENDA] Nome (Cargo) — N ações @ $X = $Total | TICKER"
      - Metadados completos: nome, cargo, código, shares, preço, saldo pós-transação
    """

    # Cache compartilhado ticker → CIK
    _cik_cache: dict[str, int] = {}

    def __init__(self, rate_limit_rps: float = 5.0):
        super().__init__(rate_limit_rps=rate_limit_rps)

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    async def collect(
        self,
        ticker: str,
        days_back: int = 30,
        open_market_only: bool = False,
    ) -> AsyncIterator[RawArticle]:
        """
        Coleta Form 4 para o ticker, emitindo um RawArticle por transação.

        Args:
            ticker:           Símbolo na bolsa americana (ex: AAPL, TSM, NVDA)
            days_back:        Quantos dias retroativos buscar
            open_market_only: Se True, retorna apenas P (compra) e S (venda) abertas
        """
        codes_filter = OPEN_MARKET_CODES if open_market_only else RELEVANT_CODES
        cutoff       = datetime.utcnow() - timedelta(days=days_back)
        ticker_upper = ticker.upper()

        cik = await self._resolve_cik(ticker_upper)
        if cik is None:
            logger.warning("InsiderTrading: CIK não encontrado para %s", ticker_upper)
            return

        submissions = await self._fetch_submissions(cik)
        if not submissions:
            return

        entity_name = submissions.get("name", ticker_upper)
        recent      = submissions.get("filings", {}).get("recent", {})
        filings     = self._filter_form4_filings(recent, cutoff)

        for filing in filings:
            try:
                xml_url = await self._find_xml_url(
                    cik, filing["accession"], filing.get("primary_document", "")
                )
                if not xml_url:
                    continue

                resp         = await self._get(xml_url, headers=EDGAR_HEADERS)
                transactions = self._parse_form4_xml(resp.text, filing["filing_date"])

                for idx, txn in enumerate(transactions):
                    if txn["code"] not in codes_filter:
                        continue

                    label = _TRANSACTION_LABELS.get(txn["code"], txn["code"])
                    price = txn["price"]
                    shares = txn["shares"]

                    price_str = f"@ ${price:,.2f}" if price else ""
                    total_str = f"= ${shares * price:,.0f}" if price else ""

                    title = (
                        f"[INSIDER][{label}] {txn['owner_name']} ({txn['title']}) — "
                        f"{shares:,.0f} ações {txn['security']} {price_str} {total_str} | {ticker_upper}"
                    ).strip()

                    lines = [
                        f"Insider:           {txn['owner_name']}",
                        f"Cargo:             {txn['title']}",
                        f"Empresa:           {entity_name} ({ticker_upper})",
                        f"Transação:         {label} (código {txn['code']})",
                        f"Ativo:             {txn['security']}",
                        f"Quantidade:        {shares:,.0f} ações",
                    ]
                    if price:
                        lines.append(f"Preço unitário:    ${price:,.4f}")
                        lines.append(f"Valor total:       ${shares * price:,.0f}")
                    if txn["shares_after"] is not None:
                        lines.append(f"Saldo pós-transação: {txn['shares_after']:,.0f} ações")
                    lines.append(f"Data:              {txn['date'].strftime('%d/%m/%Y')}")
                    lines.append(f"Formulário SEC:    {filing['form']}")
                    lines.append(f"Filing:            {self._filing_url(cik, filing['accession'])}")
                    content = "\n".join(lines)

                    # URL única por transação (accession + índice)
                    unique_url = f"{xml_url}#txn{idx}_{txn['code']}_{txn['date'].strftime('%Y%m%d')}"

                    total_value = shares * price if price else None
                    yield RawArticle(
                        source="SEC EDGAR Form 4",
                        source_type="insider_trade",
                        url=unique_url,
                        title=title,
                        content=content,
                        published_at=txn["date"],
                        company_ticker=ticker_upper,
                        company_name=entity_name,
                        raw_metadata={
                            "cik":                  cik,
                            "accession":            filing["accession"],
                            "form":                 filing["form"],
                            "owner_name":           txn["owner_name"],
                            "owner_cik":            txn.get("owner_cik"),
                            "title":                txn["title"],
                            "is_director":          txn.get("is_director", False),
                            "is_officer":           txn.get("is_officer", False),
                            "is_10pct_owner":       txn.get("is_10pct", False),
                            "transaction_code":     txn["code"],
                            "transaction_label":    label,
                            "security_title":       txn["security"],
                            "shares":               txn["shares"],
                            "price":                txn["price"],
                            "total_value":          total_value,
                            "shares_after":         txn["shares_after"],
                            "acquired_or_disposed": txn.get("acq_disp"),
                            "relevance_score":      _calc_relevance(txn["code"], total_value),
                        },
                    )

            except Exception as exc:
                logger.warning(
                    "InsiderTrading: erro ao processar Form 4 %s para %s: %s",
                    filing.get("accession"), ticker_upper, exc,
                )

    # ------------------------------------------------------------------
    # Resolução de CIK
    # ------------------------------------------------------------------

    async def _resolve_cik(self, ticker: str) -> int | None:
        if ticker in self._cik_cache:
            return self._cik_cache[ticker]

        resp = await self._get(TICKERS_URL, headers=EDGAR_HEADERS)
        data = resp.json()
        for entry in data.values():
            if entry.get("ticker", "").upper() == ticker:
                cik = int(entry["cik_str"])
                self._cik_cache[ticker] = cik
                return cik
        return None

    async def _fetch_submissions(self, cik: int) -> dict | None:
        url = SUBMISSIONS_URL.format(cik=cik)
        try:
            resp = await self._get(url, headers=EDGAR_HEADERS)
            return resp.json()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Filtro de filings Form 4
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_form4_filings(recent: dict, cutoff: datetime) -> list[dict]:
        forms      = recent.get("form", [])
        dates      = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        prim_docs  = recent.get("primaryDocument", [])

        result = []
        for form, date_str, acc, prim in zip(forms, dates, accessions, prim_docs):
            if form not in {"4", "4/A"}:
                continue
            try:
                filing_date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue
            if filing_date < cutoff:
                continue
            result.append({
                "form":             form,
                "filing_date":      filing_date,
                "accession":        acc,
                "primary_document": prim or "",
            })
        return result

    # ------------------------------------------------------------------
    # URL do XML bruto do Form 4
    # ------------------------------------------------------------------

    @staticmethod
    def _xml_url(cik: int, accession: str, primary_document: str) -> str:
        """
        Constrói a URL do XML bruto do Form 4.

        O campo primaryDocument nas submissions vem como:
          'xslF345X05/wk-form4_1234567890.xml'  ← versão XSLT (HTML renderizado)
        O XML puro está no mesmo diretório sem o prefixo do XSLT:
          'wk-form4_1234567890.xml'
        """
        acc_nodash = accession.replace("-", "")
        base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}"

        if primary_document:
            # Remove prefixo de XSLT se presente (ex: 'xslF345X05/')
            filename = primary_document.split("/")[-1]
            if filename.endswith(".xml"):
                return f"{base}/{filename}"
            # Troca .htm/.html pelo .xml correspondente (alguns filers usam HTM)
            filename_xml = filename.rsplit(".", 1)[0] + ".xml"
            return f"{base}/{filename_xml}"

        # Fallback: tenta via listagem do diretório
        return f"{base}/{acc_nodash}.xml"

    async def _find_xml_url(self, cik: int, accession: str, primary_document: str) -> str | None:
        """
        Tenta construir a URL do XML. Se o primaryDocument não resolver,
        faz fallback via listagem HTML do diretório EDGAR.
        """
        url = self._xml_url(cik, accession, primary_document)

        # Verifica se existe antes de retornar (HEAD request)
        try:
            import httpx
            resp = await self._client.head(url, headers=EDGAR_HEADERS)
            if resp.status_code == 200:
                return url
        except Exception:
            pass

        # Fallback: vasculha o índice HTML do filing
        acc_nodash = accession.replace("-", "")
        index_url  = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/"
        try:
            import re
            resp = await self._get(index_url, headers=EDGAR_HEADERS)
            # Procura links para arquivos .xml no HTML do índice
            xml_links = re.findall(
                r'/Archives/edgar/data/\d+/\d+/([^"]+\.xml)', resp.text
            )
            if xml_links:
                return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{xml_links[0]}"
        except Exception:
            pass

        return None

    # ------------------------------------------------------------------
    # Parse do XML do Form 4
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_form4_xml(xml_text: str, filing_date: datetime) -> list[dict]:
        """
        Extrai todas as transações (nonDerivative + derivative) do Form 4 XML.
        Retorna lista de dicts com campos normalizados.
        """
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []

        def text(el: ET.Element | None, path: str, default: str = "") -> str:
            if el is None:
                return default
            node = el.find(path)
            return (node.text or "").strip() if node is not None else default

        def fval(el: ET.Element | None, path: str) -> float | None:
            raw = text(el, path)
            if not raw:
                return None
            try:
                return float(raw.replace(",", ""))
            except ValueError:
                return None

        # Informações do insider
        owner_name    = text(root, ".//reportingOwner/reportingOwnerId/rptOwnerName")
        owner_cik     = text(root, ".//reportingOwner/reportingOwnerId/rptOwnerCik")
        rel           = root.find(".//reportingOwner/reportingOwnerRelationship")
        is_director   = text(rel, "isDirector") == "1"
        is_officer    = text(rel, "isOfficer")  == "1"
        is_10pct      = text(rel, "isTenPercentOwner") == "1"
        officer_title = text(rel, "officerTitle")

        if officer_title:
            insider_title = officer_title
        elif is_director and is_officer:
            insider_title = "Director & Officer"
        elif is_director:
            insider_title = "Director"
        elif is_10pct:
            insider_title = "10%+ Owner"
        else:
            insider_title = "Insider"

        base = {
            "owner_name": owner_name,
            "owner_cik":  owner_cik,
            "title":      insider_title,
            "is_director": is_director,
            "is_officer":  is_officer,
            "is_10pct":    is_10pct,
        }

        def _parse_txn(node: ET.Element) -> dict | None:
            security = (
                text(node, "securityTitle/value")
                or text(node, "securityTitle")
                or "Common Stock"
            )
            code     = text(node, "transactionCoding/transactionCode")
            shares   = fval(node, "transactionAmounts/transactionShares/value")
            price    = fval(node, "transactionAmounts/transactionPricePerShare/value")
            acq_disp = text(node, "transactionAmounts/transactionAcquiredDisposedCode/value")
            after    = fval(node, "postTransactionAmounts/sharesOwnedFollowingTransaction/value")
            date_raw = (
                text(node, "transactionDate/value")
                or text(node, "transactionDate")
            )
            try:
                date = datetime.strptime(date_raw, "%Y-%m-%d") if date_raw else filing_date
            except ValueError:
                date = filing_date

            if not code or shares is None:
                return None

            return {
                **base,
                "security":    security,
                "code":        code,
                "shares":      abs(shares),
                "price":       price,
                "acq_disp":    acq_disp,
                "shares_after": after,
                "date":        date,
            }

        transactions = []
        for tag in (".//nonDerivativeTransaction", ".//derivativeTransaction"):
            for node in root.findall(tag):
                txn = _parse_txn(node)
                if txn:
                    transactions.append(txn)

        return transactions

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filing_url(cik: int, accession: str) -> str:
        acc_nodash = accession.replace("-", "")
        return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/"
