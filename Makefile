.PHONY: install dev dev-backend dev-frontend test lint gen gen-golden

install:
	pip install -e "./backend[dev]"
	npm install --prefix frontend

dev-backend:
	cd backend && uvicorn lineage.api.app:app --reload

dev-frontend:
	npm run dev --prefix frontend

dev:
	$(MAKE) -j2 dev-backend dev-frontend

test:
	cd backend && pytest -q

lint:
	cd backend && ruff check .

gen:
	cd backend && python -m lineage.datagen.cli

gen-golden:
	@echo "Golden files are frozen. Regenerating requires explicit approval and a diff review before commit."
	cd backend && python -m lineage.datagen.cli --golden
