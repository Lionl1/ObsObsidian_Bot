# Telegram Obsidian Bot

Приватный Telegram-бот для сбора материалов и генерации заметок в Obsidian через локальную LLM с OpenAI-совместимым API.

Бот умеет принимать обычные сообщения, пересланные сообщения, ссылки и файлы, собирать их в единый контекст, учитывать уже существующие заметки в vault и сохранять итоговый результат обратно в Obsidian.

## Что умеет

- Поддерживает conversational memory для одного пользователя
- Очищает историю по команде `/clear`
- Извлекает текст статей по URL через `trafilatura`
- Обрабатывает несколько ссылок в одном сообщении
- Читает существующие `.md`-заметки из Obsidian vault
- Передает в LLM список существующих заметок и тегов
- Поддерживает запросы вида `Прочитай заметку [Название]`
- Использует текст, подпись, ссылки и файлы из пересланного сообщения
- Извлекает текст из `txt`, `md`, `json`, `yaml`, `xml`, `csv`, `html`, `docx`
- Для нетекстовых вложений добавляет в контекст метаданные
- Автоматически сохраняет или обновляет markdown-заметки в vault
- Работает локально и в Docker

## Как это работает

1. Пользователь отправляет сообщение, ссылку, пересланный материал или файл.
2. Бот извлекает текст из доступных источников.
3. Перед генерацией бот индексирует Obsidian vault и собирает список заметок и тегов.
4. В LLM передается история диалога, системный промпт, материалы пользователя и контекст существующих заметок.
5. Если модель возвращает markdown-заметку, бот сохраняет ее в `OBSIDIAN_VAULT_PATH`.

## Стек

- Python 3.11+
- `uv`
- `aiogram 3.x`
- `trafilatura`
- `openai`
- `pydantic-settings`

## Структура проекта

```text
.
├── bot.py
├── config.py
├── main.py
├── services.py
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── pyproject.toml
├── uv.lock
└── .env.example
```

## Быстрый старт

### 1. Подготовка `.env`

```bash
cp .env.example .env
```

Минимально нужно заполнить:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_USER_ID`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `OBSIDIAN_VAULT_PATH`

### 2. Локальный запуск

Для локального сервера LLM обычно используют:

```env
OPENAI_BASE_URL=http://127.0.0.1:8000/v1
```

Запуск:

```bash
make sync
make run
```

Dev-режим:

```bash
make dev
```

### 3. Запуск в Docker

Для Docker обычно нужны такие значения:

```env
OPENAI_BASE_URL=http://host.docker.internal:8000/v1
HOST_OBSIDIAN_PATH=/Users/<user>/Documents/ObsidianVault/Inbox
CONTAINER_OBSIDIAN_PATH=/app/vault
UID=501
GID=20
```

Важно:

- `HOST_OBSIDIAN_PATH` должен быть реальным путем на хосте, а не placeholder из `.env.example`
- на macOS этот путь должен быть доступен в `Docker Desktop -> Settings -> Resources -> File Sharing`

Запуск:

```bash
make docker-config
make docker-build
make docker-up
make docker-logs
```

Остановка:

```bash
make docker-down
```

## Переменные окружения

| Переменная | Назначение |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | токен Telegram-бота |
| `TELEGRAM_USER_ID` | Telegram user id владельца, бот приватный |
| `OPENAI_API_KEY` | ключ для OpenAI-совместимого API |
| `OPENAI_BASE_URL` | URL локального LLM API |
| `OPENAI_MODEL` | имя модели |
| `OBSIDIAN_VAULT_PATH` | путь к vault для локального запуска |
| `HOST_OBSIDIAN_PATH` | путь к vault на хосте для Docker |
| `CONTAINER_OBSIDIAN_PATH` | путь к vault внутри контейнера |
| `HISTORY_LIMIT` | длина истории диалога |
| `ARTICLE_TEXT_LIMIT` | лимит текста статьи |
| `ATTACHMENT_TEXT_LIMIT` | лимит текста вложения |
| `TELEGRAM_FILE_MAX_SIZE` | максимальный размер загружаемого файла |
| `URL_EXTRACT_LIMIT` | сколько ссылок из одного сообщения обрабатывать |
| `OBSIDIAN_PROMPT_NOTES_LIMIT` | сколько заметок из vault передавать в промпт |
| `OBSIDIAN_NOTE_CONTENT_LIMIT` | лимит текста при чтении существующей заметки |

## Команды

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

## Поддерживаемые входные данные

Бот уже сейчас корректно работает с такими сценариями:

- обычный текстовый запрос
- одна или несколько ссылок в одном сообщении
- пересланное сообщение с текстом или подписью
- запрос `Прочитай заметку [Название]`
- документ, приложенный к сообщению
- пересланный пост с текстом, ссылками и файлом одновременно

Если вложение нетекстовое, бот не пытается выдумывать содержимое, а передает в LLM только метаданные о файле.

## Полезные замечания

- `.env` не должен попадать в git
- `.env.example` содержит только шаблонные значения
- бот хранит память диалога в памяти процесса, без внешней БД
- при рестарте контейнера или процесса история сообщений сбрасывается
- если LLM возвращает markdown с frontmatter и заголовком `#`, заметка сохраняется автоматически

## Troubleshooting

### Docker: `mounts denied`

Причина почти всегда одна из двух:

- в `.env` остался placeholder в `HOST_OBSIDIAN_PATH`
- путь не добавлен в `Docker Desktop -> Settings -> Resources -> File Sharing`

### Docker: контейнер стартует, но сразу падает

Проверьте логи:

```bash
make docker-logs
```

### Локально не открывается LLM endpoint

Проверьте, что:

- сервер LLM действительно слушает `OPENAI_BASE_URL`
- локально используется `127.0.0.1`, а в Docker `host.docker.internal`

## Публикация в Git

Перед выкладкой репозитория достаточно проверить:

- заполненный `.env` не добавлен в индекс
- пути в `.env.example` остались шаблонными
- `.venv`, `__pycache__`, временные файлы и локальные данные не попали в git
- при необходимости добавлены `LICENSE` и ссылка на удаленный репозиторий
