"""
Top-level pipeline.

Workflow
--------
1. Clear the Blender scene.
2. Build table, camera, lighting, and the die (with default 1..20 face values).
3. Configure physics, apply the initial throw, bake the simulation.
4. Detect the settle frame and the up-facing face index.
5. For each desired outcome:
     a. Re-label the die's faces so the up-facing face shows the desired value.
     b. Configure the banner with that value.
     c. Configure render output and render the animation.
6. Done. The simulation cache is reused across all outcomes — only materials
   (text labels) and the compositor banner change between outcomes.
"""

from __future__ import annotations

import os

import bpy

from .config import PipelineConfig
from . import scene as scene_mod
from . import die as die_mod
from . import physics as physics_mod
from . import banner as banner_mod
from . import render as render_mod


def run(cfg: PipelineConfig) -> None:
    _clear_scene()

    # Build environment
    scene_mod.build_table(cfg.table)
    scene_mod.build_lighting(cfg.lighting)
    cam = scene_mod.build_camera(cfg.camera)

    # Build die
    die_obj = die_mod.build_die(cfg.die)

    # Wire camera DOF focus to the die now that it exists
    if cfg.camera.dof_enabled and cfg.camera.dof_focus_object:
        focus_obj = bpy.data.objects.get(cfg.camera.dof_focus_object)
        if focus_obj is not None:
            cam.data.dof.focus_object = focus_obj

    # Physics
    physics_mod.configure_world(cfg.physics)
    physics_mod.apply_initial_throw(die_obj, cfg.physics)
    physics_mod.bake_simulation(cfg.physics)

    # Settle detection
    settle_frame = physics_mod.find_settle_frame(die_obj, cfg.physics)
    up_face = physics_mod.find_up_face(die_obj, settle_frame)
    print(f"[pipeline] Settled at frame {settle_frame}, up face = {up_face}, "
          f"current value on that face = {die_obj.children[up_face].data.body}")

    # Render each desired outcome
    os.makedirs(cfg.render.output_dir, exist_ok=True)
    for outcome in cfg.desired_outcomes:
        die_mod.assign_outcome_to_face(die_obj, up_face_index=up_face, desired_value=outcome)
        banner_mod.setup_banner(cfg.banner, cfg.render, outcome, settle_frame)

        out_path = os.path.join(cfg.render.output_dir, f"d20_roll_{outcome:02d}.mp4")
        render_mod.configure_render(cfg.render, out_path)
        print(f"[pipeline] Rendering outcome {outcome} -> {out_path}")
        render_mod.render_animation()


def _clear_scene() -> None:
    """Wipe the default scene so we start from nothing."""
    # Remove all objects
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    # Clear orphan data blocks so re-running doesn't accumulate cruft
    for collection in (
        bpy.data.meshes, bpy.data.materials, bpy.data.lights,
        bpy.data.cameras, bpy.data.curves, bpy.data.images, bpy.data.fonts,
    ):
        for block in list(collection):
            if block.users == 0:
                collection.remove(block)

    # Clear rigid body world if present
    if bpy.context.scene.rigidbody_world is not None:
        bpy.ops.rigidbody.world_remove()
