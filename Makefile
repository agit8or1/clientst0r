# Clientst0r — convenience targets.
# Run `make help` for the full menu. All Docker targets thin-wrap
# `docker compose` so you can always drop down to the underlying
# command if a target doesn't fit.

COMPOSE ?= docker compose
PROJECT  = clientst0r

.DEFAULT_GOAL := help

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m\n\nTargets:\n"} \
	     /^[a-zA-Z0-9_-]+:.*##/ { printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ─── Docker ──────────────────────────────────────────────────────────

docker-build: ## Build the production image locally
	$(COMPOSE) build app

docker-up: ## Start app + db in detached mode
	$(COMPOSE) up -d
	@echo ""
	@echo "Clientst0r is starting. Tail logs with: make docker-logs"
	@echo "App will be reachable at: http://localhost:$${WEB_PORT:-8000}"

docker-up-full: ## Start app + db + nginx (proxy profile)
	$(COMPOSE) --profile proxy up -d

docker-down: ## Stop containers (volumes preserved)
	$(COMPOSE) down

docker-down-clean: ## Stop containers AND wipe volumes (DESTRUCTIVE)
	@echo "This deletes the database, media files, and uploads."
	@read -p "Type YES to confirm: " ans && [ "$$ans" = "YES" ] || (echo "Aborted." && exit 1)
	$(COMPOSE) down -v

docker-logs: ## Tail logs from the app container
	$(COMPOSE) logs -f app

docker-logs-all: ## Tail logs from every container
	$(COMPOSE) logs -f

docker-shell: ## Open a bash shell inside the running app container
	$(COMPOSE) exec app bash

docker-migrate: ## Run Django migrations inside the running container
	$(COMPOSE) exec app python manage.py migrate

docker-createsuperuser: ## Create a Django superuser interactively
	$(COMPOSE) exec app python manage.py createsuperuser

docker-shell-py: ## Open a Django shell (Python REPL with models loaded)
	$(COMPOSE) exec app python manage.py shell

docker-restart: ## Restart the app container (keeps DB up)
	$(COMPOSE) restart app

# ─── Dev compose ─────────────────────────────────────────────────────

dev-up: ## Start with the dev override (source mount + reload)
	$(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml up

dev-down: ## Stop the dev stack
	$(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml down

# ─── Validation ──────────────────────────────────────────────────────

docker-config: ## Validate compose syntax + resolved env
	$(COMPOSE) config

docker-pull: ## Pull the latest published image (skips local build)
	$(COMPOSE) pull

# ─── Backup / restore ────────────────────────────────────────────────

backup: ## Dump the database to ./backups/clientst0r-YYYYMMDD.sql.gz
	@mkdir -p backups
	@stamp=$$(date +%Y%m%d-%H%M%S); \
	echo "Dumping db to backups/clientst0r-$$stamp.sql.gz..."; \
	$(COMPOSE) exec -T db sh -c \
	  'mariadb-dump -uroot -p"$$MYSQL_ROOT_PASSWORD" --single-transaction --routines --triggers "$$MYSQL_DATABASE"' \
	  | gzip > backups/clientst0r-$$stamp.sql.gz; \
	echo "Done: backups/clientst0r-$$stamp.sql.gz"

restore: ## Restore from a dump: make restore FILE=backups/clientst0r-XXX.sql.gz
	@if [ -z "$(FILE)" ]; then echo "Usage: make restore FILE=backups/clientst0r-YYYYMMDD-HHMMSS.sql.gz"; exit 1; fi
	@echo "Restoring $(FILE) — this overwrites the current database."
	@read -p "Type YES to confirm: " ans && [ "$$ans" = "YES" ] || (echo "Aborted." && exit 1)
	gunzip -c $(FILE) | $(COMPOSE) exec -T db sh -c \
	  'mariadb -uroot -p"$$MYSQL_ROOT_PASSWORD" "$$MYSQL_DATABASE"'

.PHONY: help docker-build docker-up docker-up-full docker-down \
        docker-down-clean docker-logs docker-logs-all docker-shell \
        docker-migrate docker-createsuperuser docker-shell-py \
        docker-restart dev-up dev-down docker-config docker-pull \
        backup restore
