"""One-shot diagnostic: build the die scene exactly like the pipeline, advance
to settle frame, and dump enough geometry to tell why find_up_face is reporting
near-zero dot products.

Run:  blender --background --python-use-system-env --python scripts/probe_die.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bpy
from mathutils import Vector

from d20_renderer import config, scene as scene_mod, physics as physics_mod, die as die_mod

cfg = config.PipelineConfig()

# Mirror pipeline.run setup
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
scene_mod.build_table(cfg.table)
scene_mod.build_lighting(cfg.lighting)
scene_mod.build_camera(cfg.camera)
die = die_mod.build_die(cfg.die, with_labels=True)
physics_mod.configure_world(cfg.physics)
physics_mod.apply_initial_throw(die, cfg.physics)
physics_mod.bake_simulation(cfg.physics)

print("\n=== mesh state ===")
print(f"polygons: {len(die.data.polygons)}")
print(f"vertices: {len(die.data.vertices)}")

settle = physics_mod.find_settle_frame(die, cfg.physics)
print(f"\nsettle frame: {settle}")
bpy.context.scene.frame_set(settle)

print(f"\n=== die transform at frame {settle} ===")
print(f"location: {die.matrix_world.translation}")
print(f"euler:    {die.matrix_world.to_euler()}")
print(f"scale:    {die.matrix_world.to_scale()}")
print(f"matrix_world.to_3x3():\n{die.matrix_world.to_3x3()}")

print("\n=== first 3 face polygons (raw mesh data) ===")
for poly in list(die.data.polygons)[:3]:
    print(f"  idx={poly.index} center={poly.center} normal={poly.normal} normal_len={poly.normal.length:.4f}")

print("\n=== applying world rotation manually ===")
rot_3x3 = die.matrix_world.to_3x3()
for poly in list(die.data.polygons)[:5]:
    if poly.index >= 20:
        continue
    wn = rot_3x3 @ poly.normal
    print(f"  face {poly.index}: local_n={tuple(round(x,3) for x in poly.normal)} "
          f"world_n={tuple(round(x,3) for x in wn)} world_n.z={wn.z:.4f}")

print("\n=== ALL 20 face world-space normals (sorted by .z desc) ===")
all_world = []
for poly in die.data.polygons:
    if poly.index >= 20:
        continue
    wn = rot_3x3 @ poly.normal
    all_world.append((poly.index, wn.z, wn))
all_world.sort(key=lambda t: t[1], reverse=True)
for idx, z, wn in all_world:
    print(f"  face {idx:2d}  z={z:+.4f}  world_n={tuple(round(x,3) for x in wn)}")

print("\n=== matrix_world (full 4x4) ===")
print(die.matrix_world)

print("\n=== LABEL world positions (z desc) — should reveal true up face ===")
labels = sorted(
    [c for c in die.children if c.name.startswith("DieLabel_")],
    key=lambda lbl: lbl.matrix_world.translation.z,
    reverse=True,
)
die_centroid = die.matrix_world.translation
for lbl in labels:
    pos = lbl.matrix_world.translation
    # Vector from die centroid to label = the face's outward direction
    face_dir = (pos - die_centroid).normalized()
    print(f"  {lbl.name} body={lbl.data.body!r:>5}  "
          f"world_pos=({pos.x:+.3f},{pos.y:+.3f},{pos.z:+.3f})  "
          f"face_dir.z={face_dir.z:+.4f}")
