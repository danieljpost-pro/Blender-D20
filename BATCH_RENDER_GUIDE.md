# Batch Render Guide

This guide explains how to use the batch rendering system for experimenting with different camera angles, materials, colors, and lighting setups.

## Quick Start

### 1. Inspect all configs

See what each config file does without rendering:

```bash
make inspect-configs
```

This shows:
- Die color and material properties
- Table/surface appearance
- Lighting setup (key, fill, rim)
- Camera position and focal length
- Output directory
- Resolution and sample count

### 2. Render all configs

Create separate output directories and render each config:

```bash
make batch-render
```

This will:
- Find all `config_*.json` files
- Render each one to its own `./renders/<config_name>` directory
- Display progress for each config
- Show a summary when done

### 3. Render a subset

Use a pattern to render specific configs:

```bash
# Just dramatic lighting configs
make batch-render PATTERN='config_dramatic_*.json'

# Camera angle experiments
make batch-render PATTERN='config_*_angle*.json'
```

## Available Configs

The repository includes several example configs demonstrating different visual approaches:

| Config | Focus | Output Dir |
|--------|-------|-----------|
| `config_dramatic_blue_yellow.json` | Blue/yellow 3-point lighting on gold die | `./renders/dramatic_blue_yellow` |
| `config_purple_cool.json` | Cool purple die with cyan-blue lighting | `./renders/purple_cool` |
| `config_rose_gold_warm.json` | Metallic rose gold with warm orange lighting | `./renders/rose_gold_warm` |
| `config_high_angle.json` | Bright 3-point, high camera position, no DOF | `./renders/high_angle_bright` |
| `config_low_angle_dramatic.json` | Red die with strong red/white rim lighting, low angle | `./renders/low_angle_dramatic` |

## Creating Your Own Config

Copy an existing config and modify it:

```bash
cp config_dramatic_blue_yellow.json my_experiment.json
```

Edit `my_experiment.json` and change:

### Die appearance:
```json
{
  "die": {
    "body_color": [0.2, 0.8, 0.3, 1.0],    // RGBA (0–1 range)
    "body_roughness": 0.25,                 // 0 = mirror, 1 = matte
    "body_metallic": 0.5                    // 0 = plastic, 1 = metal
  }
}
```

### Lighting:
```json
{
  "lighting": {
    "key_color": [1.0, 0.5, 0.2, 1.0],     // Main light color (warm orange)
    "key_energy": 40.0,                     // Brightness (watts)
    "fill_color": [0.3, 0.5, 0.8, 1.0],    // Secondary light (cool blue)
    "fill_energy": 12.0,
    "rim_color": [1.0, 1.0, 1.0, 1.0],     // Back/edge light (white)
    "rim_energy": 35.0
  }
}
```

### Camera:
```json
{
  "camera": {
    "location": [0.1, -0.2, 0.4],          // X, Y, Z position
    "focal_length_mm": 50.0,                // 28 = wide, 50 = normal, 85 = tight
    "dof_enabled": true,
    "dof_fstop": 2.0                        // Lower = more blur, higher = sharper
  }
}
```

### Output:
```json
{
  "render": {
    "output_dir": "./renders/my_experiment",
    "resolution_percentage": 50,            // 25/50/75/100 — use 50 for fast iteration
    "samples": 32                           // Higher = less noise, longer render
  }
}
```

## Workflow Example

1. **Inspect and iterate quickly** (50% res, 32 samples):
   ```bash
   # See what all experiments look like
   make inspect-configs
   
   # Render them fast
   make batch-render PATTERN='config_*.json'
   ```

2. **Fine-tune one config**:
   ```bash
   # Render just your favorite at full quality
   make render CONFIG=config_dramatic_blue_yellow.json
   ```

3. **Final render at production quality**:
   ```bash
   # Full res, 128+ samples, Cycles with all features
   make render-all CONFIG=config_dramatic_blue_yellow.json
   ```

## Tips

- **Color space**: Use RGBA values in 0–1 range. Examples:
  - Pure red: `[1.0, 0.0, 0.0, 1.0]`
  - Dark gray: `[0.1, 0.1, 0.1, 1.0]`
  - Light cyan: `[0.7, 1.0, 1.0, 1.0]`

- **Lighting energy**: Start with key=30–50, fill=10–20, rim=30–50. Adjust to taste.

- **Camera focal length**:
  - 28mm = wide, more die in frame
  - 35–50mm = standard
  - 85mm = tight close-up

- **Resolution percentage**: Use 50% or 25% during iteration, 100% for final renders.

- **Samples**: 32 is usually enough to see the look; 128+ for production.

- **Reuse physics**: Once you have a physics cache from one render, all other configs using the same `config_dark_green_d20.json` physics will reuse it:
  ```bash
  make batch-render --no-simulate
  ```
  This skips the 2+ minute physics bake and just does render passes (60s per outcome).

## Cache Architecture

Each config stores its **rendered videos** in its own output directory, but **physics is shared** based on the die/table/physics config — not per-outcome but per-simulation setup.

- First render of any config: bakes physics (~2 min) + renders all outcomes (~60s per outcome)
- Subsequent renders with same physics: reuse cache (~60s per outcome)
- Different die materials/colors: reuse cache (only render differs)
- Different table/physics: must re-bake physics

This is by design — see `CLAUDE.md` for the physics architecture.

## Troubleshooting

**Blender not found:**
```bash
# Set custom Blender path
make batch-render EXTRA_FLAGS="--blender=/path/to/blender"
# Or set env var:
export BLENDER=/Applications/Blender.app/Contents/MacOS/Blender
make batch-render
```

**Out of disk space:**
- Each rendered outcome is ~50–100MB (video depends on codec/bitrate)
- 5 configs × 20 outcomes = 100 videos = ~5–10GB total
- Use `make clean-renders` to delete outputs and keep cache

**Render is slow:**
- Reduce samples: `make batch-render EXTRA_FLAGS='--samples 8'`
- Reduce resolution: `make batch-render EXTRA_FLAGS='--resolution-percent 25'`
- Skip simulation: `make batch-render EXTRA_FLAGS='--no-simulate'` (if physics hasn't changed)

**Physics changed, need to re-bake:**
```bash
make batch-render EXTRA_FLAGS='--force-physics'
```
