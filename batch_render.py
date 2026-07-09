#!/usr/bin/env python3
"""
Batch render script to render multiple config files into separate output directories.

Usage:
    python batch_render.py [pattern] [options]

Examples:
    python batch_render.py config_*.json
    python batch_render.py config_*.json --no-simulate
    python batch_render.py config_*.json --dry-run
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional


def find_configs(pattern: str) -> list[Path]:
    """Find all config files matching the pattern."""
    matches = list(Path(".").glob(pattern))
    return sorted(matches)


def get_output_dir(config_path: Path) -> Optional[str]:
    """Extract output_dir from a config file, or None if not specified."""
    try:
        with open(config_path) as f:
            config = json.load(f)
            return config.get("render", {}).get("output_dir")
    except (json.JSONDecodeError, IOError) as e:
        print(f"  ⚠ Failed to read {config_path}: {e}", file=sys.stderr)
        return None


def run_render(config_path: Path, extra_args: list[str]) -> bool:
    """Run the render pipeline for a single config. Returns True on success."""
    output_dir = get_output_dir(config_path)
    display_name = output_dir or config_path.stem

    print(f"\n{'='*60}")
    print(f"  🎲 {display_name}")
    print(f"{'='*60}")

    cmd = [
        "blender",
        "--background",
        "--python-use-system-env",
        "--python",
        "d20_renderer/run.py",
        "--",
        "--config",
        str(config_path),
    ] + extra_args

    try:
        result = subprocess.run(cmd, check=False)
        if result.returncode == 0:
            print(f"  ✓ Render complete")
            return True
        else:
            print(f"  ✗ Render failed with exit code {result.returncode}", file=sys.stderr)
            return False
    except FileNotFoundError:
        print(f"  ✗ blender not found on PATH", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  ✗ Error: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Batch render multiple D20 configs into separate directories."
    )
    parser.add_argument(
        "pattern",
        nargs="?",
        default="config_*.json",
        help="Glob pattern for config files (default: config_*.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would render without actually rendering",
    )
    parser.add_argument(
        "--no-simulate",
        action="store_true",
        help="Skip physics simulation, reuse cached physics",
    )
    parser.add_argument(
        "--force-all",
        action="store_true",
        help="Force re-bake physics and re-render everything",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    # Find all matching configs
    configs = find_configs(args.pattern)

    if not configs:
        print(f"No configs found matching '{args.pattern}'", file=sys.stderr)
        return 1

    print(f"\n📋 Found {len(configs)} config(s) to render:")
    for cfg in configs:
        output_dir = get_output_dir(cfg)
        display = output_dir or cfg.stem
        print(f"   • {display} ({cfg.name})")

    # Build extra arguments
    extra_args = []
    if args.dry_run:
        extra_args.append("--dry-run")
    if args.no_simulate:
        extra_args.append("--no-simulate")
    if args.force_all:
        extra_args.append("--force-all")
    if args.verbose:
        extra_args.append("--verbose")

    # Render each config
    results = []
    for i, config_path in enumerate(configs, 1):
        print(f"\n[{i}/{len(configs)}]", end=" ")
        success = run_render(config_path, extra_args)
        results.append((config_path.name, success))

    # Summary
    print(f"\n{'='*60}")
    print("📊 Summary")
    print(f"{'='*60}")
    passed = sum(1 for _, ok in results if ok)
    failed = len(results) - passed
    for name, ok in results:
        symbol = "✓" if ok else "✗"
        print(f"  {symbol} {name}")
    print(f"\n  Passed: {passed}/{len(results)}")
    if failed > 0:
        print(f"  Failed: {failed}/{len(results)}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
