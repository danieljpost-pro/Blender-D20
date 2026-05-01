# Makefile for the D20 renderer.
#
# All Blender commands route through $(BLENDER), which defaults to whatever
# `blender` is on PATH. Override on macOS:
#   make render BLENDER=/Applications/Blender.app/Contents/MacOS/Blender

BLENDER       ?= blender
PYTHON        ?= python3
OUTPUT_DIR    ?= ./renders
OUTCOMES      ?= 20
CONFIG        ?=

# Build the --config flag only if CONFIG is set
CONFIG_FLAG   := $(if $(CONFIG),--config $(CONFIG),)

.PHONY: help render render-all smoke lint format clean install-deps install-blender-deps

help:
	@echo "Targets:"
	@echo "  render             - Render outcomes specified by OUTCOMES (default: 20)"
	@echo "  render-all         - Render all 20 outcomes from one simulation"
	@echo "  smoke              - Build the scene inside Blender without rendering"
	@echo "  lint               - Run ruff on the package"
	@echo "  format             - Run ruff format on the package"
	@echo "  clean              - Remove rendered output and Blender caches"
	@echo "  install-deps       - Install dev tooling (system Python)"
	@echo "  install-blender-deps - Install Pillow into Blender's bundled Python"
	@echo ""
	@echo "Variables:"
	@echo "  BLENDER     Path to blender (default: blender)"
	@echo "  OUTCOMES    Space-separated list of die values to render (default: 20)"
	@echo "  CONFIG      Path to a JSON override file (optional)"
	@echo "  OUTPUT_DIR  Where to write renders (default: ./renders)"

render:
	$(BLENDER) --background --python-use-system-env \
		--python -m d20_renderer.run -- \
		$(CONFIG_FLAG) \
		--outcomes $(OUTCOMES) \
		--output-dir $(OUTPUT_DIR)

render-all:
	$(BLENDER) --background --python-use-system-env \
		--python -m d20_renderer.run -- \
		$(CONFIG_FLAG) \
		--outcomes 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 \
		--output-dir $(OUTPUT_DIR)

smoke:
	$(BLENDER) --background --python-use-system-env \
		--python scripts/smoke_test.py

lint:
	ruff check d20_renderer/

format:
	ruff format d20_renderer/
	ruff check --fix d20_renderer/

clean:
	rm -rf $(OUTPUT_DIR)
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name "blendcache_*" -exec rm -rf {} +
	rm -f /tmp/banner_*.png

install-deps:
	$(PYTHON) -m pip install -r requirements-dev.txt

install-blender-deps:
	@echo "Installing Pillow into Blender's bundled Python..."
	@echo "If this fails, locate Blender's python and run pip manually."
	$(BLENDER) --background --python-use-system-env --python-expr \
		"import subprocess, sys; subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'Pillow'])"
