from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from aiogram import Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from config import Settings
from services import (
    ArticleExtractionError,
    HistoryEntry,
    LLMServiceError,
    NoteLookupError,
    build_openai_client,
    extract_note_from_response,
    extract_note_read_query,
    extract_urls,
    generate_llm_reply,
    prepare_user_message,
    prepare_existing_note_context,
    save_note,
    scan_obsidian_vault,
)


logger = logging.getLogger(__name__)
MAX_TELEGRAM_MESSAGE_LENGTH = 4000


@dataclass(slots=True)
class ConversationMemory:
    limit: int
    storage: dict[int, list[HistoryEntry]] = field(default_factory=lambda: defaultdict(list))

    def get(self, user_id: int) -> list[HistoryEntry]:
        return list(self.storage.get(user_id, []))

    def add(self, user_id: int, role: str, content: str) -> None:
        history = self.storage.setdefault(user_id, [])
        history.append({"role": role, "content": content})
        if len(history) > self.limit:
            self.storage[user_id] = history[-self.limit :]

    def pop_last(self, user_id: int) -> None:
        history = self.storage.get(user_id)
        if not history:
            return
        history.pop()
        if not history:
            self.storage.pop(user_id, None)

    def clear(self, user_id: int) -> None:
        self.storage.pop(user_id, None)


def build_dispatcher(settings: Settings) -> Dispatcher:
    dispatcher = Dispatcher()
    router = Router()
    memory = ConversationMemory(limit=settings.history_limit)
    llm_client = build_openai_client(settings)

    async def ensure_access(message: Message) -> bool:
        user_id = message.from_user.id if message.from_user else None
        if message.chat.type != "private":
            await message.answer("Бот работает только в приватном чате.")
            return False
        if user_id != settings.telegram_user_id:
            logger.warning("Rejected access for user_id=%s", user_id)
            await message.answer("Бот приватный и доступен только владельцу.")
            return False
        return True

    async def send_text_chunks(message: Message, text: str) -> None:
        buffer = ""
        for line in text.splitlines(keepends=True):
            if len(line) > MAX_TELEGRAM_MESSAGE_LENGTH:
                if buffer:
                    await message.answer(buffer.rstrip())
                    buffer = ""
                for index in range(0, len(line), MAX_TELEGRAM_MESSAGE_LENGTH):
                    await message.answer(line[index : index + MAX_TELEGRAM_MESSAGE_LENGTH].rstrip())
                continue
            if len(buffer) + len(line) > MAX_TELEGRAM_MESSAGE_LENGTH:
                await message.answer(buffer.rstrip())
                buffer = line
            else:
                buffer += line

        if buffer:
            await message.answer(buffer.rstrip())

    @router.message(CommandStart())
    async def handle_start(message: Message) -> None:
        if not await ensure_access(message):
            return

        await message.answer(
            "Пришлите текст, ссылку, пересланное сообщение или файл.\n"
            "Я сохраню контекст диалога и по команде /clear сброшу историю."
        )

    @router.message(Command("clear"))
    async def handle_clear(message: Message) -> None:
        if not await ensure_access(message):
            return

        memory.clear(message.from_user.id)
        await message.answer("Контекст диалога очищен.")

    @router.message()
    async def handle_message(message: Message) -> None:
        if not await ensure_access(message):
            return

        raw_text = message.text or message.caption or ""
        has_attachments = bool(message.document or message.photo or message.video or message.audio)
        if not (raw_text or has_attachments):
            await message.answer("Отправьте текст, ссылку или файл, чтобы собрать заметку.")
            return

        user_id = message.from_user.id

        try:
            async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
                vault_index = await scan_obsidian_vault(settings.vault_path)
                note_context = (
                    await prepare_existing_note_context(raw_text, vault_index, settings)
                    if raw_text
                    else None
                )
                has_urls = bool(extract_urls(raw_text))
                note_only_request = bool(raw_text) and bool(extract_note_read_query(raw_text))

                if note_context is not None and note_only_request and not has_urls and not has_attachments:
                    user_content, note = note_context
                    await message.answer(f"📚 Загрузил заметку '{note.link_name}' в контекст.")
                else:
                    message_content, _ = await prepare_user_message(raw_text, settings)
                    if note_context is not None:
                        note_content, note = note_context
                        await message.answer(f"📚 Загрузил заметку '{note.link_name}' в контекст.")
                        if message_content:
                            user_content = f"{note_content}\n\nДополнительные материалы пользователя:\n\n{message_content}"
                        else:
                            user_content = note_content
                    else:
                        user_content = message_content
        except ArticleExtractionError as exc:
            await message.answer(f"Не удалось обработать статью: {exc}")
            return
        except NoteLookupError as exc:
            await message.answer(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error while preparing message")
            await message.answer(f"Ошибка при обработке сообщения: {exc}")
            return

        memory.add(user_id, "user", user_content)

        try:
            async with ChatActionSender.typing(bot=message.bot, chat_id=message.chat.id):
                assistant_reply = await generate_llm_reply(
                    memory.get(user_id),
                    llm_client,
                    settings,
                    vault_index=vault_index,
                )
        except LLMServiceError as exc:
            memory.pop_last(user_id)
            await message.answer(str(exc))
            return
        except Exception:  # noqa: BLE001
            memory.pop_last(user_id)
            logger.exception("Unexpected error while generating reply")
            await message.answer("Произошла непредвиденная ошибка во время генерации ответа.")
            return

        memory.add(user_id, "assistant", assistant_reply)

        note = extract_note_from_response(assistant_reply)
        if note is not None:
            try:
                result = await save_note(note, settings.vault_path)
                status = "обновлена" if result.updated else "сохранена"
                await message.answer(f"✅ Заметка '{result.filename}' {status}")
            except Exception:  # noqa: BLE001
                logger.exception("Failed to save note")
                await message.answer("Ответ с заметкой получен, но сохранить файл в Obsidian не удалось.")

        await send_text_chunks(message, assistant_reply)

    async def close_client() -> None:
        await llm_client.close()

    dispatcher.shutdown.register(close_client)
    dispatcher.include_router(router)
    return dispatcher
