from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_SYSTEM_PROMPT = """You are an AI assistant that creates structured notes for Obsidian.
You maintain the conversation context and use previous user messages when relevant.
Today's date: {today}.

If the user provides an article or asks you to create or rewrite a note, return the final result as plain Markdown without an outer ```markdown``` fence.
Start the note with YAML frontmatter in this format:
---
tags: [relevant, tags, here]
source: {{URL or unknown}}
date: {{date in YYYY-MM-DD format}}
---

Then continue with this structure:
# Title
## Summary
## Key Points
## Architecture
## Links

In the "Links" section, include every URL that was used to produce the note as a bullet list.

Automatically choose 3 to 5 relevant YAML tags. Prefer tags from the provided "Available tags" list. If none fit, create new meaningful tags that match the content.

If an architecture diagram is useful, add a Mermaid block inside the "Architecture" section.
If the user is only asking a question about the article, the existing context, or a clarification request without asking for a note, answer normally and do not force the response into note format.
Use the existing notes and tags from the vault when relevant. Prefer cross-links such as [[Existing Note Title]] when topics overlap.
"""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
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
    attachment_text_limit: int = Field(default=15000, alias="ATTACHMENT_TEXT_LIMIT")
    telegram_file_max_size: int = Field(default=10 * 1024 * 1024, alias="TELEGRAM_FILE_MAX_SIZE")
    url_extract_limit: int = Field(default=3, alias="URL_EXTRACT_LIMIT")
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
            "Obsidian vault path is not configured. Set OBSIDIAN_VAULT_PATH "
            "or provide both HOST_OBSIDIAN_PATH and CONTAINER_OBSIDIAN_PATH."
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
