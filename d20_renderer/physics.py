"""
Physics simulation control:
  - Set world-level gravity, substeps, solver iterations
  - Apply the initial throw (position, rotation, velocities) to the die
  - Bake the rigid body cache for deterministic re-rendering
  - After bake, identify the frame at which the die settles, and which face
    is pointing up at that frame
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Tuple

import bpy
from mathutils import Vector, Euler

from .config import PhysicsConfig
from .die import get_face_centers_and_normals
from . import log

if TYPE_CHECKING:
    from bpy.types import Object


def configure_world(cfg: PhysicsConfig) -> None:
    """Set scene-level physics parameters."""
    scene = bpy.context.scene

    # Ensure the rigid body world exists
    if scene.rigidbody_world is None:
        bpy.ops.rigidbody.world_add()

    rbw = scene.rigidbody_world
    rbw.enabled = True
    rbw.substeps_per_frame = cfg.substeps_per_frame
    rbw.solver_iterations = cfg.solver_iterations

    # Gravity
    scene.gravity = cfg.gravity

    # Frame range
    scene.frame_start = 1
    scene.frame_end = cfg.max_simulation_frames
    rbw.point_cache.frame_start = 1
    rbw.point_cache.frame_end = cfg.max_simulation_frames


def apply_initial_throw(die: "Object", cfg: PhysicsConfig) -> None:
    """
    Place the die at its initial position/rotation and assign initial linear
    and angular velocity. Velocities must be keyframed at frame 1 because
    Blender's rigid body system only reads them at the start of simulation.
    """
    scene = bpy.context.scene
    scene.frame_set(1)

    die.location = cfg.initial_position
    die.rotation_mode = "XYZ"
    die.rotation_euler = Euler(cfg.initial_rotation_euler, "XYZ")

    # Keyframe transform at frame 1 so the pose is locked in
    die.keyframe_insert(data_path="location", frame=1)
    die.keyframe_insert(data_path="rotation_euler", frame=1)

    # Initial velocities live on the rigid_body_object, but Blender doesn't
    # expose them directly via Python in older versions. The portable trick:
    # animate the die's location/rotation for one frame to imply velocity,
    # OR set rb.kinematic=True for frame 1 with keyframes, then disable.
    # The cleanest modern path is to use the rigid body's `deactivate` and
    # animation_data on the rb fields. Here we use an animation-driven
    # velocity injection: keyframe at frame 1 and frame 2 with displaced
    # position so the solver picks up the implied velocity.
    fps = scene.render.fps
    dt = 1.0 / fps
    log.debug(f"physics.throw: pos={cfg.initial_position}, rot={cfg.initial_rotation_euler}, "
              f"linear_v={cfg.initial_linear_velocity}, angular_v={cfg.initial_angular_velocity}, "
              f"fps={fps}, dt={dt:.4f}")
    next_pos = Vector(cfg.initial_position) + Vector(cfg.initial_linear_velocity) * dt
    # We need the die kinematic for frame 1 -> 2 to drive it, then release.
    rb = die.rigid_body
    rb.kinematic = True
    rb.keyframe_insert(data_path="kinematic", frame=1)

    die.location = next_pos
    rot = Euler(cfg.initial_rotation_euler, "XYZ")
    rot.x += cfg.initial_angular_velocity[0] * dt
    rot.y += cfg.initial_angular_velocity[1] * dt
    rot.z += cfg.initial_angular_velocity[2] * dt
    die.rotation_euler = rot
    die.keyframe_insert(data_path="location", frame=2)
    die.keyframe_insert(data_path="rotation_euler", frame=2)

    # Frame 3: release — kinematic off, solver takes over and infers velocity
    # from the frame 1->2 keyframe delta.
    rb.kinematic = False
    rb.keyframe_insert(data_path="kinematic", frame=3)


def bake_simulation(cfg: PhysicsConfig) -> None:
    """Bake the rigid body cache to disk."""
    if not cfg.bake_cache:
        return
    bpy.ops.ptcache.bake_all(bake=True)


# ----------------------------------------------------------------------------
# Settle detection
# ----------------------------------------------------------------------------

def find_settle_frame(die: "Object", cfg: PhysicsConfig) -> int:
    """
    Step through baked frames and find the first frame at which the die has
    been "still" for `settle_required_frames` consecutive frames.

    "Still" is measured by comparing positions/rotations across frames and
    requiring the per-frame delta to fall below `settle_velocity_threshold`.
    """
    scene = bpy.context.scene
    fps = scene.render.fps
    threshold = cfg.settle_velocity_threshold
    required = cfg.settle_required_frames

    prev_loc: Optional[Vector] = None
    prev_rot: Optional[Vector] = None
    quiet_streak = 0
    settle_frame: Optional[int] = None

    for f in range(1, cfg.max_simulation_frames + 1):
        scene.frame_set(f)
        loc = die.matrix_world.translation.copy()
        rot = Vector(die.matrix_world.to_euler())

        if prev_loc is not None:
            dloc = (loc - prev_loc).length * fps              # ~m/s
            drot = (rot - prev_rot).length * fps              # ~rad/s
            if dloc < threshold and drot < threshold:
                quiet_streak += 1
                if quiet_streak >= required:
                    settle_frame = f
                    break
            else:
                quiet_streak = 0

        prev_loc = loc
        prev_rot = rot

    if settle_frame is None:
        # Fallback: assume settled at the end of the cap
        log.debug(f"physics.settle: never reached threshold={threshold} for {required} consec frames; "
                  f"falling back to max_simulation_frames={cfg.max_simulation_frames}")
        settle_frame = cfg.max_simulation_frames
    else:
        log.debug(f"physics.settle: settled at frame {settle_frame} "
                  f"(threshold={threshold}, required_streak={required})")
    return settle_frame


def find_up_face(die: "Object", at_frame: int) -> int:
    """
    Return the polygon index of the face whose world-space normal is most
    aligned with +Z at the given frame.
    """
    scene = bpy.context.scene
    scene.frame_set(at_frame)

    rot_3x3 = die.matrix_world.to_3x3()
    best_idx = -1
    best_dot = -2.0
    candidates: list = []
    for face_idx, _center, normal_local in get_face_centers_and_normals(die):
        world_normal = rot_3x3 @ normal_local
        d = world_normal.z
        candidates.append((face_idx, d))
        if d > best_dot:
            best_dot = d
            best_idx = face_idx
    candidates.sort(key=lambda x: x[1], reverse=True)
    log.debug(f"physics.up_face@frame{at_frame}: scanned {len(candidates)} faces; "
              f"top 3 (idx, +Z dot) = {[(i, round(d, 4)) for i, d in candidates[:3]]}; "
              f"picked face={best_idx}")
    return best_idx
