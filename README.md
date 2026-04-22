# Telegram Obsidian Bot

Telegram bot for turning messages, links, and files into Obsidian notes through an OpenAI-compatible API.

## Features

- Private single-user access
- URL article extraction
- Existing note lookup from the Obsidian vault
- Attachment parsing for `txt`, `md`, `json`, `yaml`, `xml`, `csv`, `html`, and `docx`
- Automatic Markdown note save/update in the vault
- Local and Docker-based run modes

## Requirements

- Python 3.11+
- `uv`
- Telegram bot token
- OpenAI-compatible API endpoint
- Obsidian vault path

## Setup

Create the environment file:

```bash
cp .env.example .env
```

Required variables:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_USER_ID`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `OBSIDIAN_VAULT_PATH`

Example local API endpoint:

```env
OPENAI_BASE_URL=http://127.0.0.1:8000/v1
```

## Run Locally

```bash
make sync
make run
```

Development mode:

```bash
make dev
```

## Run with Docker

Example Docker variables:

```env
OPENAI_BASE_URL=http://host.docker.internal:8000/v1
HOST_OBSIDIAN_PATH=/Users/<user>/Documents/ObsidianVault/Inbox
CONTAINER_OBSIDIAN_PATH=/app/vault
UID=501
GID=20
```

Build and start:

```bash
make docker-config
make docker-build
make docker-up
make docker-logs
```

Stop:

```bash
make docker-down
```

## Environment Variables

| Variable | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_USER_ID` | Allowed Telegram user ID |
| `OPENAI_API_KEY` | API key for the LLM endpoint |
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
