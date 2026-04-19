from __future__ import annotations

import asyncio
import difflib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import trafilatura
from openai import AsyncOpenAI

if TYPE_CHECKING:
    from config import Settings


HistoryEntry = dict[str, str]

URL_PATTERN = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
CODE_BLOCK_PATTERN = re.compile(r"```(?:markdown|md)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*", re.DOTALL)
HEADING_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
BRACKET_NOTE_READ_PATTERN = re.compile(r"прочитай\s+заметку\s+\[([^\]]+)\]", re.IGNORECASE)
PLAIN_NOTE_READ_PATTERN = re.compile(r"^\s*прочитай\s+заметку\s+(.+?)\s*$", re.IGNORECASE | re.DOTALL)


class ArticleExtractionError(Exception):
    """Raised when an article cannot be downloaded or parsed."""


class LLMServiceError(Exception):
    """Raised when the LLM request fails or returns an empty response."""


class NoteLookupError(Exception):
    """Raised when an existing note cannot be located in the vault."""


@dataclass(slots=True)
class NotePayload:
    title: str
    content: str


@dataclass(slots=True)
class SaveResult:
    filename: str
    title: str
    updated: bool


@dataclass(slots=True)
class VaultNote:
    link_name: str
    filename: str
    relative_path: str
    path: Path
    heading: str | None
    tags: list[str]


@dataclass(slots=True)
class VaultIndex:
    notes: list[VaultNote]
    tags: list[str]


def extract_urls(text: str) -> list[str]:
    matches = URL_PATTERN.findall(text)
    return [match.rstrip(".,!?)]}>") for match in matches]


def build_system_prompt(settings: Settings, vault_index: VaultIndex | None = None) -> str:
    today = datetime.now().date().isoformat()
    prompt = settings.system_prompt_template.format(today=today)
    notes_section = render_vault_index_for_prompt(vault_index, settings)
    return f"{prompt}\n\n{notes_section}"


def build_openai_client(settings: Settings) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=settings.openai_timeout_seconds,
    )


async def prepare_user_message(text: str, settings: Settings) -> tuple[str, str | None]:
    urls = extract_urls(text)
    if not urls:
        return text.strip(), None

    primary_url = urls[0]
    article_text = await extract_article_text(primary_url)
    if len(article_text) > settings.article_text_limit:
        article_text = (
            article_text[: settings.article_text_limit].rstrip()
            + "\n\n[Текст статьи был обрезан из-за ограничения контекста.]"
        )

    all_urls_text = "\n".join(f"- {u}" for u in urls)
    prompt = (
        f"Пользователь прислал ссылки:\n{all_urls_text}\n\n"
        f"Содержимое основной статьи ({primary_url}):\n\n{article_text}\n\nПроанализируй её и сделай заметку."
    )

    additional_context = URL_PATTERN.sub("", text).strip()
    if additional_context:
        prompt += f"\n\nДополнительный комментарий пользователя: {additional_context}"

    return prompt, primary_url


async def extract_article_text(url: str) -> str:
    downloaded = await asyncio.to_thread(trafilatura.fetch_url, url)
    if not downloaded:
        raise ArticleExtractionError("Не удалось скачать страницу по указанному URL.")

    extracted = await asyncio.to_thread(
        trafilatura.extract,
        downloaded,
        include_links=False,
        include_images=False,
        favor_precision=True,
    )
    if not extracted:
        raise ArticleExtractionError("Не удалось извлечь текст статьи.")

    cleaned = extracted.strip()
    if not cleaned:
        raise ArticleExtractionError("Текст статьи пустой после обработки.")

    return cleaned


async def generate_llm_reply(
    history: list[HistoryEntry],
    client: AsyncOpenAI,
    settings: Settings,
    vault_index: VaultIndex | None = None,
) -> str:
    messages: list[HistoryEntry] = [
        {"role": "system", "content": build_system_prompt(settings, vault_index)},
        *history[-settings.history_limit :],
    ]

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            temperature=0.2,
        )
    except Exception as exc:  # noqa: BLE001
        raise LLMServiceError(f"Ошибка при обращении к LLM: {exc}") from exc

    content = response.choices[0].message.content if response.choices else None
    if not content:
        raise LLMServiceError("LLM вернула пустой ответ.")

    return content.strip()


def extract_note_from_response(response_text: str) -> NotePayload | None:
    candidates: list[str] = []
    for match in CODE_BLOCK_PATTERN.finditer(response_text):
        candidate = match.group(1).strip()
        if candidate.startswith("---") or HEADING_PATTERN.search(candidate):
            candidates.append(candidate)

    if candidates:
        note_content = candidates[0]
    else:
        raw = response_text.strip()
        if FRONTMATTER_PATTERN.match(raw):
            note_content = raw
        else:
            return None

    title_match = HEADING_PATTERN.search(note_content)
    if not title_match:
        return None

    title = title_match.group(1).strip()
    if not title:
        return None

    return NotePayload(title=title, content=note_content.strip() + "\n")


def make_safe_filename(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).strip()
    normalized = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "", normalized)
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = normalized.strip("._")

    if not normalized:
        normalized = f"note_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    return f"{normalized}.md"


async def save_note(note: NotePayload, vault_path: Path) -> SaveResult:
    def _write_note() -> SaveResult:
        vault_path.mkdir(parents=True, exist_ok=True)
        filename = make_safe_filename(note.title)
        target_path = vault_path / filename
        updated = target_path.exists()
        target_path.write_text(note.content, encoding="utf-8")
        return SaveResult(filename=filename, title=note.title, updated=updated)

    return await asyncio.to_thread(_write_note)


def extract_frontmatter(text: str) -> str | None:
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return None
    return match.group(1).strip()


def parse_tags_from_frontmatter(frontmatter: str | None) -> list[str]:
    if not frontmatter:
        return []

    lines = frontmatter.splitlines()
    tags: list[str] = []

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("tags:"):
            continue

        value = stripped.partition(":")[2].strip()
        if value.startswith("[") and value.endswith("]"):
            return _split_inline_tags(value[1:-1])
        if value:
            return _split_inline_tags(value)

        cursor = index + 1
        while cursor < len(lines):
            nested_line = lines[cursor]
            if not nested_line.startswith((" ", "\t")):
                break
            nested = nested_line.strip()
            if nested.startswith("- "):
                tag = nested[2:].strip().strip("'\"")
                if tag:
                    tags.append(tag)
            cursor += 1
        break

    return list(dict.fromkeys(tags))


def _split_inline_tags(raw_tags: str) -> list[str]:
    cleaned = raw_tags.strip()
    if not cleaned:
        return []

    parts = [part.strip().strip("'\"") for part in cleaned.split(",")]
    return [part for part in dict.fromkeys(parts) if part]


def extract_heading(text: str) -> str | None:
    match = HEADING_PATTERN.search(text)
    if not match:
        return None
    title = match.group(1).strip()
    return title or None


def normalize_note_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    normalized = normalized.removesuffix(".md")
    normalized = normalized.replace("_", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


async def scan_obsidian_vault(vault_path: Path) -> VaultIndex:
    return await asyncio.to_thread(_scan_obsidian_vault, vault_path)


def _scan_obsidian_vault(vault_path: Path) -> VaultIndex:
    if not vault_path.exists():
        return VaultIndex(notes=[], tags=[])

    notes: list[VaultNote] = []
    tag_set: set[str] = set()

    for file_path in sorted(vault_path.rglob("*.md"), key=lambda path: str(path).casefold()):
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = file_path.read_text(encoding="utf-8", errors="ignore")

        tags = parse_tags_from_frontmatter(extract_frontmatter(content))
        heading = extract_heading(content)
        relative_path = file_path.relative_to(vault_path).as_posix()
        notes.append(
            VaultNote(
                link_name=file_path.stem,
                filename=file_path.name,
                relative_path=relative_path,
                path=file_path,
                heading=heading,
                tags=tags,
            )
        )
        tag_set.update(tags)

    return VaultIndex(notes=notes, tags=sorted(tag_set, key=str.casefold))


def render_vault_index_for_prompt(vault_index: VaultIndex | None, settings: Settings) -> str:
    if vault_index is None or not vault_index.notes:
        return (
            "В хранилище Obsidian пока нет известных заметок. "
            "Если создаешь новую заметку, подбери разумные теги и структуру."
        )

    limited_notes = vault_index.notes[: settings.obsidian_prompt_notes_limit]
    lines = [
        "Ниже список существующих заметок в хранилище. "
        "Опирайся на эти существующие теги и старайся делать перекрестные ссылки "
        "[[Название существующей заметки]] в генерируемом тексте, если темы пересекаются.",
        "Существующие заметки:",
    ]

    for note in limited_notes:
        tags_text = ", ".join(note.tags) if note.tags else "без тегов"
        heading_text = f"; heading: {note.heading}" if note.heading and note.heading != note.link_name else ""
        lines.append(
            f"- [[{note.link_name}]]; file: {note.relative_path}; tags: {tags_text}{heading_text}"
        )

    if vault_index.tags:
        lines.append(f"Доступные теги: {', '.join(vault_index.tags)}")

    if len(vault_index.notes) > len(limited_notes):
        omitted = len(vault_index.notes) - len(limited_notes)
        lines.append(f"Дополнительно скрыто заметок из-за лимита промпта: {omitted}.")

    return "\n".join(lines)


def extract_note_read_query(text: str) -> str | None:
    bracket_match = BRACKET_NOTE_READ_PATTERN.search(text)
    if bracket_match:
        return bracket_match.group(1).strip()

    plain_match = PLAIN_NOTE_READ_PATTERN.match(text)
    if plain_match:
        return plain_match.group(1).strip()

    return None


def find_note(query: str, vault_index: VaultIndex) -> VaultNote | None:
    normalized_query = normalize_note_name(query)
    if not normalized_query:
        return None

    for note in vault_index.notes:
        candidates = {normalize_note_name(note.link_name)}
        if note.heading:
            candidates.add(normalize_note_name(note.heading))
        if normalized_query in candidates:
            return note

    for note in vault_index.notes:
        if normalized_query in normalize_note_name(note.link_name):
            return note
        if note.heading and normalized_query in normalize_note_name(note.heading):
            return note

    return None


def suggest_notes(query: str, vault_index: VaultIndex, limit: int = 3) -> list[str]:
    choices = [note.link_name for note in vault_index.notes]
    return difflib.get_close_matches(query, choices, n=limit, cutoff=0.4)


async def read_note_content(note: VaultNote, settings: Settings) -> str:
    def _read() -> str:
        try:
            content = note.path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = note.path.read_text(encoding="utf-8", errors="ignore")
        return content

    content = await asyncio.to_thread(_read)
    if len(content) > settings.obsidian_note_content_limit:
        content = (
            content[: settings.obsidian_note_content_limit].rstrip()
            + "\n\n[Содержимое заметки было обрезано из-за ограничения контекста.]"
        )
    return content


async def prepare_existing_note_context(
    text: str,
    vault_index: VaultIndex,
    settings: Settings,
) -> tuple[str, VaultNote] | None:
    note_query = extract_note_read_query(text)
    if not note_query:
        return None

    note = find_note(note_query, vault_index)
    if note is None:
        suggestions = suggest_notes(note_query, vault_index)
        if suggestions:
            suggestions_text = ", ".join(suggestions)
            raise NoteLookupError(
                f"Не нашел заметку '{note_query}'. Ближайшие варианты: {suggestions_text}."
            )
        raise NoteLookupError(f"Не нашел заметку '{note_query}' в папке Obsidian.")

    note_content = await read_note_content(note, settings)
    tags_text = ", ".join(note.tags) if note.tags else "нет"
    prompt = (
        f"Пользователь попросил прочитать существующую заметку '{note.link_name}'.\n"
        f"Файл: {note.relative_path}\n"
        f"Теги: {tags_text}\n\n"
        f"Содержимое заметки:\n\n{note_content}\n\n"
        f"Исходный запрос пользователя: {text}"
    )
    return prompt, note
