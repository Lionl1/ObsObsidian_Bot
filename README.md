# Telegram Obsidian Bot

Private Telegram bot for collecting source materials and turning them into Obsidian notes through an OpenAI-compatible LLM endpoint.

The bot accepts regular messages, forwarded messages, links, and files, merges them into a single context, looks up existing notes in your vault, and saves generated Markdown notes back to Obsidian.

## Features

- Private single-user access control
- In-memory conversation history with `/clear`
- Article extraction from URLs via `trafilatura`
- Multiple links per message
- Existing note and tag indexing from the Obsidian vault
- Existing note lookup with commands like `read note [My Note]`
- Attachment parsing for `txt`, `md`, `json`, `yaml`, `xml`, `csv`, `html`, and `docx`
- Metadata-only handling for unsupported binary attachments
- Automatic note save or update in the vault
- Local and Docker-based execution

## Project Structure

```text
.
├── backend/
│   ├── bot.py
│   ├── config.py
│   ├── main.py
│   ├── services.py
│   ├── tests/
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── uv.lock
├── docker-compose.yml
├── Makefile
├── .env.example
└── LICENSE
```

## Requirements

- Python 3.11+
- `uv`
- Telegram bot token
- OpenAI-compatible API endpoint
- Obsidian vault path

## Quick Start

### 1. Create the environment file

```bash
cp .env.example .env
```

Fill in at least:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_USER_ID`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `OBSIDIAN_VAULT_PATH`

### 2. Run locally

Typical local LLM configuration:

```env
OPENAI_BASE_URL=http://127.0.0.1:8000/v1
```

Commands:

```bash
make sync
make run
```

Development mode:

```bash
make dev
```

### 3. Run with Docker

Typical Docker configuration:

```env
OPENAI_BASE_URL=http://host.docker.internal:8000/v1
HOST_OBSIDIAN_PATH=/Users/<user>/Documents/ObsidianVault/Inbox
CONTAINER_OBSIDIAN_PATH=/app/vault
UID=501
GID=20
```

Important:

- `HOST_OBSIDIAN_PATH` must point to a real host directory.
- On macOS, the path must be shared in Docker Desktop file sharing settings.

Commands:

```bash
make docker-config
make docker-build
make docker-up
make docker-logs
```

Stop the stack:

```bash
make docker-down
```

## Environment Variables

| Variable | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_USER_ID` | Owner user ID, the bot is private |
| `OPENAI_API_KEY` | API key for an OpenAI-compatible endpoint |
| `OPENAI_BASE_URL` | Base URL for the LLM API |
| `OPENAI_MODEL` | Model name |
| `OBSIDIAN_VAULT_PATH` | Vault path for local runs |
| `HOST_OBSIDIAN_PATH` | Host vault path for Docker |
| `CONTAINER_OBSIDIAN_PATH` | Vault path inside the container |
| `HISTORY_LIMIT` | Number of history messages kept in memory |
| `ARTICLE_TEXT_LIMIT` | Maximum extracted article size |
| `ATTACHMENT_TEXT_LIMIT` | Maximum extracted attachment size |
| `TELEGRAM_FILE_MAX_SIZE` | Maximum downloadable Telegram file size in bytes |
| `URL_EXTRACT_LIMIT` | Maximum number of URLs processed from one message |
| `OBSIDIAN_PROMPT_NOTES_LIMIT` | Maximum number of indexed notes included in the prompt |
| `OBSIDIAN_NOTE_CONTENT_LIMIT` | Maximum content length when loading an existing note |

## Supported Inputs

- Plain text requests
- One or more links in a single message
- Forwarded messages with text or captions
- Existing note lookup requests such as `read note [Architecture]`
- Documents attached to messages
- Mixed forwarded posts containing text, links, and files

If an attachment format is not supported for text extraction, the bot passes only attachment metadata to the model.

## Development Notes

- Runtime code lives only in `backend/`.
- The repository intentionally keeps vault data and local virtual environments out of version control.
- Conversation memory is process-local and is reset after restart.
- If the model returns a valid Markdown note with frontmatter and a top-level heading, the bot saves it automatically.

## Useful Commands

```bash
make sync
make run
make dev
make docker-config
make docker-build
make docker-up
make docker-down
make docker-logs
```
