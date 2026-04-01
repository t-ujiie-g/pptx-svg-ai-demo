.PHONY: dev build up down logs clean install-backend install-frontend lint test

# Development
dev:
	docker compose up --build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

build:
	docker compose build

# Clean
clean:
	docker compose down -v --rmi local
	rm -rf backend/.venv
	rm -rf frontend/node_modules
	rm -rf frontend/dist

# Local development (without Docker)
install-backend:
	cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e .
	npm install -g pptxgenjs react react-dom react-icons sharp

install-frontend:
	cd frontend && npm install

run-backend:
	cd backend && . .venv/bin/activate && uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

run-frontend:
	cd frontend && npm run dev

# Linting and Testing
lint:
	cd backend && . .venv/bin/activate && ruff check src/
	cd frontend && npm run lint

test:
	cd backend && . .venv/bin/activate && pytest
	cd frontend && npm run test

# Health check
health:
	curl -s http://localhost:8000/health | jq .
