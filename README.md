# Example configs

Use any of these as a starting point with `make render CONFIG=examples/<name>.json`.

| File | Purpose |
|------|---------|
| `minimal.json` | Bare minimum — just sets the desired outcome. Useful as a template. |
| `preview.json` | Fast Eevee preview at 540p. Use when iterating on physics or lighting. Not final-quality. |
| `crit_hit.json` | Dramatic dark-resin die with banner + audio. Demonstrates per-outcome sound mapping. |
| `transparent_resin.json` | Classic translucent purple resin look. No banner. |

## Notes

- Audio paths in `crit_hit.json` are placeholders. Replace with real `.wav` /
  `.ogg` files before rendering.
- Any field omitted from a config inherits the default in `d20_renderer/config.py`.
- Configs only support the same dataclass tree shape — see `PipelineConfig`
  for the full list of valid keys.
- The `_comment` field is ignored by the loader. Use it freely for inline notes.
