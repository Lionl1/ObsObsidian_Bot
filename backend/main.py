from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from bot import build_dispatcher
from config import get_settings
from services import scan_obsidian_vault


async def main() -> None:
    settings = get_settings()
    settings.vault_path.mkdir(parents=True, exist_ok=True)

    vault_index = await scan_obsidian_vault(settings.vault_path)
    logging.getLogger(__name__).info(
        "Indexed %s notes and %s tags from %s",
        len(vault_index.notes),
        len(vault_index.tags),
        settings.vault_path,
    )

    dispatcher = build_dispatcher(settings)
    async with Bot(token=settings.telegram_bot_token) as bot:
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    asyncio.run(main())
