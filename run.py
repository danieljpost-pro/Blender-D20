"""
CLI entry point.

Usage
-----
    blender --background --python -m d20_renderer.run -- \
        --outcomes 1 5 13 20 \
        --output-dir ./renders

Or, with a JSON config file overriding defaults:

    blender --background --python -m d20_renderer.run -- \
        --config my_config.json

Arguments after `--` are passed to this script (Blender-convention).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, fields, is_dataclass

# When running via `blender --python`, the package import works only if the
# parent directory of `d20_renderer/` is on sys.path. Adjust if needed.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_THIS_DIR)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from d20_renderer.config import PipelineConfig  # noqa: E402
from d20_renderer.pipeline import run            # noqa: E402


def _parse_args() -> argparse.Namespace:
    # Blender swallows args before `--`; everything after `--` is ours.
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    p = argparse.ArgumentParser(description="Render D20 roll videos.")
    p.add_argument("--config", type=str, default=None,
                   help="Path to a JSON file with overrides for PipelineConfig.")
    p.add_argument("--outcomes", type=int, nargs="+", default=None,
                   help="List of desired outcomes (1-20).")
    p.add_argument("--output-dir", type=str, default=None,
                   help="Directory for rendered videos.")
    return p.parse_args(argv)


def _apply_overrides(cfg: PipelineConfig, overrides: dict) -> PipelineConfig:
    """Recursively apply a dict of overrides onto a dataclass tree."""
    def merge(obj, ov):
        if not is_dataclass(obj) or not isinstance(ov, dict):
            return
        for f in fields(obj):
            if f.name not in ov:
                continue
            cur = getattr(obj, f.name)
            new = ov[f.name]
            if is_dataclass(cur) and isinstance(new, dict):
                merge(cur, new)
            else:
                setattr(obj, f.name, new)
    merge(cfg, overrides)
    return cfg


def main() -> None:
    args = _parse_args()
    cfg = PipelineConfig()

    if args.config:
        with open(args.config) as fh:
            cfg = _apply_overrides(cfg, json.load(fh))

    if args.outcomes:
        cfg.desired_outcomes = args.outcomes
    if args.output_dir:
        cfg.render.output_dir = args.output_dir

    run(cfg)


if __name__ == "__main__":
    main()
