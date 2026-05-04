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
import sys
import shlex
from datetime import datetime

import bpy

from .config import PipelineConfig
from . import scene as scene_mod
from . import die as die_mod
from . import physics as physics_mod
from . import banner as banner_mod
from . import banner_audio as banner_audio_mod
from . import render as render_mod
from . import cache as cache_mod
from . import log


def _log_invocation(cfg: PipelineConfig) -> None:
    """Log the full Blender command line to the configured log file."""
    if "--" in sys.argv:
        dash_idx = sys.argv.index("--")
        blender_args = sys.argv[1:dash_idx]
        script_args = sys.argv[dash_idx + 1:]
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
    scene_mod.build_table(cfg.table)
    scene_mod.build_lighting(cfg.lighting)
    cam = scene_mod.build_camera(cfg.camera)

    # Create a single die with labels for both physics and rendering
    log.debug("pipeline.scene: building die (with labels)")
    die_obj = die_mod.build_die(cfg.die, with_labels=True)

    _label_children = [c for c in die_obj.children if c.name.startswith("DieLabel_")]
    log.debug(f"pipeline.scene: die has {len(_label_children)} label children")

    if cfg.camera.dof_enabled and cfg.camera.dof_focus_object:
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
        # We persist the physics key inside the cache_dir, NOT next to the
        # baked point cache (Blender owns that path). If the key file
        # matches, we trust the existing bake.
        phys_key_file = os.path.join(cfg.cache.cache_dir, "physics.cache_key")

        cached_key = None
        if os.path.exists(phys_key_file):
            try:
                with open(phys_key_file) as fh:
                    cached_key = fh.read().strip()
            except OSError:
                cached_key = None

        if (
            cfg.cache.enabled
            and not cfg.cache.force_physics
            and cached_key == phys_key
        ):
            log.stage("physics", f"cache HIT (key={phys_key}) — loading baked cache")
            log.info("Physics cache loaded from disk")
        else:
            log.stage("physics", f"cache MISS — baking simulation (key={phys_key})")
            physics_mod.bake_simulation(cfg.physics)
            with open(phys_key_file, "w") as fh:
                fh.write(phys_key)
            log.info("Physics cache saved to disk")

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

    if not cfg.stages.do_render:
        log.stage("render", "SKIPPED (stages.do_render=False)")
        return

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

        # Banner (image potentially cached) + audio
        log.info(f"outcome {idx}/{total_outcomes}: setting up banner...")
        banner_mod.setup_banner(cfg.banner, cfg.render, outcome, settle_frame)
        log.info(f"outcome {idx}/{total_outcomes}: setting up audio...")
        has_audio = banner_audio_mod.setup_banner_audio(
            cfg.banner_audio, cfg.banner, outcome, settle_frame, cfg.render.fps
        )

        # Configure + render
        log.info(f"outcome {idx}/{total_outcomes}: configuring render...")
        render_mod.configure_render(cfg.render, out_path, with_audio=has_audio)
        log.stage(f"render outcome={outcome}", f"rendering -> {out_path} (audio={has_audio})")
        log.info(f"outcome {idx}/{total_outcomes}: rendering...")
        render_mod.render_animation()
        log.info(f"outcome {idx}/{total_outcomes}: render complete")

        # Stamp cache key (unless dry-run)
        if not cfg.logging.dry_run:
            cache_mod.write_cache_key(out_path, rkey)

    log.info("Pipeline complete. All outcomes rendered.")


def _clear_scene() -> None:
    """Wipe the default scene so we start from nothing."""
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    for collection in (
        bpy.data.meshes, bpy.data.materials, bpy.data.lights,
        bpy.data.cameras, bpy.data.curves, bpy.data.images, bpy.data.fonts,
    ):
        for block in list(collection):
            if block.users == 0:
                collection.remove(block)

    if bpy.context.scene.rigidbody_world is not None:
        bpy.ops.rigidbody.world_remove()
