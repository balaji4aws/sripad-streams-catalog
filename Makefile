# Development commands. `make check` is what CI runs, so a green local run
# means a green CI run. Nothing here needs a virtualenv except `lint`, which
# needs ruff (pip install -r requirements-dev.txt).

.DEFAULT_GOAL := help
.PHONY: help check lint test test-py test-js catalog verify-catalog serve

help: ## Show the available commands
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-16s %s\n", $$1, $$2}'

check: lint test verify-catalog ## Everything CI runs

lint: ## Lint the Python sources
	ruff check .

test: test-py test-js ## Run every test

test-py: ## Python tests (standard library unittest, nothing to install)
	python3 -m unittest discover -v

test-js: ## JavaScript tests (Node's built-in runner, nothing to install)
	node --test "tests/**/*.test.mjs"

catalog: ## Rebuild the catalog from the saved playlist (offline; no network)
	python3 src/categorize.py
	python3 src/build_sequences.py

verify-catalog: catalog ## Fail if the committed output files are stale
	@git diff --quiet --exit-code -- output/ \
		|| { echo "error: output/ is stale - run 'make catalog' and commit the result."; \
		     git --no-pager diff --stat -- output/; exit 1; }
	@echo "output/ matches what the current code produces."

serve: ## Serve the folder so search.html can load its data
	@echo "Open http://localhost:8000/search.html"
	python3 -m http.server 8000
