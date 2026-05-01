"""
Render configuration and execution.
"""

from __future__ import annotations

import os

import bpy

from .config import RenderConfig


def configure_render(cfg: RenderConfig, output_path: str) -> None:
    """Apply RenderConfig to the current scene."""
    scene = bpy.context.scene
    r = scene.render

    r.engine = cfg.engine
    r.resolution_x = cfg.resolution_x
    r.resolution_y = cfg.resolution_y
    r.resolution_percentage = 100
    r.fps = cfg.fps

    # Engine-specific
    if cfg.engine == "CYCLES":
        scene.cycles.samples = cfg.samples
        scene.cycles.use_denoising = cfg.use_denoiser
    else:
        # Eevee samples live elsewhere; guard for version differences
        if hasattr(scene, "eevee"):
            scene.eevee.taa_render_samples = cfg.samples

    # Motion blur
    r.use_motion_blur = cfg.use_motion_blur
    if cfg.use_motion_blur and cfg.engine == "CYCLES":
        scene.cycles.motion_blur_position = "CENTER"
        r.motion_blur_shutter = cfg.motion_blur_shutter

    # Output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    r.filepath = output_path

    if cfg.output_format == "FFMPEG":
        r.image_settings.file_format = "FFMPEG"
        r.ffmpeg.format = "MPEG4"
        r.ffmpeg.codec = cfg.ffmpeg_codec
        r.ffmpeg.constant_rate_factor = cfg.ffmpeg_quality
        r.ffmpeg.audio_codec = "NONE"
    else:
        r.image_settings.file_format = "PNG"
        r.image_settings.color_mode = "RGBA"


def render_animation() -> None:
    """Trigger the actual render of the configured frame range."""
    bpy.ops.render.render(animation=True)
