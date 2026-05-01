# Makefile for the D20 renderer.
#
# Designed for limited hardware: targets are organized from cheap to expensive,
# so you can iterate quickly with `make preview`, then graduate to `make render`
# for final quality only when ready.
#
# Override Blender path on macOS:
#   make render BLENDER=/Applications/Blender.app/Contents/MacOS/Blender

BLENDER       ?= blender
PYTHON        ?= python3
OUTPUT_DIR    ?= ./renders
PREVIEW_DIR   ?= ./previews
CACHE_DIR     ?= ./.d20_cache
OUTCOMES      ?= 20
CONFIG        ?=
EXTRA_FLAGS   ?=

# Build the --config flag only if CONFIG is set
CONFIG_FLAG := $(if $(CONFIG),--config $(CONFIG),)

# Common Blender invocation prefix
BLEND := $(BLENDER) --background --python-use-system-env --python d20_renderer/run.py --

.PHONY: help
help:
	@echo "═══════════════════════════════════════════════════════════════"
	@echo "D20 Renderer — incremental, cache-aware video pipeline"
	@echo "═══════════════════════════════════════════════════════════════"
	@echo ""
	@echo "QUICK ITERATION (cheap):"
	@echo "  make preview              Eevee, 25%, 8 samples, no banner/audio"
	@echo "  make preview-frame N=60   Render only frame N as PNG"
	@echo "  make dry-run              Build scene, log plan, no bake/render"
	@echo "  make smoke                Verify package imports inside Blender"
	@echo ""
	@echo "INCREMENTAL RENDERING:"
	@echo "  make render               Render OUTCOMES (default: 20) at full quality"
	@echo "  make render-no-sim        Skip physics bake, reuse cached simulation"
	@echo "  make render-eevee         Full quality but with Eevee (much faster)"
	@echo "  make render-half          50% resolution"
	@echo "  make render-quarter       25% resolution"
	@echo "  make render-all           All 20 outcomes from one simulation"
	@echo ""
	@echo "CACHE CONTROL:"
	@echo "  make force-render         Re-render even if outputs exist"
	@echo "  make force-physics        Re-bake physics even if cache key matches"
	@echo "  make force-all            Force everything"
	@echo "  make clean-cache          Delete the .d20_cache directory"
	@echo "  make clean-renders        Delete the renders directory"
	@echo "  make clean                Both of the above + Blender caches"
	@echo ""
	@echo "INSPECTION:"
	@echo "  make save-blend           Build, simulate, save .blend (no render)"
	@echo ""
	@echo "DEV TOOLING:"
	@echo "  make lint                 ruff check"
	@echo "  make format               ruff format + auto-fix"
	@echo "  make install-deps         Install ruff into system Python"
	@echo "  make install-blender-deps Install Pillow into Blender's Python"
	@echo ""
	@echo "VARIABLES:"
	@echo "  BLENDER     ($(BLENDER))"
	@echo "  OUTCOMES    ($(OUTCOMES))    space-separated, e.g. OUTCOMES='1 13 20'"
	@echo "  CONFIG      ($(CONFIG))      path to JSON override file"
	@echo "  OUTPUT_DIR  ($(OUTPUT_DIR))"
	@echo "  PREVIEW_DIR ($(PREVIEW_DIR))"
	@echo "  CACHE_DIR   ($(CACHE_DIR))"
	@echo "  EXTRA_FLAGS pass extra CLI flags through"
	@echo ""
	@echo "Use \`make render EXTRA_FLAGS='--no-motion-blur --samples 32'\` to"
	@echo "tweak any flag not exposed as a dedicated target. See:"
	@echo "  $(BLENDER) -b --python d20_renderer/run.py -- --help"

# ─── Quick iteration ─────────────────────────────────────────────────────────

.PHONY: preview
preview:
	$(BLEND) $(CONFIG_FLAG) \
		--engine BLENDER_EEVEE_NEXT --resolution-percent 25 --samples 8 \
		--no-banner --no-audio --no-motion-blur --no-dof \
		--outcomes $(OUTCOMES) --output-dir $(PREVIEW_DIR) \
		$(EXTRA_FLAGS)

# Render a single frame as a PNG. Usage: make preview-frame N=60
.PHONY: preview-frame
preview-frame:
	@if [ -z "$(N)" ]; then echo "Usage: make preview-frame N=<frame>"; exit 1; fi
	$(BLEND) $(CONFIG_FLAG) \
		--engine BLENDER_EEVEE_NEXT --resolution-percent 50 --samples 16 \
		--single-frame $(N) \
		--outcomes $(OUTCOMES) --output-dir $(PREVIEW_DIR) \
		$(EXTRA_FLAGS)

.PHONY: dry-run
dry-run:
	$(BLEND) $(CONFIG_FLAG) --dry-run --verbose \
		--outcomes $(OUTCOMES) $(EXTRA_FLAGS)

.PHONY: smoke
smoke:
	$(BLENDER) --background --python-use-system-env --python scripts/smoke_test.py

# ─── Incremental rendering ───────────────────────────────────────────────────

.PHONY: render
render:
	$(BLEND) $(CONFIG_FLAG) \
		--outcomes $(OUTCOMES) --output-dir $(OUTPUT_DIR) \
		$(EXTRA_FLAGS)

.PHONY: render-no-sim
render-no-sim:
	$(BLEND) $(CONFIG_FLAG) --no-simulate \
		--outcomes $(OUTCOMES) --output-dir $(OUTPUT_DIR) \
		$(EXTRA_FLAGS)

.PHONY: render-eevee
render-eevee:
	$(BLEND) $(CONFIG_FLAG) --engine BLENDER_EEVEE_NEXT \
		--outcomes $(OUTCOMES) --output-dir $(OUTPUT_DIR) \
		$(EXTRA_FLAGS)

.PHONY: render-half
render-half:
	$(BLEND) $(CONFIG_FLAG) --resolution-percent 50 \
		--outcomes $(OUTCOMES) --output-dir $(OUTPUT_DIR) \
		$(EXTRA_FLAGS)

.PHONY: render-quarter
render-quarter:
	$(BLEND) $(CONFIG_FLAG) --resolution-percent 25 \
		--outcomes $(OUTCOMES) --output-dir $(OUTPUT_DIR) \
		$(EXTRA_FLAGS)

.PHONY: render-all
render-all:
	$(BLEND) $(CONFIG_FLAG) \
		--outcomes 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 \
		--output-dir $(OUTPUT_DIR) \
		$(EXTRA_FLAGS)

# ─── Cache control ───────────────────────────────────────────────────────────

.PHONY: force-render
force-render:
	$(BLEND) $(CONFIG_FLAG) --force-render \
		--outcomes $(OUTCOMES) --output-dir $(OUTPUT_DIR) \
		$(EXTRA_FLAGS)

.PHONY: force-physics
force-physics:
	$(BLEND) $(CONFIG_FLAG) --force-physics \
		--outcomes $(OUTCOMES) --output-dir $(OUTPUT_DIR) \
		$(EXTRA_FLAGS)

.PHONY: force-all
force-all:
	$(BLEND) $(CONFIG_FLAG) --force-all \
		--outcomes $(OUTCOMES) --output-dir $(OUTPUT_DIR) \
		$(EXTRA_FLAGS)

.PHONY: clean-cache
clean-cache:
	rm -rf $(CACHE_DIR)
	find . -type d -name "blendcache_*" -exec rm -rf {} + 2>/dev/null || true

.PHONY: clean-renders
clean-renders:
	rm -rf $(OUTPUT_DIR) $(PREVIEW_DIR)

.PHONY: clean
clean: clean-cache clean-renders
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -f /tmp/banner_*.png

# ─── Inspection ──────────────────────────────────────────────────────────────

# Build the scene and simulate, then save a .blend you can open in the GUI
# to inspect lighting/materials/composition. Doesn't render.
.PHONY: save-blend
save-blend:
	$(BLEND) $(CONFIG_FLAG) --no-render --save-blend ./inspect.blend \
		--outcomes $(OUTCOMES) $(EXTRA_FLAGS)
	@echo ""
	@echo "Open inspect.blend in Blender GUI to inspect."

# ─── Dev tooling ─────────────────────────────────────────────────────────────

.PHONY: lint
lint:
	ruff check d20_renderer/

.PHONY: format
format:
	ruff format d20_renderer/
	ruff check --fix d20_renderer/

.PHONY: install-deps
install-deps:
	$(PYTHON) -m pip install -r requirements-dev.txt

.PHONY: install-blender-deps
install-blender-deps:
	@echo "Installing Pillow into Blender's bundled Python..."
	$(BLENDER) --background --python-use-system-env --python-expr \
		"import subprocess, sys; subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'Pillow'])"
