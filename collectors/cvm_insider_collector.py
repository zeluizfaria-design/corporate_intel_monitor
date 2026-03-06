"""
Coleta negociações de valores mobiliários por administradores (insiders) via CVM.

A CVM exige que diretores estatutários, membros do Conselho de Administração,
acionistas controladores e membros do Conselho Fiscal divulguem suas negociações
de valores mobiliários (Instrução CVM 358/2002, art. 11).

Fonte de dados:
  https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/NEGOCIACAO/DADOS/
  Arquivos CSV anuais: negociacao_cia_aberta_{year}.csv

Mapeamento ticker → CD_CVM via cadastro:
  https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv

Nota: os dados ficam disponíveis com atraso de até 10 dias úteis após o
prazo de entrega pelo insider (15 dias corridos após a negociação).
"""
import csv
import hashlib
import io
import logging
import zipfile
from datetime import datetime, timedelta
from typing import AsyncIterator

from .base_collector import BaseCollector, RawArticle

logger = logging.getLogger(__name__)

CVM_VLMO_BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/VLMO/DADOS"
CVM_CAD_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"

# Mapeamentos de tipo de operação (Crédito=COMPRA, Débito=VENDA)
_TIPO_MAP: dict[str, str] = {
    "Crédito": "COMPRA",
    "Débito":  "VENDA",
    "Credito": "COMPRA",
    "Debito":  "VENDA",
}

# Relevance score por tipo
_RELEVANCE: dict[str, int] = {
    "COMPRA": 3,
    "VENDA":  3,
}


class CVMInsiderCollector(BaseCollector):
    """
    Coleta negociações de administradores de empresas B3 via CVM open data.

    Cobre:
    - Diretores estatutários
    - Membros do Conselho de Administração
    - Acionistas controladores (pessoa natural ou jurídica)
    - Membros do Conselho Fiscal

    Uso:
        async with CVMInsiderCollector() as c:
            async for article in c.collect("PETR4", days_back=180):
                print(article.title)
    """

    # Cache compartilhado entre instâncias: ticker → (cd_cvm, company_name)
    _cad_cache: dict[str, tuple[str, str]] = {}

    def __init__(self, rate_limit_rps: float = 0.5):
        super().__init__(rate_limit_rps=rate_limit_rps)

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    async def collect(
        self,
        ticker: str,
        days_back: int = 365,
    ) -> AsyncIterator[RawArticle]:
        """
        Coleta negociações de insiders para o ticker B3.

        Args:
            ticker:    Ticker na B3 (ex: PETR4, VALE3, ITUB4)
            days_back: Quantos dias retroativos buscar (default: 365)
        """
        ticker_upper = ticker.upper()
        cutoff       = datetime.now() - timedelta(days=days_back)

        # Resolve CNPJ para o ticker
        result = await self._resolve_cnpj(ticker_upper)
        if result is None:
            logger.warning("CVMInsider: CNPJ não encontrado para %s", ticker_upper)
            return

        cnpj, company_name = result

        # Coleta arquivos VLMO dos anos relevantes
        years = list(range(cutoff.year, datetime.now().year + 1))
        for year in years:
            url = f"{CVM_VLMO_BASE}/vlmo_cia_aberta_{year}.zip"
            try:
                resp = await self._get(url)
            except Exception as exc:
                logger.warning("CVMInsider: erro ao buscar %s: %s", url, exc)
                continue

            try:
                z = zipfile.ZipFile(io.BytesIO(resp.content))
                con_filename = f"vlmo_cia_aberta_con_{year}.csv"
                if con_filename not in z.namelist():
                    continue
                content = z.read(con_filename)
            except Exception as exc:
                logger.warning("CVMInsider: erro ao ler zip %s: %s", url, exc)
                continue

            rows = self._parse_csv(content, cnpj, cutoff)
            for row in rows:
                article = self._row_to_article(row, ticker_upper, company_name)
                if article:
                    yield article


    # ------------------------------------------------------------------
    # Resolução de CNPJ via cadastro FCA
    # ------------------------------------------------------------------

    async def _resolve_cnpj(self, ticker: str) -> tuple[str, str] | None:
        """Retorna (CNPJ_Companhia, Nome_Empresarial) para o ticker, usando FCA."""
        if ticker in self._cad_cache:
            return self._cad_cache[ticker]

        years_to_try = [datetime.now().year, datetime.now().year - 1]
        for year in years_to_try:
            url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_{year}.zip"
            try:
                resp = await self._get(url)
                if resp.status_code != 200:
                    continue
                
                z = zipfile.ZipFile(io.BytesIO(resp.content))
                csv_filename = f"fca_cia_aberta_valor_mobiliario_{year}.csv"
                if csv_filename not in z.namelist():
                    continue
                
                content = z.read(csv_filename)
                try:
                    text = content.decode("latin-1")
                except Exception:
                    text = content.decode("utf-8", errors="replace")
                
                reader = csv.DictReader(io.StringIO(text), delimiter=";")
                for row in reader:
                    row_ticker = (row.get("Codigo_Negociacao") or "").strip().upper()
                    
                    if row_ticker == ticker or (
                        len(row_ticker) >= 4 and ticker.startswith(row_ticker[:4])
                        and row_ticker[:4] == ticker[:4]
                    ):
                        cnpj = (row.get("CNPJ_Companhia") or "").strip()
                        if cnpj:
                            name = (row.get("Nome_Empresarial") or ticker).strip()
                            self._cad_cache[ticker] = (cnpj, name)
                            return cnpj, name
            except Exception as exc:
                logger.warning("CVMInsider: erro ao buscar FCA CVM: %s", exc)
                continue

        return None

    # ------------------------------------------------------------------
    # Parse do CSV de negociações (VLMO)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_csv(content: bytes, cnpj: str, cutoff: datetime) -> list[dict]:
        """Filtra linhas do CSV pelo CNPJ_Companhia e período, retorna lista de dicts."""
        try:
            text = content.decode("latin-1")
        except Exception:
            text = content.decode("utf-8", errors="replace")

        try:
            reader = csv.DictReader(io.StringIO(text), delimiter=";")
            fieldnames = reader.fieldnames or []
            reader.fieldnames = [f.lstrip("\ufeff").strip() for f in fieldnames]
        except Exception as exc:
            logger.warning("CVMInsider: erro ao parsear CSV: %s", exc)
            return []

        rows = []
        for row in reader:
            row_cnpj = (row.get("CNPJ_Companhia") or "").strip()
            if row_cnpj != cnpj:
                continue

            date_str = (row.get("Data_Movimentacao") or "").strip()
            if not date_str:
                continue

            date = None
            for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
                try:
                    date = datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    continue

            if not date or date < cutoff:
                continue

            row["_date"] = date
            rows.append(dict(row))

        return rows

    # ------------------------------------------------------------------
    # Conversão de linha CSV (VLMO) → RawArticle
    # ------------------------------------------------------------------

    def _row_to_article(self, row: dict, ticker: str, company_name: str) -> RawArticle | None:
        date = row.get("_date")
        if not date:
            return None

        # Na VLMO os nomes individuais não são divulgados, apenas a Posição (Cargo)
        cargo = (row.get("Tipo_Cargo") or "N/D").strip()
        nome  = f"Posição Consolidada ({cargo})"

        tipo_raw = (row.get("Tipo_Operacao") or "").strip() # Crédito / Débito
        tipo_label = _TIPO_MAP.get(tipo_raw, _TIPO_MAP.get(tipo_raw.capitalize(), tipo_raw.upper() or "TRANSAÇÃO"))

        # Quantidade
        qtde = self._parse_float(row.get("Quantidade") or "0")

        # Preço
        preco = self._parse_float(row.get("Preco_Unitario") or "0")

        # Se Preco_Unitario estiver zerado ou vazio mas houver Volume, tenta inferir
        volume = self._parse_float(row.get("Volume") or "0")
        if preco <= 0 and qtde > 0 and volume > 0:
            preco = volume / qtde

        total = qtde * preco if qtde and preco else volume

        # Ativo negociado
        tipo_ativo = (row.get("Tipo_Ativo") or "").strip()
        caract = (row.get("Caracteristica_Valor_Mobiliario") or "").strip()
        ativo = f"{tipo_ativo} {caract}".strip() or "Valor Mobiliário"

        qtde_str  = f"{qtde:,.0f}" if qtde else "N/D"
        preco_str = f"@ R${preco:,.2f}" if preco else ""
        total_str = f"= R${total:,.0f}" if total else ""

        title = (
            f"[INSIDER CVM][{tipo_label}] {nome} — "
            f"{qtde_str} {ativo} {preco_str} {total_str} | {ticker}"
        ).strip()

        lines = [
            f"Insider (Consolidado): {nome}",
            f"Cargo:           {cargo}",
            f"Empresa:         {company_name} ({ticker})",
            f"Tipo (Balanço):  {tipo_raw} - {row.get('Tipo_Movimentacao', '')}",
            f"Ação:            {tipo_label}",
            f"Ativo:           {ativo}",
            f"Quantidade:      {qtde_str}",
        ]
        if preco > 0:
            lines.append(f"Preço unitário:  R${preco:,.4f}")
        if total > 0:
            lines.append(f"Valor total:     R${total:,.0f}")
        lines.append(f"Data:            {date.strftime('%d/%m/%Y')}")
        lines.append(f"Fonte:           CVM — Posição Consolidada de Valores Mobiliários (VLMO)")

        content = "\n".join(lines)

        # URL única para deduplicação
        uid = hashlib.sha256(
            f"{cargo}|{date.isoformat()}|{ticker}|{tipo_raw}|{qtde}".encode()
        ).hexdigest()[:20]
        url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/VLMO/#cvm-{uid}"

        relevance = _RELEVANCE.get(tipo_label, 1)
        if total > 1_000_000:
            relevance = min(relevance + 1, 3)

        return RawArticle(
            source="CVM Posição VLMO",
            source_type="insider_trade",
            url=url,
            title=title,
            content=content,
            published_at=date,
            company_ticker=ticker,
            company_name=company_name,
            raw_metadata={
                "cnpj_cvm":         row.get("CNPJ_Companhia", "").strip(),
                "nome_negociante":  nome,
                "cargo":            cargo,
                "tipo_negociacao":  tipo_raw,
                "tipo_label":       tipo_label,
                "ativo":            ativo,
                "quantidade":       qtde,
                "preco":            preco,
                "total_value":      total,
                "relevance_score":  relevance,
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_float(value: str | None) -> float:
        if not value:
            return 0.0
        try:
            # O novo formato VLMO usa ponto (.) como separador decimal.
            # Caso apareçam vírgulas isoladas como decimais, trocamos por ponto.
            # Se for uma string com formato inglês ou CVM padrão (ex: "123.45"), float() já lida corretamente.
            cleaned = str(value).strip()
            # Se tiver tanto vírgula quanto ponto (ex: 1,234.56 ou 1.234,56), tentamos limpar milhar primeiro
            if "," in cleaned and "." in cleaned:
                if cleaned.rfind(",") > cleaned.rfind("."):
                    # Formato BR: 1.234,56
                    cleaned = cleaned.replace(".", "").replace(",", ".")
                else:
                    # Formato US: 1,234.56
                    cleaned = cleaned.replace(",", "")
            elif "," in cleaned:
                # Apenas vírgula: convertemos para ponto (decimal)
                cleaned = cleaned.replace(",", ".")
            
            return float(cleaned)
        except (ValueError, AttributeError):
            return 0.0
