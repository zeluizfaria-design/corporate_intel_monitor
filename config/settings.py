"""
Configurações centrais do Corporate Intelligence Monitor.
Carrega variáveis do arquivo .env via pydantic-settings.
"""
from __future__ import annotations

import json
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Tickers monitorados ---
    target_tickers: list[str] = Field(
        default=["PETR4", "VALE3", "AAPL"],
        description="Lista de tickers a monitorar (separados por vírgula no .env)",
    )

    # --- Twitter / X ---
    twitter_bearer_token: str | None = None

    # --- Reddit ---
    reddit_client_id:     str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent:    str = "CorporateIntelMonitor/1.0"

    # --- Discord ---
    discord_bot_token: str | None = None
    discord_channels:  list[int] = Field(
        default=[],
        description="IDs dos canais Discord a monitorar (separados por vírgula no .env)",
    )

    # --- Telegram ---
    telegram_api_id:   int | None = None
    telegram_api_hash: str | None = None
    telegram_phone:    str | None = None   # ex: +5511999990000
    telegram_channels: list[str] | None = None

    # --- LinkedIn ---
    linkedin_cookies_path: str | None = None   # path para linkedin_cookies.json

    # --- Kalshi (leitura pública; auth para dados de portfólio) ---
    kalshi_email:    str | None = None
    kalshi_password: str | None = None

    # --- Betfair ---
    betfair_username: str | None = None
    betfair_password: str | None = None
    betfair_app_key:  str | None = None

    # --- Deriv ---
    deriv_app_id: str = "1089"   # app_id público para leitura
    deriv_token:  str | None = None

    # --- IQ Option ---
    iq_option_email:    str | None = None
    iq_option_password: str | None = None

    # --- Claude API (síntese de briefings) ---
    anthropic_api_key: str | None = None

    # --- Quiver Quantitative (negociações de congressistas) ---
    # Registro gratuito em https://quiverquant.com
    # Sem a key o endpoint bulk pode retornar 401 por rate limiting
    quiver_api_key: str | None = None

    # --- Alertas webhook ---
    # Slack: criar Incoming Webhook em https://api.slack.com/messaging/webhooks
    slack_webhook_url: str | None = None

    # Telegram: criar bot via @BotFather, obter token e chat_id
    alert_telegram_bot_token: str | None = None
    alert_telegram_chat_id:   str | None = None  # ex: "-1001234567890"

    # Threshold: valor mínimo (USD) para alertar em insider trades
    alert_insider_min_value: float = 100_000.0

    # --- Coleta ---
    days_back: int = 30

    # Mapa de dupla listagem: ticker BR → ticker US
    # Lido de uma string JSON no .env:
    # DUAL_LISTED_MAP='{"VALE3":"VALE","PETR4":"PBR","ITUB4":"ITUB"}'
    dual_listed_map: dict[str, str] = Field(default_factory=dict)
