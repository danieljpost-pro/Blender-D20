"""
Top-level pipeline with cache-aware, incremental execution.

Stages (each independently skippable):
  1. Scene build (always, but cheap)
  2. Physics simulate + bake — skipped if cache key matches
  3. Settle detection (always, but cheap; runs against the baked cache)
  4. Per-outcome render — each skipped if its individual output cache key matches

Hardware-aware features:
  - `stages.do_simulate=False` skips physics entirely (assumes cache exists)
  - `stages.do_render=False` stops after simulation
  - `cache.force_*` flags bypass any individual cache
  - `logging.dry_run=True` builds the scene + logs the plan but skips bake/render
"""

from __future__ import annotations

import os
import shlex
import sys
from datetime import datetime

import bpy

from . import cache as cache_mod
from . import die as die_mod
from . import log
from . import physics as physics_mod
from . import render as render_mod
from . import scene as scene_mod
from .config import PipelineConfig


def _log_invocation(cfg: PipelineConfig) -> None:
    """Log the full Blender command line to the configured log file."""
    if "--" in sys.argv:
        dash_idx = sys.argv.index("--")
        blender_args = sys.argv[1:dash_idx]
        script_args = sys.argv[dash_idx + 1 :]
    else:
        blender_args = sys.argv[1:]
        script_args = []

    blender_path = sys.argv[0] if sys.argv else "blender"
    cmd_parts = [blender_path] + blender_args + (["--"] + script_args if script_args else [])
    full_cmd = " ".join(shlex.quote(part) for part in cmd_parts)

    timestamp = datetime.now().isoformat()
    log_msg = f"[{timestamp}] {full_cmd}"
    log.file_log(log_msg)


def run(cfg: PipelineConfig) -> None:
    log.configure(cfg.logging)
    _log_invocation(cfg)
    log.info(f"Pipeline starting. Outcomes: {cfg.desired_outcomes}")
    if cfg.logging.dry_run:
        log.info("DRY-RUN MODE — no bake, no render")

    cache_mod.ensure_cache_dir(cfg.cache)

    # ---- Stage 1: Scene build ----
    log.stage("scene", "building")
    _clear_scene()

    # Bowl and table are mutually exclusive surfaces.
    if cfg.bowl.enabled:
        log.debug("bowl enabled: skipping table build")
        cfg.table.physics_enabled = False
    else:
        scene_mod.build_table(cfg.table)

    if cfg.bowl.enabled:
        scene_mod.build_bowl(cfg.bowl)
    scene_mod.build_lighting(cfg.lighting)
    cam = scene_mod.build_camera(cfg.camera)

    # Create a single die with labels for both physics and rendering
    log.debug("pipeline.scene: building die (with labels)")
    die_obj = die_mod.build_die(cfg.die, with_labels=True)

    if die_obj is not None:
        _label_children = [c for c in die_obj.children if c.name.startswith("DieLabel_")]
        log.debug(f"pipeline.scene: die has {len(_label_children)} label children")

    if cfg.camera.dof_enabled and cfg.camera.dof_focus_object and cam is not None:
        focus_obj = bpy.data.objects.get(cfg.camera.dof_focus_object)
        if focus_obj is not None:
            cam.data.dof.focus_object = focus_obj

    # ---- Stage 2: Physics simulate + bake (cache-gated) ----
    log.info("Configuring physics world...")
    physics_mod.configure_world(cfg.physics)
    log.info("Applying initial throw...")
    physics_mod.apply_initial_throw(die_obj, cfg.physics)

    if not cfg.stages.do_simulate:
        log.stage("physics", "SKIPPED (stages.do_simulate=False)")
    elif cfg.logging.dry_run:
        log.stage("physics", "DRY-RUN")
    else:
        phys_key = cache_mod.physics_key(cfg)
        phys_key_file = os.path.join(cfg.cache.cache_dir, "physics.cache_key")
        bake_blend_path = os.path.join(cfg.cache.cache_dir, "physics.blend")

        cached_key = None
        if os.path.exists(phys_key_file):
            try:
                with open(phys_key_file) as fh:
                    cached_key = fh.read().strip()
            except OSError:
                cached_key = None

        if cfg.cache.enabled and not cfg.cache.force_physics and cached_key == phys_key and os.path.exists(bake_blend_path):
            # Cache hit: load the baked physics (full scene from .blend)
            log.stage("physics", f"cache HIT (key={phys_key}) — loading baked physics")
            bpy.ops.wm.open_mainfile(filepath=bake_blend_path)
            log.info("Physics .blend loaded from disk")
            # Get references to objects from the loaded scene
            die_obj = bpy.data.objects.get("Die")
            cam = bpy.data.objects.get("Camera")
            if die_obj is None or cam is None:
                log.error("Cached .blend missing Die or Camera!")
                raise SystemExit(1)
            # The loaded .blend carries materials/lights/camera from bake
            # time; re-apply render-only config that may have changed since.
            cam = _resync_render_only_config(cfg, die_obj)
        else:
            # Cache miss: bake fresh
            if cached_key == phys_key and os.path.exists(bake_blend_path):
                log.stage("physics", f"cache KEY HIT but .blend missing (key={phys_key}) — re-baking")
            else:
                log.stage("physics", f"cache MISS — baking simulation (key={phys_key})")
            physics_mod.bake_simulation(cfg.physics)
            bpy.ops.wm.save_as_mainfile(filepath=bake_blend_path)
            with open(phys_key_file, "w") as fh:
                fh.write(phys_key)
            log.info("Physics .blend saved to disk")

    # ---- Stage 3: Settle detection ----
    log.info("Detecting settle frame...")
    settle_frame = physics_mod.find_settle_frame(die_obj, cfg.physics)
    log.info(f"Settle frame detected: {settle_frame}")
    log.info("Finding up-facing face...")
    up_face = physics_mod.find_up_face(die_obj, settle_frame)
    up_label = next(
        (c for c in die_obj.children if c.name == f"DieLabel_{up_face:02d}"),
        None,
    )
    up_label_text = up_label.data.body if up_label is not None else "?"
    log.info(
        f"Die settled at frame {settle_frame}, up-facing face index = {up_face} "
        f"(currently shows '{up_label_text}')"
    )

    # ---- Stage 3.5: Camera die-tracking ----
    if cfg.camera.track_die:
        log.info("camera.track: aiming camera at die along baked trajectory")
        scene_mod.animate_camera_track(die_obj, settle_frame, cfg.camera)

    # ---- Stage 3.5: Post-settle camera orbit ----
    # Smoothly move the camera to a top-down close-up of the up face. Also
    # clip the rendered range so we don't render hundreds of motionless frames
    # past the orbit's hold tail.
    if cfg.camera.orbit_enabled:
        bpy.context.scene.frame_set(settle_frame)
        from .die import get_labelled_face_normals

        local_n = get_labelled_face_normals(die_obj)[up_face]
        world_up = die_obj.matrix_world.to_3x3() @ local_n
        orbit_end = scene_mod.animate_camera_orbit(cam, die_obj, settle_frame, world_up, cfg.camera)
        new_end = max(bpy.context.scene.frame_start, orbit_end)
        if new_end < bpy.context.scene.frame_end:
            log.info(
                f"camera.orbit: clipping render frame_end "
                f"{bpy.context.scene.frame_end} -> {new_end}"
            )
            bpy.context.scene.frame_end = new_end

    if not cfg.stages.do_render:
        log.stage("render", "SKIPPED (stages.do_render=False)")
        return

    # ---- Stage 3.75: Greenscreen (opt-in) ----
    if cfg.render.greenscreen:
        log.stage("greenscreen", f"table+walls -> camera-only pure {cfg.render.greenscreen_color[:3]}")
        scene_mod.apply_greenscreen(cfg.render.greenscreen_color)

    # ---- Stage 4: Per-outcome render (each cache-gated) ----
    os.makedirs(cfg.render.output_dir, exist_ok=True)
    ext = render_mod.output_extension(cfg.render)
    total_outcomes = len(cfg.desired_outcomes)
    log.info(f"Starting render loop: {total_outcomes} outcome(s) to render")

    for idx, outcome in enumerate(cfg.desired_outcomes, 1):
        filename = cfg.render.output_filename_pattern.format(outcome=outcome) + ext
        out_path = os.path.join(cfg.render.output_dir, filename)
        rkey = cache_mod.render_key(cfg, outcome)

        if (
            cfg.cache.enabled
            and not cfg.cache.force_render
            and cache_mod.cache_hit(out_path, rkey, force=False)
        ):
            log.stage(f"render outcome={outcome}", f"cache HIT — skipping ({out_path})")
            log.info(f"outcome {idx}/{total_outcomes}: cache hit, skipped")
            continue

        log.info(f"outcome {idx}/{total_outcomes}: relabeling die for value {outcome}...")
        die_mod.assign_outcome_to_face(die_obj, up_face_index=up_face, desired_value=outcome)
        if cfg.die.number_style == "inset":
            log.info(f"outcome {idx}/{total_outcomes}: carving inset labels...")
            die_mod.carve_labels(die_obj, cfg.die)

        # Configure + render
        log.info(f"outcome {idx}/{total_outcomes}: configuring render...")
        render_mod.configure_render(cfg.render, out_path)
        log.stage(f"render outcome={outcome}", f"rendering -> {out_path}")
        log.info(f"outcome {idx}/{total_outcomes}: rendering...")
        render_mod.render_animation()
        log.info(f"outcome {idx}/{total_outcomes}: render complete")

        # Stamp cache key (unless dry-run)
        if not cfg.logging.dry_run:
            cache_mod.write_cache_key(out_path, rkey)

    log.info("Pipeline complete. All outcomes rendered.")


def _resync_render_only_config(cfg: PipelineConfig, die_obj) -> bpy.types.Object:
    """Re-apply render-only config on top of a scene loaded from the physics
    cache .blend.

    Physics-relevant fields are guaranteed current (they form the cache key),
    but the baked .blend snapshots materials, lights, camera, and visibility
    as they were at bake time. Without this, render-only config changes are
    silently ignored on every cache hit. Returns the (rebuilt) camera.
    """
    die_mod.reapply_materials(die_obj, cfg.die)

    # Lights: delete and rebuild (also resets the world background).
    for obj in [o for o in bpy.data.objects if o.type == "LIGHT"]:
        bpy.data.objects.remove(obj, do_unlink=True)
    scene_mod.build_lighting(cfg.lighting)

    # Camera: delete and rebuild; track/orbit keyframes are applied later in
    # the pipeline, so nothing baked into the old camera is lost.
    for name in ("Camera", "CameraTarget"):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
    cam = scene_mod.build_camera(cfg.camera)
    if cfg.camera.dof_enabled and cfg.camera.dof_focus_object:
        focus_obj = bpy.data.objects.get(cfg.camera.dof_focus_object)
        if focus_obj is not None:
            cam.data.dof.focus_object = focus_obj

    # Table / bumper appearance (not their physics, which matched the key).
    table = bpy.data.objects.get("Table")
    if table is not None:
        table.hide_render = not cfg.table.visible
        mat = table.data.materials[0] if table.data.materials else None
        if mat is not None and mat.use_nodes:
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf is not None:
                bsdf.inputs["Base Color"].default_value = cfg.table.color
                bsdf.inputs["Roughness"].default_value = cfg.table.roughness
    for obj in bpy.data.objects:
        if obj.name.startswith("Bumper"):
            obj.hide_render = not cfg.table.bumpers_visible

    return cam


def _clear_scene() -> None:
    """Wipe the default scene so we start from nothing."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    for collection in (
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.lights,
        bpy.data.cameras,
        bpy.data.curves,
        bpy.data.images,
        bpy.data.fonts,
    ):
        for block in list(collection):
            if block.users == 0:
                collection.remove(block)

    if bpy.context.scene.rigidbody_world is not None:
        bpy.ops.rigidbody.world_remove()
