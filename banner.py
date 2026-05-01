"""
Banner overlay: a 2D text banner that animates onto the screen after the die
has settled. Implemented via Blender's compositor so it sits on top of the
3D render with full control over scroll, fade, and timing — and can be
toggled or reconfigured without touching the 3D scene at all.

How it works
------------
1. We pre-render the banner text to a transparent PNG using PIL (or Blender's
   text-to-image baking). The PNG has the text + outline + rounded background.
2. We add an Image node in the compositor pointing at that PNG.
3. We mix it over the rendered scene using a Mix node, with the Mix factor
   keyframed to drive the fade-in / fade-out and a Translate node keyframed
   to drive the scroll-in animation.

This isolates the banner entirely from the 3D scene — the same simulation
can be rendered with the banner on, off, or with totally different banner
text/styling, with no re-simulation or 3D scene changes.
"""

from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING

import bpy

from .config import BannerConfig, RenderConfig

if TYPE_CHECKING:
    from bpy.types import Object


def setup_banner(
    banner_cfg: BannerConfig,
    render_cfg: RenderConfig,
    outcome_value: int,
    settle_frame: int,
) -> None:
    """
    Configure compositor nodes for the banner. Call this AFTER simulation
    has settled and `settle_frame` is known.
    """
    if not banner_cfg.enabled:
        # Make sure compositor is configured to just pass through render layers
        _setup_passthrough_compositor()
        return

    # 1. Render the banner image to a temp PNG
    banner_png_path = _render_banner_png(
        banner_cfg, render_cfg, outcome_value
    )

    # 2. Wire up the compositor
    _build_compositor_graph(banner_cfg, render_cfg, banner_png_path, settle_frame)


# ----------------------------------------------------------------------------
# Banner image generation (PIL)
# ----------------------------------------------------------------------------

def _render_banner_png(
    cfg: BannerConfig,
    render_cfg: RenderConfig,
    value: int,
) -> str:
    """Render the banner as a transparent PNG and return its path."""
    from PIL import Image, ImageDraw, ImageFont

    text = cfg.text_template.format(value=value)

    # Load font
    if cfg.font_path and os.path.exists(cfg.font_path):
        font = ImageFont.truetype(cfg.font_path, cfg.font_size_px)
    else:
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", cfg.font_size_px)
        except OSError:
            font = ImageFont.load_default()

    # Measure text
    tmp = Image.new("RGBA", (10, 10))
    draw = ImageDraw.Draw(tmp)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=cfg.outline_width_px)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    pad = cfg.background_padding_px
    img_w = text_w + pad * 2
    img_h = text_h + pad * 2

    img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if cfg.background_enabled:
        bg_rgba = tuple(int(c * 255) for c in cfg.background_color)
        draw.rounded_rectangle(
            [(0, 0), (img_w - 1, img_h - 1)],
            radius=cfg.background_border_radius_px,
            fill=bg_rgba,
        )

    text_rgba = tuple(int(c * 255) for c in cfg.text_color)
    outline_rgba = tuple(int(c * 255) for c in cfg.outline_color)
    draw.text(
        (pad - bbox[0], pad - bbox[1]),
        text,
        font=font,
        fill=text_rgba,
        stroke_width=cfg.outline_width_px,
        stroke_fill=outline_rgba,
    )

    out_path = os.path.join(tempfile.gettempdir(), f"banner_{value}.png")
    img.save(out_path, "PNG")
    return out_path


# ----------------------------------------------------------------------------
# Compositor graph
# ----------------------------------------------------------------------------

def _setup_passthrough_compositor() -> None:
    scene = bpy.context.scene
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    rl = tree.nodes.new("CompositorNodeRLayers")
    comp = tree.nodes.new("CompositorNodeComposite")
    tree.links.new(rl.outputs["Image"], comp.inputs["Image"])


def _build_compositor_graph(
    cfg: BannerConfig,
    render_cfg: RenderConfig,
    banner_png_path: str,
    settle_frame: int,
) -> None:
    scene = bpy.context.scene
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()

    rl = tree.nodes.new("CompositorNodeRLayers")
    comp = tree.nodes.new("CompositorNodeComposite")

    # Load banner image
    img = bpy.data.images.load(banner_png_path, check_existing=True)
    img_node = tree.nodes.new("CompositorNodeImage")
    img_node.image = img

    # Translate node for scroll animation
    translate = tree.nodes.new("CompositorNodeTranslate")

    # Alpha-over for compositing the banner on top of the render
    alpha_over = tree.nodes.new("CompositorNodeAlphaOver")
    alpha_over.inputs[0].default_value = 1.0  # Fac, will be animated for fade

    # Wire: render -> alpha_over.image1; banner -> translate -> alpha_over.image2
    tree.links.new(rl.outputs["Image"], alpha_over.inputs[1])
    tree.links.new(img_node.outputs["Image"], translate.inputs["Image"])
    tree.links.new(translate.outputs["Image"], alpha_over.inputs[2])
    tree.links.new(alpha_over.outputs["Image"], comp.inputs["Image"])

    # Animate translate (scroll) and alpha_over factor (fade)
    _animate_banner(
        cfg,
        render_cfg,
        translate,
        alpha_over,
        banner_image_size=img.size,
        settle_frame=settle_frame,
    )


def _animate_banner(
    cfg: BannerConfig,
    render_cfg: RenderConfig,
    translate_node,
    alpha_over_node,
    banner_image_size,
    settle_frame: int,
) -> None:
    """Keyframe the scroll-in, hold, and fade-out."""
    res_x = render_cfg.resolution_x
    res_y = render_cfg.resolution_y
    bw, bh = banner_image_size

    # Final resting position of the banner center, in compositor pixel coords
    # (origin is image center; positive X = right, positive Y = up)
    if cfg.horizontal_align == "left":
        rest_x = -res_x / 2 + bw / 2 + cfg.margin_px
    elif cfg.horizontal_align == "right":
        rest_x = res_x / 2 - bw / 2 - cfg.margin_px
    else:
        rest_x = 0

    if cfg.anchor == "top":
        rest_y = res_y / 2 - bh / 2 - cfg.margin_px
    elif cfg.anchor == "bottom":
        rest_y = -res_y / 2 + bh / 2 + cfg.margin_px
    else:
        rest_y = 0

    # Off-screen start position
    if cfg.scroll_direction == "left":
        start_x, start_y = rest_x + res_x, rest_y
    elif cfg.scroll_direction == "right":
        start_x, start_y = rest_x - res_x, rest_y
    elif cfg.scroll_direction == "up":
        start_x, start_y = rest_x, rest_y - res_y
    elif cfg.scroll_direction == "down":
        start_x, start_y = rest_x, rest_y + res_y
    else:
        start_x, start_y = rest_x, rest_y

    # Trigger frame
    if cfg.trigger_mode == "after_settle":
        trigger_f = settle_frame + cfg.trigger_frame_offset
    else:
        trigger_f = cfg.trigger_frame_absolute

    arrive_f = trigger_f + cfg.scroll_duration_frames
    hold_end_f = arrive_f + cfg.hold_frames
    end_f = hold_end_f + (cfg.fade_duration_frames if cfg.fade_out else 0)

    # Scroll keyframes
    translate_node.inputs["X"].default_value = start_x
    translate_node.inputs["Y"].default_value = start_y
    translate_node.inputs["X"].keyframe_insert(data_path="default_value", frame=trigger_f)
    translate_node.inputs["Y"].keyframe_insert(data_path="default_value", frame=trigger_f)

    translate_node.inputs["X"].default_value = rest_x
    translate_node.inputs["Y"].default_value = rest_y
    translate_node.inputs["X"].keyframe_insert(data_path="default_value", frame=arrive_f)
    translate_node.inputs["Y"].keyframe_insert(data_path="default_value", frame=arrive_f)

    # Fade keyframes (alpha_over Fac: 0 = banner invisible, 1 = banner fully visible)
    fac = alpha_over_node.inputs[0]
    fac.default_value = 0.0
    fac.keyframe_insert(data_path="default_value", frame=trigger_f - 1)

    if cfg.fade_in:
        fac.default_value = 0.0
        fac.keyframe_insert(data_path="default_value", frame=trigger_f)
        fac.default_value = 1.0
        fac.keyframe_insert(data_path="default_value", frame=trigger_f + cfg.fade_duration_frames)
    else:
        fac.default_value = 1.0
        fac.keyframe_insert(data_path="default_value", frame=trigger_f)

    fac.default_value = 1.0
    fac.keyframe_insert(data_path="default_value", frame=hold_end_f)

    if cfg.fade_out:
        fac.default_value = 0.0
        fac.keyframe_insert(data_path="default_value", frame=end_f)

    # Make sure the scene's frame_end is long enough to include the banner
    bpy.context.scene.frame_end = max(bpy.context.scene.frame_end, end_f + 6)
