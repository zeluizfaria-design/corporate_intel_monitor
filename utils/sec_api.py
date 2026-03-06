"""Integração com a API do SEC EDGAR para buscar SIC Codes."""
import asyncio
import httpx
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Caching em memória (singleton-like per worker)
_TICKER_TO_CIK_CACHE: Dict[str, str] = {}
_CIK_TO_SIC_CACHE: Dict[str, str] = {}
_TICKERS_LOADED = False

async def _load_company_tickers():
    global _TICKERS_LOADED
    if _TICKERS_LOADED:
        return
    
    url = "https://www.sec.gov/files/company_tickers.json"
    headers = {
        # SEC requires proper User-Agent
        "User-Agent": "CorporateIntelMonitor/1.0 (contact@example.com)",
        "Accept-Encoding": "gzip, deflate"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            
            for key, entry in data.items():
                ticker = entry.get("ticker")
                cik_str = str(entry.get("cik_str")).zfill(10)
                if ticker:
                    _TICKER_TO_CIK_CACHE[ticker.upper()] = cik_str
                    
            _TICKERS_LOADED = True
            logger.debug(f"Loaded {len(_TICKER_TO_CIK_CACHE)} tickers from SEC API.")
    except Exception as e:
        logger.error(f"Error loading SEC company tickers: {e}")

async def get_sic_for_ticker(ticker: Optional[str]) -> Optional[str]:
    """Retorna o SIC Code para um dado ticker, utilizando a API da SEC (EDGAR)."""
    if not ticker:
        return None
        
    ticker = ticker.upper()
    await _load_company_tickers()
    
    cik = _TICKER_TO_CIK_CACHE.get(ticker)
    if not cik:
        return None
        
    # Verifica cache
    if cik in _CIK_TO_SIC_CACHE:
        return _CIK_TO_SIC_CACHE[cik]
        
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    headers = {
        "User-Agent": "CorporateIntelMonitor/1.0 (contact@example.com)",
        "Accept-Encoding": "gzip, deflate"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=10.0)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            
            sic = data.get("sic")
            if sic:
                _CIK_TO_SIC_CACHE[cik] = str(sic)
                return str(sic)
    except Exception as e:
        logger.error(f"Error fetching SIC for CIK {cik} ({ticker}): {e}")
        
    return None
