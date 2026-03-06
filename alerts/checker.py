"""Detecção de eventos de alta relevância e disparo de alertas."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from alerts.sender import dispatch_alert
from utils.sec_api import get_sic_for_ticker

if TYPE_CHECKING:
    from config.settings import Settings
    from storage.database import Database

logger = logging.getLogger(__name__)

# Setores regulados: tickers ou palavras no nome da empresa
_REGULATED_KEYWORDS = {
    "bank", "financial", "insurance", "pharma", "health", "defense",
    "energy", "oil", "gas", "utility", "telecom", "semiconductor",
    "petro", "saude", "financ", "seguro", "energia", "defesa",
}


def _parse_amount(amount_raw) -> float | None:
    """Tenta extrair valor numérico de strings como '100000-500000' ou 150000."""
    if amount_raw is None:
        return None
    if isinstance(amount_raw, (int, float)):
        return float(amount_raw)
    s = str(amount_raw).replace(",", "").replace("$", "").strip()
    # Intervalo: pega o valor máximo para ser conservador
    if "-" in s:
        parts = s.split("-")
        try:
            return max(float(p.strip()) for p in parts if p.strip())
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _is_regulated(company_name: str) -> bool:
    name_lower = (company_name or "").lower()
    return any(kw in name_lower for kw in _REGULATED_KEYWORDS)


def _is_regulated_sic(sic: str) -> bool:
    if not sic:
        return False
    # Finance/Banking/Insurance: 6000-6499, 6700-6799
    if sic.startswith(("60", "61", "62", "63", "64", "67")):
        return True
    # Healthcare/Pharma/Biotech: 2830-2839, 8000-8099
    if sic.startswith("283") or sic.startswith("80"):
        return True
    # Defense/Aerospace: 3720-3729, 3760-3769, 3810-3819
    if sic.startswith(("372", "376", "381")):
        return True
    # Energy/Utilities: 1300-1399, 2900-2999, 4900-4999
    if sic.startswith(("13", "29", "49")):
        return True
    # Telecommunications: 4800-4899
    if sic.startswith("48"):
        return True
    # Semiconductors: 3674
    if sic.startswith("3674"):
        return True
    return False


def _format_insider_alert(article: dict) -> str:
    meta: dict = {}
    raw = article.get("raw_metadata")
    if isinstance(raw, str):
        try:
            meta = json.loads(raw)
        except Exception:
            meta = {}
    elif isinstance(raw, dict):
        meta = raw

    ticker  = article.get("company_ticker", "???")
    title   = article.get("title", "")
    url     = article.get("url", "")
    pub_at  = article.get("published_at", "")
    if isinstance(pub_at, datetime):
        pub_at = pub_at.strftime("%d/%m/%Y")

    total   = meta.get("total_value")
    total_s = f"${total:,.0f}" if total else "N/D"
    score   = meta.get("relevance_score", 1)
    code    = meta.get("transaction_code", "")
    label   = {"P": "COMPRA", "S": "VENDA", "A": "CONCESSAO"}.get(code, code)
    insider = meta.get("insider_name", "")

    msg = (
        f"*[ALERTA INSIDER]* {ticker} — {label}\n"
        f"*Insider:* {insider}\n"
        f"*Valor:* {total_s}  |  *Score:* {score}/3\n"
        f"*Data:* {pub_at}\n"
        f"*Título:* {title[:100]}\n"
        f"*Link:* {url}"
    )
    return msg


def _format_politician_alert(article: dict) -> str:
    meta: dict = {}
    raw = article.get("raw_metadata")
    if isinstance(raw, str):
        try:
            meta = json.loads(raw)
        except Exception:
            meta = {}
    elif isinstance(raw, dict):
        meta = raw

    ticker    = article.get("company_ticker", "???")
    title     = article.get("title", "")
    url       = article.get("url", "")
    pub_at    = article.get("published_at", "")
    if isinstance(pub_at, datetime):
        pub_at = pub_at.strftime("%d/%m/%Y")

    name      = meta.get("politician_name", "")
    party     = meta.get("party", "")
    chamber   = meta.get("chamber", "")
    tx_label  = meta.get("transaction_label", meta.get("transaction_type", ""))
    amount    = meta.get("amount", "N/D")
    company   = article.get("company_name", ticker)

    msg = (
        f"*[ALERTA POLÍTICO]* {ticker} — {tx_label}\n"
        f"*Político:* {name} ({party}) — {chamber}\n"
        f"*Empresa:* {company}  |  *Valor:* {amount}\n"
        f"*Data:* {pub_at}\n"
        f"*Título:* {title[:100]}\n"
        f"*Link:* {url}"
    )
    return msg


async def check_and_alert(db: "Database", settings: "Settings", ticker: str | None = None) -> int:
    """
    Verifica artigos novos de alta relevância e envia alertas.
    Retorna número de alertas enviados.

    Triggers:
    - insider_trade: total_value >= alert_insider_min_value OU relevance_score >= 2
    - politician_trade: qualquer compra/venda de setor regulado (ou qualquer trade)
    """
    slack_url = settings.slack_webhook_url
    tg_token  = settings.alert_telegram_bot_token
    tg_chat   = settings.alert_telegram_chat_id

    # Sem canais configurados: não há nada a fazer
    if not slack_url and not (tg_token and tg_chat):
        return 0

    if ticker:
        tickers = [ticker]
    else:
        tickers = [item["ticker"] for item in db.get_watchlist()]
    sent_count = 0

    for t in tickers:
        articles = db.query_by_ticker(
            t,
            days=2,  # últimas 48h
            source_types=["insider_trade", "politician_trade"],
        )

        for article in articles:
            art_id = article.get("id", "")
            if not art_id or db.is_alert_sent(art_id):
                continue

            source_type = article.get("source_type", "")
            should_alert = False
            alert_msg = ""

            if source_type == "insider_trade":
                meta: dict = {}
                raw = article.get("raw_metadata")
                if isinstance(raw, str):
                    try:
                        meta = json.loads(raw)
                    except Exception:
                        pass
                elif isinstance(raw, dict):
                    meta = raw

                total_value    = meta.get("total_value") or 0.0
                relevance_score = meta.get("relevance_score", 1)

                if total_value >= settings.alert_insider_min_value or relevance_score >= 2:
                    should_alert = True
                    alert_msg = _format_insider_alert(article)

            elif source_type == "politician_trade":
                meta = {}
                raw = article.get("raw_metadata")
                if isinstance(raw, str):
                    try:
                        meta = json.loads(raw)
                    except Exception:
                        pass
                elif isinstance(raw, dict):
                    meta = raw

                tx_type = (meta.get("transaction_type") or "").lower()
                company = article.get("company_name", "") or ""
                amount_raw = meta.get("amount")
                amount_val = _parse_amount(amount_raw) or 0.0

                # Novo bloco para resolver SIC code primeiro
                company_ticker = article.get("company_ticker") or ""
                sic_code = await get_sic_for_ticker(company_ticker)
                
                if sic_code:
                    is_reg = _is_regulated_sic(sic_code)
                else:
                    is_reg = _is_regulated(company)

                # Alerta se setor regulado OU valor alto
                if is_reg or amount_val >= settings.alert_insider_min_value:
                    if tx_type in ("buy", "sell", "purchase", "sale", "compra", "venda", ""):
                        should_alert = True
                        alert_msg = _format_politician_alert(article)

            if should_alert and alert_msg:
                try:
                    await dispatch_alert(alert_msg, slack_url, tg_token, tg_chat)
                    db.mark_alert_sent(art_id)
                    sent_count += 1
                    logger.info(f"[Alert] Enviado para {t}: {article.get('title', '')[:80]}")
                except Exception as e:
                    logger.error(f"[Alert] Falha ao enviar alerta {art_id}: {e}")

    return sent_count
