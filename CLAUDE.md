# CLAUDE.md

Briefing for Claude Code working in this repository.

## What this project is

A Blender + Python pipeline that generates videos of a D20 die rolling, with
**predetermined outcomes**. The user passes in a desired roll (e.g. 20) and
gets back an MP4 of a die rolling and landing on that number, with an
optional banner overlay and audio.

## The core trick (read this before changing anything)

We do **not** simulate physics in reverse. We do **not** use negative
friction. Both were considered and rejected — see the git history / chat
transcript if curious, but in short: Bullet's solver is dissipative and not
time-reversible, and "just flip the friction sign" produces unstable
energy-gaining contacts that explode the simulation.

Instead:

1. Run **one** forward physics simulation with default 1..20 face labels.
2. Detect the frame at which the die settles, and which face is pointing
   straight up at that frame.
3. **Re-label the faces** so the up-pointing face shows the desired number,
   while preserving the standard D20 invariant that opposite faces sum to 21.
4. Render. The physics cache is unchanged across all 20 possible outcomes —
   only the text on the face labels (and the banner) differs.

This means N outcome videos cost **1 simulation + N renders**, not N
simulations. Anything that changes the simulation (geometry, mass, friction,
initial conditions) invalidates the cache and must trigger a re-bake.

## Module map

```
d20_renderer/
├── config.py        # All tunable parameters as nested dataclasses. Single source of truth.
├── scene.py         # Table (passive RB), bumpers, three-point lighting, camera.
├── die.py           # Icosahedron mesh, body material, per-face TEXT LABELS parented to die.
├── physics.py       # Gravity, substeps, initial throw injection, settle detection, up-face.
├── banner.py        # 2D compositor overlay. PIL renders PNG → compositor Image node →
│                    # animated translate + alpha-over keyframes.
├── banner_audio.py  # VSE sound strips: one-shot sting + looping ambience.
├── render.py        # Render engine settings + audio codec toggle.
├── pipeline.py      # Orchestrator. Builds scene → simulates → bakes → loops outcomes.
└── run.py           # CLI entry. Invoked as `blender --background --python -m d20_renderer.run`.
```

## Non-obvious design decisions

### Face labels are text objects, not textures
Each of the 20 faces gets a child `bpy.types.Object` of type TEXT, parented
to the die so it tumbles along. Re-mapping outcomes is a cheap string
rewrite on `obj.data.body`. The alternative (per-face material slots with
baked image textures) works but is more setup for the same flexibility.

### Initial velocity is injected via a "kinematic for 2 frames then release" trick
Blender's rigid body API doesn't cleanly expose initial linear/angular
velocity in older versions. We keyframe `kinematic=True` at frames 1-2,
displace the die's location/rotation between them to imply velocity, then
`kinematic=False` at frame 3 — Bullet picks up the implied velocity.
**Blender 4.x may have a cleaner `linear_velocity` field**; if so, prefer it.

### The banner is a 2D compositor overlay, not a 3D object
This keeps banner styling/animation completely independent of the 3D
scene — you can re-render with a different banner without re-simulating.
PIL renders the banner to a transparent PNG, then the compositor does:
`render → alpha_over ← translate ← image_node`, with keyframes on the
translate's X/Y (scroll) and alpha_over's Fac (fade).

### Audio uses the VSE, not 3D speakers
Blender supports 3D positional audio via Speaker objects, but we don't need
it — the banner sting and ambience are 2D screen-space concepts. VSE sound
strips are simpler and integrate cleanly with FFmpeg muxing.

### FFmpeg audio codec must be flipped on
By default `render.py` sets `audio_codec="NONE"`. When `banner_audio` is
enabled, `pipeline.py` passes `with_audio=True` to `configure_render`, which
flips it to AAC. **If you add audio anywhere else, route through this same
flag** — Blender silently drops audio if the muxer isn't configured for it.

### Opposite-face mapping assumes Blender's default icosphere indexing
`die.assign_outcome_to_face` finds opposite faces by negated-normal matching.
This works for `subdivisions=1` icospheres in current Blender, but is not
guaranteed across versions. **Verify the sum-to-21 invariant after any
Blender upgrade** by inspecting label values on opposite faces.

## Gotchas

- **Blender's bundled Python is not your system Python.** PIL must be
  installed into the bundled interpreter:
  `<blender>/python/bin/python -m pip install Pillow`. The user's system
  pip will not help.
- **Determinism is per-Blender-version.** Bake the cache (default) and
  don't change Blender versions mid-project. Cross-version Bullet is not
  bit-identical.
- **Principled BSDF input names changed in Blender 4.x.** `die.py` already
  guards `Transmission`/`Transmission Weight` and `Subsurface`/`Subsurface
  Weight`. If you add new BSDF inputs, do the same `if "Foo" in bsdf.inputs`
  dance.
- **Bevel modifier is applied destructively** in `die.py` so the collision
  shape sees the beveled mesh. If you change to `collision_shape="MESH"`,
  the bounce profile will shift noticeably from `"CONVEX_HULL"`.
- **`run.py` adjusts `sys.path`** so the package imports correctly when
  invoked via `blender --python`. Don't rely on installed-package semantics.
- **VSE looped audio strips** can be quirky across Blender versions when
  using `frame_final_duration` to extend beyond the source length. If loops
  misbehave, fall back to manually duplicating strips back-to-back.

## Commands

All commands assume `blender` is on PATH. If not, set `BLENDER` env var:
`BLENDER=/Applications/Blender.app/Contents/MacOS/Blender make render`.

```bash
# Default render (outcome 20, default config)
make render

# Specific outcomes
make render OUTCOMES="1 13 20"

# All 20 outcomes from one simulation
make render-all

# Use a config override
make render CONFIG=examples/transparent_resin.json OUTCOMES="20"

# Smoke test: import the package inside Blender, build the scene, but don't render.
# Catches API mismatches and import errors fast.
make smoke

# Lint/format (uses system Python, not Blender's)
make lint
make format

# Clean rendered output and Blender caches
make clean
```

## When the user asks for changes

Decision tree for common requests:

- **"Change how the die looks"** → `config.DieConfig` fields. No code change
  unless adding a new visual concept (then update `die._apply_body_material`).
- **"Change how the throw feels"** → `config.PhysicsConfig` initial_*
  fields. Re-bake required (delete `~/blendcache_*` or just re-run, the
  pipeline rebakes by default).
- **"Add a new banner animation style"** → `banner.py` `_animate_banner`,
  add a new `scroll_direction` value or a new keyframe pattern. Update
  `BannerConfig` to expose the parameter.
- **"Add a new sound layer"** → `banner_audio.py`, mirror the pattern of
  `_add_sting` / `_add_ambience`. Add fields to `BannerAudioConfig`. Make
  sure `setup_banner_audio` returns True if any strip was added so the
  audio codec gets enabled.
- **"Render to a different format"** → `config.RenderConfig` and
  `render.configure_render`. Add new branches alongside the FFMPEG / PNG
  ones. If adding a format that supports audio, route through the
  `with_audio` flag.
- **"Make the simulation deterministic across machines"** → Not possible
  with Bullet alone. Would require shipping baked cache files in the repo
  or moving to a deterministic external solver. Push back on the user
  before attempting.

## What NOT to do

- Don't reintroduce reverse-video or negative-friction approaches. Both
  were tried in design and rejected for solid reasons.
- Don't add randomness to physics (force fields with random seeds, etc.)
  without a corresponding seed config field — it breaks determinism.
- Don't bypass the `desired_outcomes` loop and re-simulate per outcome.
  The whole architecture's value is one-sim-many-renders.
- Don't bake assumptions about face indexing into business logic. Always
  go through `physics.find_up_face` / `die.assign_outcome_to_face`.
- Don't import `bpy` at module top-level in test code. The package is
  importable for type-checking and dataclass introspection without Blender,
  and we want to keep it that way.

## Verification before committing

```bash
make lint          # ruff
make smoke         # imports + scene build inside Blender, no render
make render OUTCOMES="20"  # one full render end-to-end
```

If smoke passes but render fails, the bug is almost certainly in physics
baking, render settings, or compositor wiring. Check Blender's stderr
output — `--background` mode prints solver warnings.
