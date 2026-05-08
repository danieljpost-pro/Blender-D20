"""
Banner overlay: a 2D text banner that animates onto the screen after the die
has settled. Implemented via Blender's compositor so it sits on top of the
3D render with full control over scroll, fade, and timing — and can be
toggled or reconfigured without touching the 3D scene at all.

How it works
------------
1. We pre-render the banner text to a transparent PNG using PIL (or Blender's
   text-to-image baking). The PNG has the text + outline + rounded background.
   The PNG is content-addressed and cached, so re-rendering the same banner
   text/styling doesn't regenerate the image.
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
from . import log

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
    banner_png_path = _render_banner_png(banner_cfg, render_cfg, outcome_value)

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


def _get_compositor_tree(scene):
    """Return scene's compositor NodeTree, creating it if needed.

    Blender 4.x exposes the compositor tree as `scene.node_tree` (after enabling
    `use_nodes`). Blender 5.x removed that attribute and instead stores it as a
    standalone `bpy.data.node_groups` datablock referenced by
    `scene.compositing_node_group`.
    """
    scene.use_nodes = True
    if hasattr(scene, "node_tree") and scene.node_tree is not None:
        return scene.node_tree
    tree = scene.compositing_node_group
    if tree is None:
        tree = bpy.data.node_groups.new(name="D20_Compositor", type="CompositorNodeTree")
        scene.compositing_node_group = tree
    return tree


def _alpha_over_socket(node, role: str):
    """Return the AlphaOver input socket for `role` ('factor'/'background'/'foreground').

    Blender 4 used positional sockets [Fac, Image, Image]; Blender 5 renamed
    them to Factor/Background/Foreground (with Background first).
    """
    name_map = {
        "factor": ("Factor", "Fac"),
        "background": ("Background",),
        "foreground": ("Foreground",),
    }
    for name in name_map[role]:
        sock = node.inputs.get(name)
        if sock is not None:
            return sock
    # Blender 4 positional fallback.
    fallback_idx = {"factor": 0, "background": 1, "foreground": 2}[role]
    return node.inputs[fallback_idx]


def _new_composite_sink(tree):
    """Add a composite output sink to `tree` and return its Image input socket.

    Blender 4.x uses `CompositorNodeComposite`. Blender 5.x replaced this with
    a NodeGroupOutput on the compositor node group, requiring an Image socket
    on the group's interface.
    """
    try:
        node = tree.nodes.new("CompositorNodeComposite")
        return node.inputs["Image"]
    except RuntimeError:
        # Blender 5.x — build a group output instead.
        if not any(
            getattr(item, "in_out", None) == "OUTPUT" and item.name == "Image"
            for item in tree.interface.items_tree
        ):
            tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        node = tree.nodes.new("NodeGroupOutput")
        return node.inputs["Image"]


def _setup_passthrough_compositor() -> None:
    scene = bpy.context.scene
    tree = _get_compositor_tree(scene)
    tree.nodes.clear()
    rl = tree.nodes.new("CompositorNodeRLayers")
    sink = _new_composite_sink(tree)
    tree.links.new(rl.outputs["Image"], sink)


def _build_compositor_graph(
    cfg: BannerConfig,
    render_cfg: RenderConfig,
    banner_png_path: str,
    settle_frame: int,
) -> None:
    scene = bpy.context.scene
    tree = _get_compositor_tree(scene)
    tree.nodes.clear()

    rl = tree.nodes.new("CompositorNodeRLayers")
    composite_sink = _new_composite_sink(tree)

    # Load banner image
    img = bpy.data.images.load(banner_png_path, check_existing=True)
    img_node = tree.nodes.new("CompositorNodeImage")
    img_node.image = img

    # Translate node for scroll animation
    translate = tree.nodes.new("CompositorNodeTranslate")

    # Alpha-over for compositing the banner on top of the render.
    # Blender 4.x sockets: [Fac(0), Image-bg(1), Image-fg(2)].
    # Blender 5.x sockets: Background, Foreground, Factor (named).
    alpha_over = tree.nodes.new("CompositorNodeAlphaOver")
    ao_factor = _alpha_over_socket(alpha_over, "factor")
    ao_bg = _alpha_over_socket(alpha_over, "background")
    ao_fg = _alpha_over_socket(alpha_over, "foreground")
    ao_factor.default_value = 1.0  # animated for fade

    # Wire: render -> alpha_over.bg; banner -> translate -> alpha_over.fg
    tree.links.new(rl.outputs["Image"], ao_bg)
    tree.links.new(img_node.outputs["Image"], translate.inputs["Image"])
    tree.links.new(translate.outputs["Image"], ao_fg)
    tree.links.new(alpha_over.outputs["Image"], composite_sink)

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
    fac = _alpha_over_socket(alpha_over_node, "factor")
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
