"""
Smoke test: import the package, build the scene, configure physics, but do
NOT bake or render. Catches API mismatches and import errors fast.

Run via:
    blender --background --python scripts/smoke_test.py

Exits non-zero on any unexpected error so it's CI-friendly.
"""

from __future__ import annotations

import os
import sys
import traceback

# Make the package importable when running from the repo root
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def main() -> int:
    try:
        import bpy  # noqa: F401  -- verifies we're inside Blender
        from d20_renderer.config import PipelineConfig
        from d20_renderer import scene as scene_mod
        from d20_renderer import die as die_mod
        from d20_renderer import physics as physics_mod
        from d20_renderer.pipeline import _clear_scene
    except Exception:
        print("[smoke] FAIL: imports", file=sys.stderr)
        traceback.print_exc()
        return 1

    try:
        cfg = PipelineConfig()
        # Make the smoke test cheap: tiny frame range, no bake
        cfg.physics.max_simulation_frames = 4
        cfg.physics.bake_cache = False

        _clear_scene()
        scene_mod.build_table(cfg.table)
        scene_mod.build_lighting(cfg.lighting)
        cam = scene_mod.build_camera(cfg.camera)
        die = die_mod.build_die(cfg.die)
        physics_mod.configure_world(cfg.physics)
        physics_mod.apply_initial_throw(die, cfg.physics)

        # Sanity checks
        assert die is not None, "die object missing"
        assert cam is not None, "camera object missing"
        assert len(die.children) == 20, f"expected 20 face labels, got {len(die.children)}"
        assert die.rigid_body is not None, "die has no rigid body"
        assert die.rigid_body.type == "ACTIVE", "die rigid body should be ACTIVE"

        print("[smoke] OK")
        return 0
    except Exception:
        print("[smoke] FAIL: scene build", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
