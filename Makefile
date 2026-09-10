# Development commands. `make check` is what CI runs, so a green local run
# means a green CI run. The test suites need nothing installed; `lint` and
# `typecheck` need pip install -r requirements-dev.txt, and `test-browser`
# needs Chrome or Chromium.

.DEFAULT_GOAL := help
.PHONY: help check lint typecheck test test-py test-js test-browser catalog verify-catalog serve

help: ## Show the available commands
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-16s %s\n", $$1, $$2}'

check: lint typecheck test verify-catalog ## Everything CI runs

lint: ## Lint the Python sources (needs ruff)
	ruff check .

typecheck: ## Type-check the Python sources (needs mypy)
	mypy

test: test-py test-js ## Run the test suites that need no browser

test-py: ## Python tests (standard library unittest, nothing to install)
	python3 -m unittest discover -v

test-js: ## JavaScript tests (Node's built-in runner, nothing to install)
	# The shell expands the paths rather than handing --test a glob pattern,
	# which it only accepts from Node 22 onwards.
	node --test tests/*.test.mjs

test-browser: ## Load search.html in a real browser and check it (needs Chrome)
	node tests/browser_check.mjs

catalog: ## Rebuild the catalog from the saved playlist (offline; no network)
	python3 src/categorize.py
	python3 src/build_sequences.py

verify-catalog: catalog ## Fail if the committed output files are stale
	# `git status --porcelain` rather than `git diff`, so a NEW output file that
	# was never committed is caught too, not just changes to existing ones.
	@test -z "$$(git status --porcelain -- output/)" \
		|| { echo "error: output/ is stale - run 'make catalog' and commit the result."; \
		     git status --short -- output/; exit 1; }
	@echo "output/ matches what the current code produces."

serve: ## Serve the folder so search.html can load its data
	@echo "Open http://localhost:8000/search.html"
	python3 -m http.server 8000
