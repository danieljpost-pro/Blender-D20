"""
CLI entry point for the D20 renderer.

Designed for limited hardware: every commonly-tweaked parameter has a CLI
flag so you don't need to edit a config file just to flip the engine to
Eevee, drop the resolution, or skip the simulation.

Layered overrides (later wins):
  1. Built-in defaults from `config.PipelineConfig`
  2. JSON config file from `--config`
  3. CLI flags

Invocation:
    blender --background --python -m d20_renderer.run -- [flags]

Everything after `--` is passed to this script (Blender convention).

Example sessions:

    # Cheap preview: Eevee, 25% resolution, 8 samples, no banner, no audio.
    blender -b --python -m d20_renderer.run -- \
        --engine BLENDER_EEVEE_NEXT --resolution-percent 25 \
        --samples 8 --no-banner --no-audio --outcomes 20

    # Render one frame to inspect lighting/composition cheaply.
    blender -b --python -m d20_renderer.run -- \
        --single-frame 60 --outcomes 20 --output-dir ./previews

    # Skip simulation, reuse cached physics, just re-render with new die color.
    blender -b --python -m d20_renderer.run -- \
        --no-simulate --outcomes 20 --output-dir ./renders_v2

    # Dry-run: build the scene and log the plan, no bake or render.
    blender -b --python -m d20_renderer.run -- --dry-run --verbose
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import fields, is_dataclass
from typing import Any, Dict

# Make the package importable when running via `blender --python`.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_THIS_DIR)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from d20_renderer.config import PipelineConfig  # noqa: E402
from d20_renderer.pipeline import run            # noqa: E402


# ----------------------------------------------------------------------------
# Argument parsing
# ----------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="d20_renderer",
        description="Render D20 dice-roll videos with predetermined outcomes.",
    )

    # --- Config & outputs ---
    g_cfg = p.add_argument_group("config & output")
    g_cfg.add_argument("--config", type=str, default=None,
                      help="Path to a JSON file with overrides for PipelineConfig.")
    g_cfg.add_argument("--outcomes", type=int, nargs="+", default=None,
                      help="Desired outcomes 1..20. e.g. --outcomes 1 13 20")
    g_cfg.add_argument("--output-dir", type=str, default=None,
                      help="Directory for rendered videos.")
    g_cfg.add_argument("--filename-pattern", type=str, default=None,
                      help="Output filename pattern. {outcome} is substituted. "
                           "Default: 'd20_roll_{outcome:02d}'")

    # --- Render engine & quality ---
    g_render = p.add_argument_group("render engine & quality")
    g_render.add_argument("--engine", choices=["CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"],
                          default=None)
    g_render.add_argument("--device", choices=["CPU", "GPU"], default=None,
                          help="Cycles compute device.")
    g_render.add_argument("--samples", type=int, default=None,
                          help="Render samples (Cycles) or TAA samples (Eevee).")
    g_render.add_argument("--no-denoiser", action="store_true",
                          help="Disable Cycles denoiser.")
    g_render.add_argument("--no-motion-blur", action="store_true")
    g_render.add_argument("--simplify", type=int, default=None, metavar="MAX_SUBDIV",
                          help="Enable global simplify with given max subdivision level.")
    g_render.add_argument("--persistent-data", action="store_true",
                          help="Cycles: keep BVH in memory between frames (faster, more RAM).")

    # --- Resolution / framerate ---
    g_res = p.add_argument_group("resolution & framerate")
    g_res.add_argument("--resolution", type=str, default=None, metavar="WIDTHxHEIGHT",
                       help="e.g. --resolution 1280x720")
    g_res.add_argument("--resolution-percent", type=int, default=None, metavar="PCT",
                       help="Quick downscale: 25, 50, 75, 100. Cheaper than changing resolution.")
    g_res.add_argument("--fps", type=int, default=None)

    # --- Frame range / preview ---
    g_frames = p.add_argument_group("frame range & preview")
    g_frames.add_argument("--frame-start", type=int, default=None,
                          help="Override render start frame.")
    g_frames.add_argument("--frame-end", type=int, default=None,
                          help="Override render end frame.")
    g_frames.add_argument("--single-frame", type=int, default=None, metavar="N",
                          help="Render only this frame as a PNG. Great for cheap previews.")
    g_frames.add_argument("--max-sim-frames", type=int, default=None,
                          help="Cap on simulation length (frames).")

    # --- Output format ---
    g_out = p.add_argument_group("output format")
    g_out.add_argument("--format", choices=["FFMPEG", "PNG"], default=None,
                       dest="output_format")
    g_out.add_argument("--codec", type=str, default=None, dest="ffmpeg_codec",
                       help="FFmpeg codec, e.g. H264")
    g_out.add_argument("--quality", choices=["LOW", "MEDIUM", "HIGH", "PERC_LOSSLESS", "LOSSLESS"],
                       default=None, dest="ffmpeg_quality")

    # --- Feature toggles ---
    g_feat = p.add_argument_group("feature toggles")
    g_feat.add_argument("--no-banner", action="store_true",
                        help="Disable banner overlay regardless of config.")
    g_feat.add_argument("--banner-text", type=str, default=None,
                        help="Override banner text template. {value} is substituted.")
    g_feat.add_argument("--no-audio", action="store_true",
                        help="Disable banner audio regardless of config.")
    g_feat.add_argument("--no-bumpers", action="store_true",
                        help="Disable invisible table bumpers (die may roll out of frame).")
    g_feat.add_argument("--no-dof", action="store_true",
                        help="Disable depth of field (faster render).")
    g_feat.add_argument("--no-rim-light", action="store_true")
    g_feat.add_argument("--no-fill-light", action="store_true")

    # --- Stages & caching ---
    g_stage = p.add_argument_group("stages & caching")
    g_stage.add_argument("--no-simulate", action="store_true",
                         help="Skip physics bake; reuse existing cached simulation.")
    g_stage.add_argument("--no-render", action="store_true",
                         help="Stop after simulation. Useful with --save-blend.")
    g_stage.add_argument("--no-cache", action="store_true",
                         help="Disable cache hit-checking (always rebuilds).")
    g_stage.add_argument("--cache-dir", type=str, default=None)
    g_stage.add_argument("--force-physics", action="store_true",
                         help="Force re-bake even if physics cache key matches.")
    g_stage.add_argument("--force-render", action="store_true",
                         help="Force re-render even if output file exists with matching key.")
    g_stage.add_argument("--force-all", action="store_true",
                         help="Equivalent to --force-physics --force-render.")

    # --- Logging / dry-run ---
    g_log = p.add_argument_group("logging")
    g_log.add_argument("--verbose", "-v", action="store_true")
    g_log.add_argument("--quiet", "-q", action="store_true")
    g_log.add_argument("--dry-run", action="store_true",
                       help="Build the scene, log the plan, but skip bake and render.")

    # --- Save the .blend for manual inspection ---
    g_log.add_argument("--save-blend", type=str, default=None, metavar="PATH",
                       help="After running, save the Blender file to this path.")

    return p


def _parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    return _build_parser().parse_args(argv)


# ----------------------------------------------------------------------------
# Override application
# ----------------------------------------------------------------------------

def _apply_json_overrides(cfg: PipelineConfig, overrides: Dict[str, Any]) -> None:
    """Recursively apply a dict of overrides onto a dataclass tree."""
    def merge(obj, ov):
        if not is_dataclass(obj) or not isinstance(ov, dict):
            return
        valid_field_names = {f.name for f in fields(obj)}
        for key, new_val in ov.items():
            if key not in valid_field_names:
                continue   # silently ignore unknowns (e.g. _comment)
            cur = getattr(obj, key)
            if is_dataclass(cur) and isinstance(new_val, dict):
                merge(cur, new_val)
            else:
                setattr(obj, key, new_val)
    merge(cfg, overrides)


def _apply_cli_overrides(cfg: PipelineConfig, args: argparse.Namespace) -> None:
    """Map CLI flags onto the config tree. Each flag is opt-in: None = leave alone."""

    # Outcomes / output
    if args.outcomes:
        cfg.desired_outcomes = args.outcomes
    if args.output_dir is not None:
        cfg.render.output_dir = args.output_dir
    if args.filename_pattern is not None:
        cfg.render.output_filename_pattern = args.filename_pattern

    # Engine / quality
    if args.engine is not None:
        cfg.render.engine = args.engine
    if args.device is not None:
        cfg.render.device = args.device
    if args.samples is not None:
        cfg.render.samples = args.samples
    if args.no_denoiser:
        cfg.render.use_denoiser = False
    if args.no_motion_blur:
        cfg.render.use_motion_blur = False
    if args.simplify is not None:
        cfg.render.simplify_enabled = True
        cfg.render.simplify_subdivision = args.simplify
    if args.persistent_data:
        cfg.render.persistent_data = True

    # Resolution / fps
    if args.resolution is not None:
        try:
            w, h = args.resolution.lower().split("x")
            cfg.render.resolution_x = int(w)
            cfg.render.resolution_y = int(h)
        except ValueError:
            raise SystemExit(f"--resolution must be WIDTHxHEIGHT, got {args.resolution!r}")
    if args.resolution_percent is not None:
        cfg.render.resolution_percentage = args.resolution_percent
    if args.fps is not None:
        cfg.render.fps = args.fps

    # Frame range / preview
    if args.frame_start is not None:
        cfg.render.frame_start_override = args.frame_start
    if args.frame_end is not None:
        cfg.render.frame_end_override = args.frame_end
    if args.single_frame is not None:
        cfg.render.single_frame = args.single_frame
    if args.max_sim_frames is not None:
        cfg.physics.max_simulation_frames = args.max_sim_frames

    # Output format
    if args.output_format is not None:
        cfg.render.output_format = args.output_format
    if args.ffmpeg_codec is not None:
        cfg.render.ffmpeg_codec = args.ffmpeg_codec
    if args.ffmpeg_quality is not None:
        cfg.render.ffmpeg_quality = args.ffmpeg_quality

    # Feature toggles
    if args.no_banner:
        cfg.banner.enabled = False
    if args.banner_text is not None:
        cfg.banner.text_template = args.banner_text
    if args.no_audio:
        cfg.banner_audio.enabled = False
    if args.no_bumpers:
        cfg.table.bumpers_enabled = False
    if args.no_dof:
        cfg.camera.dof_enabled = False
    if args.no_rim_light:
        cfg.lighting.rim_enabled = False
    if args.no_fill_light:
        cfg.lighting.fill_enabled = False

    # Stages & cache
    if args.no_simulate:
        cfg.stages.do_simulate = False
    if args.no_render:
        cfg.stages.do_render = False
    if args.no_cache:
        cfg.cache.enabled = False
    if args.cache_dir is not None:
        cfg.cache.cache_dir = args.cache_dir
    if args.force_physics or args.force_all:
        cfg.cache.force_physics = True
    if args.force_render or args.force_all:
        cfg.cache.force_render = True

    # Logging
    cfg.logging.verbose = args.verbose
    cfg.logging.quiet = args.quiet
    cfg.logging.dry_run = args.dry_run


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()
    cfg = PipelineConfig()

    if args.config:
        with open(args.config) as fh:
            _apply_json_overrides(cfg, json.load(fh))

    _apply_cli_overrides(cfg, args)

    run(cfg)

    # Optionally save the .blend for manual inspection
    if args.save_blend:
        import bpy
        save_path = os.path.abspath(args.save_blend)
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=save_path)
        print(f"[d20] Saved .blend to {save_path}")


if __name__ == "__main__":
    main()
