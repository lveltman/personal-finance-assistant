"""Bot entry point."""
import asyncio
import logging

import structlog
from aiogram import Bot, Dispatcher
from src import config
from src.bot.handlers import router


def setup_logging() -> None:
    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
    )
    logging.basicConfig(level=level)


async def main() -> None:
    setup_logging()
    log = structlog.get_logger()

    config.SESSION_DIR.mkdir(parents=True, exist_ok=True)

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    log.info("bot_starting", model=config.LLM_MODEL, fallback=config.LLM_FALLBACK_MODEL)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
