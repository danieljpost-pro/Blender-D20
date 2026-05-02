"""
Render configuration and execution.

Translates RenderConfig into Blender scene/render settings, including the
hardware-aware levers (device, persistent data, simplify, resolution
percentage, single-frame preview, frame range override).
"""

from __future__ import annotations

import os

import bpy

from .config import RenderConfig
from . import log


def configure_render(cfg: RenderConfig, output_path: str, with_audio: bool = False) -> None:
    """Apply RenderConfig to the current scene.

    Args:
        cfg: render config.
        output_path: filepath for the rendered video (or PNG, in single_frame mode).
        with_audio: if True, configure the FFmpeg muxer to include audio (AAC).
    """
    scene = bpy.context.scene
    r = scene.render

    log.debug(f"render.configure: engine={cfg.engine}, device={cfg.device}, samples={cfg.samples}, "
              f"res={cfg.resolution_x}x{cfg.resolution_y}@{cfg.resolution_percentage}%, "
              f"fps={cfg.fps}, format={cfg.output_format}, denoiser={cfg.use_denoiser}, "
              f"audio={with_audio}, output={output_path}")

    # --- Engine ---
    r.engine = cfg.engine

    # --- Resolution ---
    r.resolution_x = cfg.resolution_x
    r.resolution_y = cfg.resolution_y
    r.resolution_percentage = max(1, min(100, cfg.resolution_percentage))
    r.fps = cfg.fps

    # --- Engine-specific ---
    if cfg.engine == "CYCLES":
        scene.cycles.samples = cfg.samples
        scene.cycles.use_denoising = cfg.use_denoiser
        scene.cycles.device = cfg.device
        if hasattr(scene.cycles, "use_persistent_data"):
            scene.cycles.use_persistent_data = cfg.persistent_data
        if hasattr(scene.cycles, "tile_size"):
            scene.cycles.tile_size = cfg.tile_size
    else:
        if hasattr(scene, "eevee"):
            scene.eevee.taa_render_samples = cfg.samples

    # --- Simplify (emergency quality reducer) ---
    if cfg.simplify_enabled:
        r.use_simplify = True
        r.simplify_subdivision_render = cfg.simplify_subdivision
    else:
        r.use_simplify = False

    # --- Motion blur ---
    r.use_motion_blur = cfg.use_motion_blur
    if cfg.use_motion_blur and cfg.engine == "CYCLES":
        scene.cycles.motion_blur_position = "CENTER"
        r.motion_blur_shutter = cfg.motion_blur_shutter

    # --- Frame range override ---
    # Single-frame mode trumps everything else
    if cfg.single_frame is not None:
        scene.frame_start = cfg.single_frame
        scene.frame_end = cfg.single_frame
        log.debug(f"single_frame mode: rendering frame {cfg.single_frame} only")
    else:
        if cfg.frame_start_override is not None:
            scene.frame_start = cfg.frame_start_override
        if cfg.frame_end_override is not None:
            scene.frame_end = cfg.frame_end_override

    # --- Output ---
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    r.filepath = output_path

    # Single-frame mode forces PNG output regardless of configured format
    if cfg.single_frame is not None:
        r.image_settings.file_format = "PNG"
        r.image_settings.color_mode = "RGBA"
    elif cfg.output_format == "FFMPEG":
        r.image_settings.file_format = "FFMPEG"
        r.ffmpeg.format = "MPEG4"
        r.ffmpeg.codec = cfg.ffmpeg_codec
        r.ffmpeg.constant_rate_factor = cfg.ffmpeg_quality
        if with_audio:
            r.ffmpeg.audio_codec = "AAC"
            r.ffmpeg.audio_bitrate = 192
        else:
            r.ffmpeg.audio_codec = "NONE"
    else:
        r.image_settings.file_format = "PNG"
        r.image_settings.color_mode = "RGBA"


def render_animation() -> None:
    """Trigger a render. In single_frame mode this renders a still image."""
    if log.is_dry_run():
        log.stage("render", "DRY-RUN (skipping bpy.ops.render.render)")
        return
    scene = bpy.context.scene
    is_still = scene.frame_start == scene.frame_end
    bpy.ops.render.render(animation=not is_still, write_still=is_still)


def output_extension(cfg: RenderConfig) -> str:
    """Return the file extension that will actually be produced."""
    if cfg.single_frame is not None:
        return ".png"
    if cfg.output_format == "FFMPEG":
        return ".mp4"
    return ""
