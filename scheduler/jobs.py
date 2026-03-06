"""APScheduler jobs para coleta automática periódica."""
import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import Settings
from storage.database import Database

logger = logging.getLogger(__name__)


async def collect_all_tickers(settings: Settings):
    """Roda coleta completa para todos os tickers configurados e dispara alertas."""
    from main import run_collection, run_dual_listed
    from alerts.checker import check_and_alert

    db = Database()
    db.seed_watchlist(settings.target_tickers, settings.dual_listed_map)
    watchlist = db.get_watchlist()

    for item in watchlist:
        ticker = item['ticker']
        if item['is_dual'] and item['us_ticker']:
            us_ticker = item['us_ticker']
            try:
                logger.info(f"[Scheduler] Coleta dupla listagem: {ticker} / {us_ticker}")
                await run_dual_listed(ticker, us_ticker, settings, days_back=settings.days_back)
            except Exception as e:
                logger.error(f"[Scheduler] Erro na coleta dual {ticker}/{us_ticker}: {e}")
        else:
            try:
                logger.info(f"[Scheduler] Iniciando coleta para {ticker}")
                await run_collection(ticker, settings, days_back=settings.days_back)
                logger.info(f"[Scheduler] Coleta concluída para {ticker}")
            except Exception as e:
                logger.error(f"[Scheduler] Erro ao coletar {ticker}: {e}")

    # Verifica e dispara alertas após cada rodada de coleta
    try:
        sent = await check_and_alert(db, settings)
        if sent:
            logger.info(f"[Scheduler] {sent} alerta(s) enviado(s)")
    except Exception as e:
        logger.error(f"[Scheduler] Erro ao verificar alertas: {e}")


def create_scheduler(settings: Settings) -> AsyncIOScheduler:
    """Cria e configura o scheduler com os jobs padrão."""
    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        collect_all_tickers,
        trigger=IntervalTrigger(hours=4),
        args=[settings],
        id="collect_all",
        name="Coleta completa de todos os tickers",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    return scheduler


async def run_scheduler():
    """Entry point para rodar o scheduler standalone."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    settings = Settings()
    scheduler = create_scheduler(settings)

    logger.info("Iniciando scheduler — coleta a cada 4 horas")
    scheduler.start()

    # Executa coleta imediatamente na inicialização
    await collect_all_tickers(settings)

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Encerrando scheduler...")
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(run_scheduler())
