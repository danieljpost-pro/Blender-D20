# D20 Renderer

Generates videos of a D20 die rolling, with deterministic, predetermined outcomes.

## Approach

The simulation always runs forward in physical time (no reverse-video tricks, no
negative friction). Because Blender's Bullet rigid body physics is deterministic,
we:

1. Run the roll **once** with default 1..20 face labels.
2. Detect the frame at which the die settles, and which face is pointing up.
3. For each desired outcome (e.g. "20"), **swap the text on the face labels** so
   the up-pointing face shows the desired number, while preserving the standard
   "opposite faces sum to 21" property.
4. Render once per outcome. The simulation cache is reused; only labels and the
   compositor banner change between renders.

This means 20 outcome videos cost 1 simulation + 20 renders, not 20 simulations.

## Module layout

```
d20_renderer/
├── config.py        # Every tunable parameter, as dataclasses
├── scene.py         # Table, lights, camera, world background
├── die.py           # D20 mesh, body material, per-face text labels
├── physics.py       # Initial throw, simulation, settle/up-face detection
├── banner.py        # 2D compositor banner overlay (independent of 3D scene)
├── banner_audio.py  # Optional sting + ambience for the banner (VSE strips)
├── render.py        # Render-engine settings + execution
├── pipeline.py      # Orchestrates everything
└── run.py           # CLI entry point
```

## Running

```bash
# Default: render outcome [20] to ./renders/d20_roll_20.mp4
blender --background --python -m d20_renderer.run

# Specific outcomes
blender --background --python -m d20_renderer.run -- --outcomes 1 13 20

# Full set
blender --background --python -m d20_renderer.run -- \
    --outcomes 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20

# With config override
blender --background --python -m d20_renderer.run -- --config my_overrides.json
```

Example `my_overrides.json`:

```json
{
  "die": {
    "body_color": [0.1, 0.1, 0.15, 1.0],
    "body_transmission": 0.4,
    "mass": 0.020
  },
  "physics": {
    "gravity": [0, 0, -9.81],
    "initial_angular_velocity": [20, 5, 18]
  },
  "banner": {
    "enabled": true,
    "text_template": "Critical hit! ({value})",
    "scroll_direction": "left"
  },
  "banner_audio": {
    "enabled": true,
    "sting_enabled": true,
    "sting_default_path": "/path/to/fanfare.wav",
    "sting_per_outcome": {
      "20": "/path/to/crit_hit.wav",
      "1":  "/path/to/critical_fail.wav"
    },
    "sting_volume": 1.0,
    "ambience_enabled": true,
    "ambience_default_path": "/path/to/tavern_loop.ogg",
    "ambience_volume": 0.35,
    "ambience_loop": true
  }
}
```

## Caveats / known TODOs

- **Number engraving styles.** `number_style="inset"` and `"raised"` are
  scaffolded but not implemented. Decals work fully and look fine for most uses.
- **Initial velocity injection** uses a "kinematic for 2 frames then release"
  trick because Blender's rigid body API doesn't expose initial velocity
  directly in older versions. On Blender 4.x there are cleaner approaches via
  the rigidbody object's `linear_velocity` field if present — worth swapping in
  for production.
- **Opposite-face mapping** in `die.assign_outcome_to_face` assumes the default
  Blender icosphere produces face indices in opposite-normal pairs. For the
  default subdivisions=1 icosphere this holds, but verify before relying on the
  sum-to-21 invariant in your Blender version.
- **PIL is required** for the banner module. Install into Blender's bundled
  Python: `<blender>/python/bin/python -m pip install Pillow`.
- **Bevels on the collision mesh.** With `collision_shape="CONVEX_HULL"` the
  bevel barely affects physics; if you switch to `"MESH"` the bounce profile
  will change noticeably.
- **Determinism.** Bake the cache (`physics.bake_cache=True`, default) and
  don't change Blender versions mid-project. Cross-version determinism is not
  guaranteed by Bullet.
