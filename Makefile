.PHONY: help install test chat web clean lint format

help:  ## Show this help message
	@echo "MaSoVa Agent - Available Commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## Install dependencies
	python3 -m pip install -r requirements.txt

install-dev:  ## Install development dependencies
	python3 -m pip install -r requirements.txt
	python3 -m pip install -e ".[dev]"

test:  ## Run all tests
	./scripts/run-tests.sh

chat:  ## Start interactive chat
	./scripts/start-chat.sh

web:  ## Start web UI
	./scripts/start-web.sh

clean:  ## Clean up generated files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf build/ dist/ .pytest_cache/ 2>/dev/null || true

lint:  ## Run linters
	flake8 src/ tests/
	mypy src/

format:  ## Format code with black
	black src/ tests/

setup:  ## First-time setup
	@echo "Setting up MaSoVa Agent..."
	python3 -m venv .venv
	@echo "Activating virtual environment..."
	. .venv/bin/activate && pip install --upgrade pip
	. .venv/bin/activate && pip install -r requirements.txt
	@echo "Creating .env file..."
	cp config/env.example src/masova_agent/.env
	@echo ""
	@echo "✅ Setup complete!"
	@echo "Edit src/masova_agent/.env to add your GOOGLE_API_KEY"
	@echo ""
	@echo "Run 'make web' to start the web interface"
