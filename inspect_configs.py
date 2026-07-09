#!/usr/bin/env python3
"""
Inspect and summarize what each config file does.

Useful for understanding the variations before committing to renders.
"""

import json
import sys
from pathlib import Path


def describe_config(config_path: Path) -> str:
    """Generate a human-readable description of a config file."""
    try:
        with open(config_path) as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        return f"Error reading config: {e}"

    lines = []

    # Die
    if "die" in cfg:
        die = cfg["die"]
        if "body_color" in die:
            color = die["body_color"]
            lines.append(f"  Die color: RGBA{tuple(color)}")
        if "body_roughness" in die:
            lines.append(f"  Die roughness: {die['body_roughness']}")
        if "body_metallic" in die:
            lines.append(f"  Die metallic: {die['body_metallic']}")

    # Table
    if "table" in cfg:
        table = cfg["table"]
        if "color" in table:
            color = table["color"]
            lines.append(f"  Table color: RGBA{tuple(color)}")

    # Lighting
    if "lighting" in cfg:
        light = cfg["lighting"]
        if "key_color" in light and "key_energy" in light:
            color = light["key_color"]
            energy = light["key_energy"]
            lines.append(f"  Key light: {color[:3]} @ {energy}W")
        if "fill_color" in light and "fill_energy" in light:
            color = light["fill_color"]
            energy = light["fill_energy"]
            lines.append(f"  Fill light: {color[:3]} @ {energy}W")
        if "rim_color" in light and "rim_energy" in light:
            color = light["rim_color"]
            energy = light["rim_energy"]
            lines.append(f"  Rim light: {color[:3]} @ {energy}W")

    # Camera
    if "camera" in cfg:
        cam = cfg["camera"]
        if "location" in cam:
            loc = cam["location"]
            lines.append(f"  Camera position: {loc}")
        if "focal_length_mm" in cam:
            lines.append(f"  Focal length: {cam['focal_length_mm']}mm")
        if "dof_enabled" in cam:
            lines.append(f"  Depth of field: {'enabled' if cam['dof_enabled'] else 'disabled'}")

    # Render settings
    if "render" in cfg:
        render = cfg["render"]
        if "output_dir" in render:
            lines.append(f"  Output: {render['output_dir']}")
        if "resolution_percentage" in render:
            lines.append(f"  Resolution scale: {render['resolution_percentage']}%")
        if "samples" in render:
            lines.append(f"  Samples: {render['samples']}")

    # Outcomes
    if "desired_outcomes" in cfg:
        outcomes = cfg["desired_outcomes"]
        lines.append(f"  Outcomes: {outcomes}")

    return "\n".join(lines) if lines else "  (empty config)"


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else "config_*.json"
    configs = sorted(Path(".").glob(pattern))

    if not configs:
        print(f"No configs found matching '{pattern}'")
        return 1

    print(f"📋 Config Summary ({len(configs)} files)\n")

    for config_path in configs:
        print(f"▶ {config_path.name}")
        print(describe_config(config_path))
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
