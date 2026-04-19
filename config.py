from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_SYSTEM_PROMPT = """Ты — AI-ассистент для создания структурированных заметок в Obsidian.
Ты ведешь диалог с пользователем и учитываешь предыдущие сообщения.
Сегодняшняя дата: {today}.

Если пользователь дает статью или просит создать или переделать заметку, выдай финальный результат строго в Markdown-блоке.
Начинай заметку с YAML frontmatter в таком виде:
---
tags: [теги]
source: {{URL или unknown}}
date: {{дата в формате YYYY-MM-DD}}
---

Затем продолжай заметку так:
# Заголовок
## Краткая выжимка
## Ключевые тезисы
## Архитектура
## Ссылки

В разделе "Ссылки" перечисли в виде списка все URL, которые были использованы при создании заметки.

Если архитектурная схема уместна, добавь mermaid-блок внутри раздела "Архитектура".
Если пользователь просто задает вопрос по статье, отвечает по контексту или просит что-то уточнить без создания заметки, отвечай в свободной форме и не заставляй ответ быть заметкой.
Опирайся на существующие заметки и теги из хранилища. Старайся использовать перекрестные ссылки вида [[Название существующей заметки]], если темы пересекаются.
"""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")
    telegram_user_id: int = Field(alias="TELEGRAM_USER_ID")

    openai_api_key: str = Field(default="local", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(alias="OPENAI_BASE_URL")
    openai_model: str = Field(alias="OPENAI_MODEL")
    openai_timeout_seconds: int = Field(default=120, alias="OPENAI_TIMEOUT_SECONDS")

    obsidian_vault_path: Path | None = Field(default=None, alias="OBSIDIAN_VAULT_PATH")
    host_obsidian_path: Path | None = Field(default=None, alias="HOST_OBSIDIAN_PATH")
    container_obsidian_path: Path | None = Field(default=None, alias="CONTAINER_OBSIDIAN_PATH")

    history_limit: int = Field(default=18, alias="HISTORY_LIMIT")
    article_text_limit: int = Field(default=15000, alias="ARTICLE_TEXT_LIMIT")
    obsidian_prompt_notes_limit: int = Field(default=100, alias="OBSIDIAN_PROMPT_NOTES_LIMIT")
    obsidian_note_content_limit: int = Field(default=12000, alias="OBSIDIAN_NOTE_CONTENT_LIMIT")

    system_prompt_template: str = DEFAULT_SYSTEM_PROMPT

    @property
    def vault_path(self) -> Path:
        for candidate in (
            self.obsidian_vault_path,
            self.host_obsidian_path,
            self.container_obsidian_path,
        ):
            if candidate is not None:
                return candidate

        raise ValueError(
            "Не задан путь к Obsidian vault. Укажите OBSIDIAN_VAULT_PATH "
            "или пару HOST_OBSIDIAN_PATH / CONTAINER_OBSIDIAN_PATH."
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
