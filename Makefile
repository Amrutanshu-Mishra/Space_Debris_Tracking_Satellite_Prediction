.PHONY: up down demo demo-storage demo-offline logs test lint seed fmt clean

up: ## Build and start the demo stack (api + web), logs attached
	docker compose up --build

down: ## Stop the stack
	docker compose down

demo: ## Build, start detached, wait for the API health check, print the URL
	docker compose up --build --detach --wait
	@echo ""
	@echo "  PRAHARI console : http://localhost:8080"
	@echo "  API health      : http://localhost:8000/api/v1/health"
	@echo ""

demo-storage: ## Build, start with Postgres + Redis (opt-in persistence), run the loader
	docker compose -f docker-compose.yml -f docker-compose.storage.yml \
		--profile storage up --build --detach --wait
	@echo ""
	@echo "  PRAHARI console : http://localhost:8080  (API reading from Postgres)"
	@echo "  API health      : http://localhost:8000/api/v1/health"
	@echo ""

demo-offline: ## Prove the running stack needs no network (compose net set internal)
	docker compose build
	docker compose -f docker-compose.yml -f docker-compose.offline.yml up --detach --wait
	@echo ""
	@echo "  stack healthy with the compose network cut off from the internet"
	@echo "  PRAHARI console : http://localhost:8080"
	@echo ""

logs: ## Tail logs from all services
	docker compose logs -f

test: ## Run all test suites (orbital + api + worker), host-side, no docker required
	cd services/orbital && python -m pytest -q
	cd services/api && python -m pytest -q
	cd services/worker && python -m pytest -q
	cd web && npm run test -- --run

lint: ## Lint Python and TypeScript
	cd services/orbital && ruff check . && mypy prahari_orbital
	cd services/api && ruff check . && mypy prahari_api
	cd services/worker && ruff check . && mypy prahari_worker
	cd web && npm run lint && npm run typecheck

seed: ## Regenerate Pydantic + TypeScript models from contracts/schemas
	cd services/orbital && python -m datamodel_code_generator \
		--input ../../contracts/schemas \
		--input-file-type jsonschema \
		--output prahari_orbital/models.py \
		--target-python-version 3.11 \
		--use-schema-description \
		--field-constraints
	cd web && npx json-schema-to-typescript ../contracts/schemas/object.schema.json -o src/api/types/object.d.ts
	cd web && npx json-schema-to-typescript ../contracts/schemas/conjunction.schema.json -o src/api/types/conjunction.d.ts
	cd web && npx json-schema-to-typescript ../contracts/schemas/catalog_status.schema.json -o src/api/types/catalog_status.d.ts

fmt: ## Format Python and TypeScript
	cd services/orbital && ruff format .
	cd services/api && ruff format .
	cd services/worker && ruff format .
	cd web && npm run format

clean: ## Remove containers, volumes, and caches
	docker compose down -v
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
