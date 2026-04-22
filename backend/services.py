from __future__ import annotations

import asyncio
import csv
import difflib
import io
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import TYPE_CHECKING

import trafilatura
from openai import AsyncOpenAI

if TYPE_CHECKING:
    from config import Settings


HistoryEntry = dict[str, str]

URL_PATTERN = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*", re.DOTALL)
HEADING_PATTERN = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
BRACKET_NOTE_READ_PATTERN = re.compile(
    r"(?:read\s+note|прочитай\s+заметку)\s+\[([^\]]+)\]",
    re.IGNORECASE,
)
PLAIN_NOTE_READ_PATTERN = re.compile(
    r"^\s*(?:read\s+note|прочитай\s+заметку)\s+(.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
NOTE_BLOCK_OPEN_PATTERN = re.compile(r"^\s*```(?:markdown|md)?\s*$", re.IGNORECASE)
NOTE_BLOCK_CLOSE_PATTERN = re.compile(r"^\s*```\s*$")
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
SUPPORTED_TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".csv",
    ".html",
    ".htm",
    ".docx",
}
WORD_NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


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
    urls = extract_urls(text)[: settings.url_extract_limit]
    if not urls:
        return text.strip(), None

    primary_url = urls[0]
    article_text = await extract_article_text(primary_url)
    if len(article_text) > settings.article_text_limit:
        article_text = (
            article_text[: settings.article_text_limit].rstrip()
            + "\n\n[The article text was truncated because of the context limit.]"
        )

    all_urls_text = "\n".join(f"- {u}" for u in urls)
    prompt = (
        f"The user sent these URLs:\n{all_urls_text}\n\n"
        f"Primary article content ({primary_url}):\n\n{article_text}\n\nAnalyze it and create a note."
    )

    additional_context = URL_PATTERN.sub("", text).strip()
    if additional_context:
        prompt += f"\n\nAdditional user comment: {additional_context}"

    return prompt, primary_url


async def extract_article_text(url: str) -> str:
    downloaded = await asyncio.to_thread(trafilatura.fetch_url, url)
    if not downloaded:
        raise ArticleExtractionError("Failed to download the page from the provided URL.")

    extracted = await asyncio.to_thread(
        trafilatura.extract,
        downloaded,
        include_links=False,
        include_images=False,
        favor_precision=True,
    )
    if not extracted:
        raise ArticleExtractionError("Failed to extract article text.")

    cleaned = extracted.strip()
    if not cleaned:
        raise ArticleExtractionError("The extracted article text is empty.")

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
            max_tokens=4000,
        )
    except Exception as exc:  # noqa: BLE001
        raise LLMServiceError(f"Error while calling the LLM: {exc}") from exc

    content = response.choices[0].message.content if response.choices else None
    if not content:
        raise LLMServiceError("The LLM returned an empty response.")

    return content.strip()


def extract_note_from_response(response_text: str) -> NotePayload | None:
    note_content = _extract_note_content(response_text)
    if note_content is None:
        return None

    title_match = HEADING_PATTERN.search(note_content)
    if not title_match:
        return None

    title = title_match.group(1).strip()
    if not title:
        return None

    return NotePayload(title=title, content=note_content.strip() + "\n")


def _extract_note_content(response_text: str) -> str | None:
    raw = response_text.strip()
    if not raw:
        return None

    fenced_candidate = _extract_fenced_note_candidate(raw)
    if fenced_candidate is not None:
        return fenced_candidate

    if FRONTMATTER_PATTERN.match(raw) or HEADING_PATTERN.search(raw):
        return raw

    frontmatter_match = FRONTMATTER_PATTERN.search(raw)
    if frontmatter_match:
        return raw[frontmatter_match.start() :].strip()

    heading_match = HEADING_PATTERN.search(raw)
    if heading_match:
        return raw[heading_match.start() :].strip()

    return None


def _extract_fenced_note_candidate(text: str) -> str | None:
    lines = text.splitlines()
    openers = [index for index, line in enumerate(lines) if NOTE_BLOCK_OPEN_PATTERN.match(line)]
    closers = [index for index, line in enumerate(lines) if NOTE_BLOCK_CLOSE_PATTERN.match(line)]
    candidates: list[str] = []

    for opener_index in openers:
        for closer_index in reversed(closers):
            if closer_index <= opener_index:
                continue
            inner = "\n".join(lines[opener_index + 1 : closer_index]).strip()
            if FRONTMATTER_PATTERN.match(inner) or HEADING_PATTERN.search(inner):
                candidates.append(inner)
                break

    if not candidates:
        return None

    return max(candidates, key=len)


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


def build_attachment_prompt(
    filename: str,
    mime_type: str | None,
    text: str | None,
    settings: Settings,
) -> str:
    metadata = [f"Filename: {filename}"]
    if mime_type:
        metadata.append(f"MIME type: {mime_type}")

    if text:
        trimmed = text.strip()
        if len(trimmed) > settings.attachment_text_limit:
            trimmed = (
                trimmed[: settings.attachment_text_limit].rstrip()
                + "\n\n[The attachment text was truncated because of the context limit.]"
            )
        metadata_text = "\n".join(metadata)
        return f"{metadata_text}\n\nExtracted attachment text:\n\n{trimmed}"

    metadata_text = "\n".join(metadata)
    return (
        f"{metadata_text}\n\n"
        "The file content was not extracted automatically. Use only the attachment metadata."
    )


def extract_attachment_text(
    filename: str | None,
    content: bytes,
    mime_type: str | None = None,
) -> str | None:
    suffix = Path(filename or "").suffix.casefold()
    if suffix not in SUPPORTED_TEXT_SUFFIXES:
        return None

    if suffix == ".docx":
        return _extract_docx_text(content)

    decoded = _decode_attachment_bytes(content)
    if not decoded:
        return None

    if suffix in {".html", ".htm"}:
        extracted = trafilatura.extract(
            decoded,
            include_links=False,
            include_images=False,
            favor_precision=True,
        )
        if extracted:
            return extracted.strip()
        return _strip_html(decoded)

    if suffix == ".csv":
        return _render_csv(decoded)

    if suffix == ".json":
        return _pretty_json(decoded)

    if suffix == ".xml":
        return _extract_xml_text(decoded)

    return decoded.strip()


def _decode_attachment_bytes(content: bytes) -> str | None:
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _extract_docx_text(content: bytes) -> str | None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            document_xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile):
        return None

    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError:
        return None

    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", WORD_NAMESPACE):
        parts = [node.text for node in paragraph.findall(".//w:t", WORD_NAMESPACE) if node.text]
        if parts:
            paragraphs.append("".join(parts))

    return "\n".join(paragraphs).strip() or None


def _render_csv(decoded: str) -> str:
    reader = csv.reader(io.StringIO(decoded))
    rows = ["\t".join(cell.strip() for cell in row) for row in reader]
    return "\n".join(row for row in rows if row).strip()


def _pretty_json(decoded: str) -> str:
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError:
        return decoded.strip()
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _extract_xml_text(decoded: str) -> str:
    try:
        root = ET.fromstring(decoded)
    except ET.ParseError:
        return decoded.strip()

    parts = [fragment.strip() for fragment in root.itertext() if fragment and fragment.strip()]
    return "\n".join(parts).strip()


def _strip_html(decoded: str) -> str:
    text = HTML_TAG_PATTERN.sub(" ", decoded)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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
            "There are no known Obsidian notes in the vault yet. "
            "If you create a new note, choose sensible tags and structure."
        )

    limited_notes = vault_index.notes[: settings.obsidian_prompt_notes_limit]
    lines = [
        "Below is the list of existing notes in the vault. "
        "Use these tags where relevant and prefer cross-links "
        "[[Existing Note Title]] when topics overlap.",
        "Existing notes:",
    ]

    for note in limited_notes:
        tags_text = ", ".join(note.tags) if note.tags else "no tags"
        heading_text = f"; heading: {note.heading}" if note.heading and note.heading != note.link_name else ""
        lines.append(
            f"- [[{note.link_name}]]; file: {note.relative_path}; tags: {tags_text}{heading_text}"
        )

    if vault_index.tags:
        lines.append(f"Available tags: {', '.join(vault_index.tags)}")

    if len(vault_index.notes) > len(limited_notes):
        omitted = len(vault_index.notes) - len(limited_notes)
        lines.append(f"Additional notes hidden because of the prompt limit: {omitted}.")

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
            + "\n\n[The note content was truncated because of the context limit.]"
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
                f"Could not find note '{note_query}'. Closest matches: {suggestions_text}."
            )
        raise NoteLookupError(f"Could not find note '{note_query}' in the Obsidian vault.")

    note_content = await read_note_content(note, settings)
    tags_text = ", ".join(note.tags) if note.tags else "none"
    prompt = (
        f"The user asked to read the existing note '{note.link_name}'.\n"
        f"File: {note.relative_path}\n"
        f"Tags: {tags_text}\n\n"
        f"Note content:\n\n{note_content}\n\n"
        f"Original user request: {text}"
    )
    return prompt, note
