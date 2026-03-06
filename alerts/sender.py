"""Envio de alertas via Slack e Telegram."""
from __future__ import annotations

import logging
import httpx

logger = logging.getLogger(__name__)


async def send_slack(webhook_url: str, message: str) -> bool:
    """Envia mensagem para um canal Slack via Incoming Webhook."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json={"text": message})
            if resp.status_code == 200:
                return True
            logger.warning(f"[Slack] Status inesperado: {resp.status_code} — {resp.text}")
    except Exception as e:
        logger.error(f"[Slack] Erro ao enviar alerta: {e}")
    return False


async def send_telegram(bot_token: str, chat_id: str, message: str) -> bool:
    """Envia mensagem via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
            if data.get("ok"):
                return True
            logger.warning(f"[Telegram] Erro da API: {data.get('description')}")
    except Exception as e:
        logger.error(f"[Telegram] Erro ao enviar alerta: {e}")
    return False


async def dispatch_alert(message: str, slack_url: str | None, tg_token: str | None, tg_chat: str | None) -> None:
    """Envia alerta para todos os canais configurados."""
    if slack_url:
        await send_slack(slack_url, message)
    if tg_token and tg_chat:
        await send_telegram(tg_token, tg_chat, message)
