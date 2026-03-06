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
