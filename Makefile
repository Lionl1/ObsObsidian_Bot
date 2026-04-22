ENV_FILE ?= .env

check-env:
	@test -f $(ENV_FILE) || (echo "Missing $(ENV_FILE). Copy .env.example to .env and fill it." && exit 1)

check-docker-env: check-env
	@HOST_PATH=$$(grep '^HOST_OBSIDIAN_PATH=' $(ENV_FILE) | cut -d= -f2-); \
	if [ -z "$$HOST_PATH" ]; then \
		echo "HOST_OBSIDIAN_PATH is empty in $(ENV_FILE)."; \
		exit 1; \
	fi; \
	if [ "$$HOST_PATH" = "/absolute/path/to/your/ObsidianVault/Inbox" ]; then \
		echo "HOST_OBSIDIAN_PATH still uses the placeholder value in $(ENV_FILE)."; \
		echo "Set it to a real host path, for example /Users/<user>/Documents/ObsidianVault/Inbox."; \
		exit 1; \
	fi; \
	if [ ! -d "$$HOST_PATH" ]; then \
		echo "HOST_OBSIDIAN_PATH does not exist on host: $$HOST_PATH"; \
		exit 1; \
	fi

sync:
	cd backend && uv sync

run:
	cd backend && uv run python main.py

dev:
	cd backend && uv run python -X dev main.py

docker-config: check-docker-env
	docker compose --env-file $(ENV_FILE) config

docker-build: check-docker-env
	docker compose --env-file $(ENV_FILE) build

docker-up: check-docker-env
	docker compose --env-file $(ENV_FILE) up -d

docker-down:
	docker compose --env-file $(ENV_FILE) down

docker-logs: check-env
	docker compose --env-file $(ENV_FILE) logs -f bot
