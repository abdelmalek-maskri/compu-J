.PHONY: help setup classify api news web dev docker docker-down test lint

help:
	@echo 'make setup        install Python and dashboard packages, create .env'
	@echo 'make classify     classify every email (uses saved answers when it can)'
	@echo 'make dev          API, headlines every 10 minutes and dashboard, together'
	@echo '                  (Ctrl+C stops all three; open http://localhost:5173)'
	@echo 'make api | news | web   one of those three on its own'
	@echo 'make docker       the same in Docker, on http://localhost:8000'
	@echo 'make docker-down  stop Docker'
	@echo 'make test         all tests'
	@echo 'make lint         all style checks'

setup:
	uv sync
	cd web && npm ci
	@test -f .env || (cp .env.example .env && echo 'created .env: add your keys')

classify:
	uv run python classify.py

api:
	uv run uvicorn api.main:app --reload

news:
	uv run python fetch_news.py --every 10

web:
	cd web && npm run dev

# -j3 runs the three side by side; they never finish, so Ctrl+C is how to stop them
dev:
	$(MAKE) -j3 api news web

docker:
	docker compose up --build

docker-down:
	docker compose down

test:
	uv run pytest
	cd web && npm test

lint:
	uv run ruff check .
	uv run ruff format --check .
	cd web && npm run lint
