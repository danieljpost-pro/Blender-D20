"""
Content-addressed caching for pipeline stages.

Each stage hashes its relevant config inputs into a key. We write the key to
a sidecar file (`<output>.cache_key`); subsequent runs compare keys and skip
the stage if the inputs are unchanged.

This is critical for working on limited hardware:
  - Don't re-bake physics when only changing the die color.
  - Don't re-render outcome 20 when only changing outcome 1's banner text.
  - Don't regenerate banner PNGs when only changing audio paths.

The hash is deliberately *over-conservative* — any field change in any
involved config invalidates the cache. False negatives (re-running when we
didn't need to) are cheap; false positives (skipping when we should rerun)
produce subtle bugs that waste hours.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, is_dataclass
from typing import Any, List

from .config import PipelineConfig, CacheConfig


# ----------------------------------------------------------------------------
# Hashing
# ----------------------------------------------------------------------------

def _stable_dump(obj: Any) -> str:
    """JSON dump that sorts keys for stable hashing across Python runs."""
    if is_dataclass(obj):
        obj = asdict(obj)
    return json.dumps(obj, sort_keys=True, default=str)


def _hash(*parts: Any) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(_stable_dump(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


# ----------------------------------------------------------------------------
# Stage keys — what each stage's output depends on
# ----------------------------------------------------------------------------

def physics_key(cfg: PipelineConfig) -> str:
    """
    Physics output (the baked rigid body cache) depends on:
      - All physics params (gravity, substeps, initial throw)
      - Die mesh + mass + friction + restitution + collision shape
      - Table size/location/orientation + bumpers + their friction/restitution
      - Anything that affects the simulated mesh, including bevel
    Material color/roughness/transmission do NOT affect physics, so they're
    excluded — that's the whole point of caching this stage.
    """
    return _hash(
        cfg.physics,
        # Die: only physics-relevant subset
        {
            "size": cfg.die.size,
            "bevel_amount": cfg.die.bevel_amount,
            "bevel_segments": cfg.die.bevel_segments,
            "subdivision_levels": cfg.die.subdivision_levels,
            "mass": cfg.die.mass,
            "friction": cfg.die.friction,
            "restitution": cfg.die.restitution,
            "linear_damping": cfg.die.linear_damping,
            "angular_damping": cfg.die.angular_damping,
            "collision_margin": cfg.die.collision_margin,
            "collision_shape": cfg.die.collision_shape,
        },
        cfg.table,
    )


def banner_image_key(cfg: PipelineConfig, outcome: int) -> str:
    """The banner PNG depends only on text, font, colors, sizing — and outcome."""
    return _hash(cfg.banner, outcome)


def render_key(cfg: PipelineConfig, outcome: int) -> str:
    """
    Render output depends on EVERYTHING — physics, all materials, lighting,
    camera, banner, audio, render settings, this specific outcome value.
    Effectively: if anything changed, re-render.
    """
    return _hash(
        physics_key(cfg),       # transitively includes physics-relevant inputs
        cfg.die,                # full die config including materials
        cfg.camera,
        cfg.lighting,
        cfg.banner,
        cfg.banner_audio,
        cfg.render,
        outcome,
    )


# ----------------------------------------------------------------------------
# Sidecar file helpers
# ----------------------------------------------------------------------------

def _key_path(output_path: str) -> str:
    return output_path + ".cache_key"


def cache_hit(output_path: str, expected_key: str, force: bool) -> bool:
    """
    Return True if we should SKIP regeneration: the output file exists and
    its sidecar key matches. `force=True` always returns False (forces redo).
    """
    if force:
        return False
    if not os.path.exists(output_path):
        return False
    key_file = _key_path(output_path)
    if not os.path.exists(key_file):
        return False
    try:
        with open(key_file) as fh:
            stored = fh.read().strip()
    except OSError:
        return False
    return stored == expected_key


def write_cache_key(output_path: str, key: str) -> None:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(_key_path(output_path), "w") as fh:
        fh.write(key)


def ensure_cache_dir(cfg: CacheConfig) -> str:
    os.makedirs(cfg.cache_dir, exist_ok=True)
    return cfg.cache_dir
