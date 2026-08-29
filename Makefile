PYTHON ?= python3
SRC := packages/repograph-core/src:packages/repograph-render/src:packages/repograph-cli/src:packages/repograph-tui/src
OUT ?= repograph-out
TARGET ?= .

.PHONY: help
help:
	@echo "repograph — make targets"
	@echo "  make scan TARGET=<path>   scan a repository (default: this one)"
	@echo "  make demo                 scan the bundled example monorepo"
	@echo "  make tui                  browse the last scan in the terminal"
	@echo "  make serve                serve the HTML report on :8000"
	@echo "  make test                 run the test suite"
	@echo "  make lint                 run ruff (if installed)"
	@echo "  make install              install with pipx (falls back to pip --user)"
	@echo "  make clean                remove generated output"

.PHONY: scan
scan:
	./bin/repograph scan $(TARGET) -o $(OUT)

.PHONY: demo
demo:
	./bin/repograph scan examples/sample-monorepo -o examples/sample-monorepo-report

.PHONY: tui
tui:
	./bin/repograph tui $(OUT)

.PHONY: serve
serve:
	./bin/repograph serve $(OUT)

.PHONY: test
test:
	PYTHONPATH=$(SRC) $(PYTHON) -m unittest discover -s tests -v

.PHONY: lint
lint:
	@command -v ruff >/dev/null 2>&1 && ruff check . || echo "ruff not installed — skipping"

.PHONY: install
install:
	@command -v pipx >/dev/null 2>&1 && pipx install --force . || $(PYTHON) -m pip install --user .

.PHONY: clean
clean:
	rm -rf $(OUT) examples/sample-monorepo-report build dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
