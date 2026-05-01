# CLAUDE.md

Briefing for Claude Code working in this repository.

## ⚠️ HARDWARE CONSTRAINT — READ FIRST

The user is on **limited hardware**. Every script, command, and feature in
this codebase must respect that constraint:

1. **Nothing runs unless it has to.** Every pipeline stage is cache-gated.
   Don't introduce code paths that always re-do work.
2. **Every common knob is CLI-tunable.** A user must never have to edit a
   config file just to try a different render engine, lower the resolution,
   or skip a stage. If you add a feature, expose its on/off and main
   parameters as CLI flags.
3. **Default to cheap.** New defaults should err on the side of fast/low —
   the user will turn quality up explicitly when ready.
4. **Stages are independently runnable.** Scene-build, physics-bake,
   per-outcome render, and banner-image generation can each be skipped if
   their inputs are unchanged. Don't break this.
5. **Provide a preview path.** Single-frame PNG renders, low-resolution
   modes, and dry-run all exist for fast feedback. Use them in examples.

If you propose a change that adds expense, also propose how to skip / cache /
toggle it.

## What this project is

A Blender + Python pipeline that generates videos of a D20 die rolling, with
**predetermined outcomes**. The user passes in a desired roll (e.g. 20) and
gets back an MP4 of a die rolling and landing on that number, with optional
banner overlay and audio.

## The core trick (read before changing anything)

We do **not** simulate physics in reverse. We do **not** use negative
friction. Both were considered and rejected — Bullet's solver is dissipative
and not time-reversible, and "just flip the friction sign" produces unstable
energy-gaining contacts that explode the simulation.

Instead:

1. Run **one** forward physics simulation with default 1..20 face labels.
2. Detect the frame at which the die settles, and which face is pointing
   straight up.
3. **Re-label the faces** so the up-pointing face shows the desired number,
   while preserving the standard D20 invariant that opposite faces sum to 21.
4. Render. The physics cache is unchanged across all 20 possible outcomes —
   only the text on the face labels (and the banner) differs.

N outcome videos = **1 simulation + N renders**. Anything that changes the
simulation (geometry, mass, friction, initial conditions) invalidates the
physics cache and must trigger a re-bake.

## Module map

```
d20_renderer/
├── config.py        # Every tunable parameter as nested dataclasses. Single source of truth.
├── log.py           # Tiny logging facade (verbose/quiet/dry-run).
├── cache.py         # Content-addressed stage cache keys.
├── scene.py         # Table (passive RB), bumpers, three-point lighting, camera.
├── die.py           # Icosahedron mesh, body material, per-face TEXT LABELS parented to die.
├── physics.py       # Gravity, substeps, initial throw injection, settle detection, up-face.
├── banner.py        # 2D compositor overlay. PIL-rendered PNG → animated translate + alpha-over.
├── banner_audio.py  # VSE sound strips: one-shot sting + looping ambience.
├── render.py        # Render-engine settings + audio codec toggle + preview modes.
├── pipeline.py      # Orchestrator with stage gating, caching, and dry-run.
└── run.py           # CLI entry. Defines all CLI flags, applies layered overrides.
```

## Cache architecture

Three independent cache layers:

| Stage | Key depends on | Storage |
|-------|---------------|---------|
| Physics bake | physics + physics-relevant die fields + table | `<cache_dir>/physics.cache_key` + Blender's point cache |
| Banner PNG (per outcome) | banner config + outcome value | `/tmp/banner_*.png` (Blender Image cache) |
| Render output (per outcome) | EVERYTHING (transitively includes physics key) | `<output>.cache_key` next to the output file |

The render key transitively includes the physics key, so changing physics
invalidates all renders automatically. This is intentional — false negatives
(re-rendering when we didn't need to) are cheap; false positives (skipping
when we should rerun) waste hours.

To bust caches:
- `--force-physics` — re-bake even if key matches
- `--force-render` — re-render even if outputs exist
- `--force-all` — both
- `make clean-cache` — nuclear option

## CLI surface

Every commonly-tweaked knob has a flag. Run `--help` for the full list. Key
ones to know about:

```
# Engine / quality
--engine CYCLES|BLENDER_EEVEE_NEXT|BLENDER_EEVEE
--device CPU|GPU
--samples N
--no-denoiser
--no-motion-blur
--simplify N        # global simplify with max subdiv N
--persistent-data   # Cycles BVH retention

# Resolution / framerate
--resolution WxH
--resolution-percent 25|50|75|100
--fps N

# Frames / preview
--single-frame N    # render only frame N as PNG (fast preview)
--frame-start N
--frame-end N
--max-sim-frames N  # cap simulation length

# Features
--no-banner
--banner-text "..."
--no-audio
--no-bumpers
--no-dof
--no-rim-light
--no-fill-light

# Stages
--no-simulate       # reuse cached physics
--no-render         # stop after sim
--dry-run           # log plan, no bake/render

# Cache
--no-cache
--force-physics
--force-render
--force-all
```

If you add a feature that should be toggleable, add a flag to `run.py`'s
`_build_parser()` and a corresponding override in `_apply_cli_overrides()`.

## Non-obvious design decisions

### Face labels are text objects, not textures
Each of the 20 faces gets a child `bpy.types.Object` of type TEXT, parented
to the die so it tumbles along. Re-mapping outcomes is a cheap string
rewrite on `obj.data.body`.

### Initial velocity uses "kinematic for 2 frames then release"
Blender's rigid body API doesn't cleanly expose initial linear/angular
velocity. We keyframe `kinematic=True` at frames 1-2, displace the die's
location/rotation between them to imply velocity, then `kinematic=False` at
frame 3 — Bullet picks up the implied velocity. **Blender 4.x may have a
cleaner `linear_velocity` field**; if so, prefer it.

### The banner is a 2D compositor overlay, not a 3D object
PIL renders the banner to a transparent PNG, then the compositor does:
`render → alpha_over ← translate ← image_node`, with keyframes on the
translate's X/Y (scroll) and alpha_over's Fac (fade). This keeps banner
styling/animation independent of the 3D scene.

### Audio uses the VSE, not 3D speakers
Blender supports 3D positional audio via Speaker objects, but we don't need
it — the banner sting and ambience are 2D screen-space concepts.

### FFmpeg audio codec must be flipped on
By default `render.py` sets `audio_codec="NONE"`. When `banner_audio` is
enabled, `pipeline.py` passes `with_audio=True` to `configure_render`, which
flips it to AAC. **If you add audio anywhere else, route through this same
flag** — Blender silently drops audio if the muxer isn't configured for it.

### Single-frame mode forces PNG output
When `--single-frame N` is set, `configure_render` ignores `output_format`
and writes a PNG. Otherwise FFmpeg would produce a one-frame video, which is
not what anyone wants for a preview.

### Opposite-face mapping assumes Blender's default icosphere indexing
`die.assign_outcome_to_face` finds opposite faces by negated-normal
matching. Works for `subdivisions=1` icospheres in current Blender. **Verify
the sum-to-21 invariant after any Blender upgrade.**

## Gotchas

- **Blender's bundled Python is not your system Python.** PIL must be
  installed into the bundled interpreter. `make install-blender-deps`
  handles this, but if it fails, run pip manually against
  `<blender>/python/bin/python`.
- **Determinism is per-Blender-version.** Don't change Blender mid-project.
- **Principled BSDF input names changed in Blender 4.x.** `die.py` already
  guards `Transmission`/`Transmission Weight` and `Subsurface`/`Subsurface
  Weight`. Match this pattern for new inputs.
- **`run.py` adjusts `sys.path`** so the package imports correctly when
  invoked via `blender --python`.
- **VSE looped audio strips** can be quirky across Blender versions when
  using `frame_final_duration` to extend beyond source length.
- **JSON keys are always strings.** `banner_audio._resolve_audio_path`
  handles both int and str keys for `*_per_outcome` dicts.

## Commands

All commands assume `blender` is on PATH. If not, set `BLENDER` env var.

```bash
# Cheap iteration
make preview                         # Eevee, 25%, 8 samples, no banner/audio
make preview-frame N=60              # single PNG of frame 60
make dry-run                         # plan only, no bake/render
make smoke                           # imports + scene build, no render

# Incremental rendering
make render                          # full quality
make render-no-sim                   # skip physics, reuse cache
make render-eevee                    # full quality but Eevee
make render-half                     # 50% resolution
make render-all                      # all 20 outcomes

# Cache control
make force-render
make force-physics
make force-all
make clean-cache

# Inspection
make save-blend                      # save inspect.blend, no render

# Pass-through extra flags
make render EXTRA_FLAGS="--samples 32 --no-motion-blur"
```

## When the user asks for changes

Decision tree for common requests:

| Request | Where to change | Cost | Cache impact |
|---------|----------------|------|--------------|
| Different die color/material | `DieConfig` body_* fields | cheap | render only |
| Different die mass/friction | `DieConfig` physics fields | costly | physics + render |
| Different throw | `PhysicsConfig` initial_* | costly | physics + render |
| Different lighting | `LightingConfig` | cheap | render only |
| Different camera | `CameraConfig` | cheap | render only |
| New banner animation | `banner.py` `_animate_banner` | cheap | render only |
| New sound layer | `banner_audio.py`, mirror sting/ambience pattern | cheap | render only |
| New render format | `RenderConfig` + `render.configure_render` | cheap | render only |

If the change is in the "costly" column, make sure the user knows their
physics cache will rebuild. They might want to use `--no-simulate` first to
preview with the old physics if they're not sure they want the change.

## What NOT to do

- Don't reintroduce reverse-video or negative-friction approaches.
- Don't add randomness to physics without a corresponding seed config.
- Don't bypass the `desired_outcomes` loop and re-simulate per outcome.
- Don't bake assumptions about face indexing into business logic.
- Don't import `bpy` at module top-level in test code.
- **Don't add features that always run.** Everything must be skippable,
  cacheable, or both.
- **Don't hard-code paths that should be CLI-tunable.** Output dirs, cache
  dirs, config paths — all flags.

## Verification before committing

```bash
make lint                              # ruff
make smoke                             # import sanity
make dry-run                           # plan validation
make preview-frame N=60                # cheapest visual sanity check
make render OUTCOMES="20"              # one full render end-to-end
```

If smoke passes but render fails: check Blender's stderr — `--background`
prints solver warnings.
