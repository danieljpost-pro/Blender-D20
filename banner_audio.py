"""
Banner audio: optional sound effects layered on top of the banner.

Implementation
--------------
Blender's Video Sequence Editor (VSE) is the only sane way to attach audio
to a render. We add sound strips on the sequence editor timeline:
  - "Sting": one-shot SFX that fires when the banner triggers.
  - "Ambience": optional looping background audio that plays while the banner
    is on-screen (or for a custom absolute frame range).

Both are configured independently and either can be used without the other.
This module is also independent of the visual banner — you can render with
audio but no overlay, or vice versa.

Important: this module is responsible for ensuring the FFmpeg muxer is
configured to actually include audio in the output. `render.py` flips its
audio codec setting when banner_audio is enabled.
"""

from __future__ import annotations

import os
from typing import Optional

import bpy

from .config import BannerAudioConfig, BannerConfig


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

def setup_banner_audio(
    audio_cfg: BannerAudioConfig,
    banner_cfg: BannerConfig,
    outcome_value: int,
    settle_frame: int,
    fps: int,
) -> bool:
    """
    Configure VSE sound strips for this render.

    Returns True if any audio was added (so the renderer knows to enable
    the FFmpeg audio codec), False otherwise.
    """
    _clear_audio_strips()

    if not audio_cfg.enabled:
        return False

    trigger_frame = _compute_banner_trigger_frame(banner_cfg, settle_frame)
    banner_end_frame = _compute_banner_end_frame(banner_cfg, trigger_frame)

    seq_editor = _ensure_sequence_editor()
    added_any = False

    # Sting (one-shot)
    if audio_cfg.sting_enabled:
        sting_path = _resolve_audio_path(
            audio_cfg.sting_per_outcome,
            audio_cfg.sting_default_path,
            outcome_value,
        )
        if sting_path:
            sting_frame = trigger_frame + audio_cfg.sting_offset_frames
            _add_sting(seq_editor, sting_path, sting_frame, audio_cfg.sting_volume)
            added_any = True

    # Ambience (loop)
    if audio_cfg.ambience_enabled:
        amb_path = _resolve_audio_path(
            audio_cfg.ambience_per_outcome,
            audio_cfg.ambience_default_path,
            outcome_value,
        )
        if amb_path:
            if audio_cfg.ambience_follow_banner:
                amb_start = trigger_frame
                amb_end = banner_end_frame
            else:
                amb_start = audio_cfg.ambience_start_frame_absolute or trigger_frame
                amb_end = audio_cfg.ambience_end_frame_absolute or banner_end_frame

            _add_ambience(
                seq_editor,
                amb_path,
                start_frame=amb_start,
                end_frame=amb_end,
                volume=audio_cfg.ambience_volume,
                loop=audio_cfg.ambience_loop,
                fade_in_frames=audio_cfg.ambience_fade_in_frames,
                fade_out_frames=audio_cfg.ambience_fade_out_frames,
                fps=fps,
            )
            added_any = True

    return added_any


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _ensure_sequence_editor():
    scene = bpy.context.scene
    if scene.sequence_editor is None:
        scene.sequence_editor_create()
    return scene.sequence_editor


def _clear_audio_strips() -> None:
    """Remove any sound strips left over from a previous render."""
    scene = bpy.context.scene
    if scene.sequence_editor is None:
        return
    seqs = scene.sequence_editor.sequences
    to_remove = [s for s in seqs if s.type == "SOUND"]
    for s in to_remove:
        seqs.remove(s)


def _resolve_audio_path(per_outcome: dict, default: Optional[str], outcome: int) -> Optional[str]:
    """Per-outcome path takes precedence; otherwise fall back to default.

    Handles both int and str keys, since JSON-loaded dicts will have string keys
    (`{"20": "..."}`) while Python-constructed configs typically have int keys.
    """
    candidate = None
    if per_outcome:
        candidate = per_outcome.get(outcome) or per_outcome.get(str(outcome))
    candidate = candidate or default
    if candidate and os.path.exists(candidate):
        return candidate
    if candidate:
        print(f"[banner_audio] WARNING: path not found, skipping: {candidate}")
    return None


def _compute_banner_trigger_frame(banner_cfg: BannerConfig, settle_frame: int) -> int:
    """Mirror the logic in banner.py so audio aligns with the visual."""
    if banner_cfg.trigger_mode == "after_settle":
        return settle_frame + banner_cfg.trigger_frame_offset
    return banner_cfg.trigger_frame_absolute


def _compute_banner_end_frame(banner_cfg: BannerConfig, trigger_frame: int) -> int:
    """End of the banner's visible window (after scroll-in, hold, fade-out)."""
    arrive = trigger_frame + banner_cfg.scroll_duration_frames
    hold_end = arrive + banner_cfg.hold_frames
    end = hold_end + (banner_cfg.fade_duration_frames if banner_cfg.fade_out else 0)
    return end


# ----------------------------------------------------------------------------
# Strip creation
# ----------------------------------------------------------------------------

def _add_sting(seq_editor, path: str, frame: int, volume: float) -> None:
    """Add a one-shot sound strip at `frame`."""
    strip = seq_editor.sequences.new_sound(
        name="BannerSting",
        filepath=path,
        channel=2,
        frame_start=frame,
    )
    strip.volume = volume


def _add_ambience(
    seq_editor,
    path: str,
    start_frame: int,
    end_frame: int,
    volume: float,
    loop: bool,
    fade_in_frames: int,
    fade_out_frames: int,
    fps: int,
) -> None:
    """
    Add a looping ambience strip from `start_frame` to `end_frame`, with
    keyframed volume fades at each end.
    """
    strip = seq_editor.sequences.new_sound(
        name="BannerAmbience",
        filepath=path,
        channel=3,
        frame_start=start_frame,
    )
    duration = end_frame - start_frame

    # Looping: extend the strip's frame_final_duration to match the desired
    # window. Blender will loop the underlying sound to fill that duration if
    # `frame_final_duration` exceeds the source sound's length.
    if loop:
        strip.frame_final_duration = max(1, duration)
    else:
        # Truncate to whichever is shorter: source length or our window
        natural = strip.frame_final_duration
        strip.frame_final_duration = min(natural, max(1, duration))

    # Volume fade keyframes
    strip.volume = 0.0
    strip.keyframe_insert(data_path="volume", frame=start_frame)

    fade_in_done = start_frame + max(1, fade_in_frames)
    strip.volume = volume
    strip.keyframe_insert(data_path="volume", frame=fade_in_done)

    fade_out_start = max(fade_in_done, end_frame - max(1, fade_out_frames))
    strip.volume = volume
    strip.keyframe_insert(data_path="volume", frame=fade_out_start)

    strip.volume = 0.0
    strip.keyframe_insert(data_path="volume", frame=end_frame)
