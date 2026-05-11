"""
Scene assembly: table, lights, camera, and world background.

Each function takes the relevant config sub-section and returns the created
Blender object(s). Functions are idempotent in spirit — they should be called
on a freshly cleared scene (see `clear_scene` in `pipeline.py`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from .config import CameraConfig, LightingConfig, TableConfig

if TYPE_CHECKING:
    from bpy.types import Object


# ----------------------------------------------------------------------------
# Table
# ----------------------------------------------------------------------------


def build_table(cfg: TableConfig) -> Object:
    """Create the table surface as a passive rigid body."""
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=cfg.location)
    table = bpy.context.active_object
    table.name = "Table"
    table.scale = (cfg.size[0], cfg.size[1], cfg.size[2])
    table.rotation_euler = cfg.rotation_euler
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    # Material
    mat = bpy.data.materials.new(name="TableMaterial")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = cfg.color
    bsdf.inputs["Roughness"].default_value = cfg.roughness
    # NOTE: hooking up cfg.texture_path / cfg.normal_map_path would add image
    # texture nodes here. Left as TODO for brevity.
    table.data.materials.append(mat)

    # Rigid body (passive — does not move)
    bpy.ops.rigidbody.object_add()
    table.rigid_body.type = "PASSIVE"
    table.rigid_body.collision_shape = "BOX"
    table.rigid_body.friction = cfg.friction
    table.rigid_body.restitution = cfg.restitution

    if cfg.bumpers_enabled:
        _build_bumpers(cfg, table)

    return table


def _build_bumpers(cfg: TableConfig, table: Object) -> None:
    """Four invisible (or visible) walls around the table edge."""
    sx, sy, sz = cfg.size
    h = cfg.bumpers_height
    # Each wall is a thin box positioned at one edge of the table.
    walls = [
        ("Bumper_N", (0, sy/2, sz + h / 2), (sx, 0.005, h)),
        ("Bumper_S", (0, -sy/2, sz + h / 2), (sx, 0.005, h)),
        ("Bumper_E", (sx/2, 0, sz + h / 2), (0.005, sy, h)),
        ("Bumper_W", (-sx/2, 0, sz + h / 2), (0.005, sy, h)),
    ]
    for name, loc, scale in walls:
        bpy.ops.mesh.primitive_cube_add(
            size=1.0,
            location=(
                cfg.location[0] + loc[0],
                cfg.location[1] + loc[1],
                cfg.location[2] + loc[2],
            ),
        )
        wall = bpy.context.active_object
        wall.name = name
        wall.scale = scale
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

        bpy.ops.rigidbody.object_add()
        wall.rigid_body.type = "PASSIVE"
        wall.rigid_body.collision_shape = "BOX"
        wall.rigid_body.friction = cfg.bumpers_friction
        wall.rigid_body.restitution = cfg.bumpers_restitution

        wall.hide_render = not cfg.bumpers_visible


# ----------------------------------------------------------------------------
# Camera
# ----------------------------------------------------------------------------


def build_camera(cfg: CameraConfig) -> Object:
    bpy.ops.object.camera_add(location=cfg.location)
    cam = bpy.context.active_object
    cam.name = "Camera"
    cam.data.lens = cfg.focal_length_mm
    cam.data.sensor_width = cfg.sensor_width_mm

    # Aim the camera using a tracking constraint on an empty at look_at.
    bpy.ops.object.empty_add(location=cfg.look_at)
    target = bpy.context.active_object
    target.name = "CameraTarget"

    constraint = cam.constraints.new(type="TRACK_TO")
    constraint.target = target
    constraint.track_axis = "TRACK_NEGATIVE_Z"
    constraint.up_axis = "UP_Y"

    if cfg.dof_enabled:
        cam.data.dof.use_dof = True
        cam.data.dof.aperture_fstop = cfg.dof_fstop
        # focus_object hookup deferred to after die exists; pipeline.py wires it.

    bpy.context.scene.camera = cam
    return cam


def animate_camera_orbit(
    cam: Object,
    die: Object,
    settle_frame: int,
    up_face_world_normal,
    cfg: CameraConfig,
) -> int:
    """Keyframe a smooth move from the camera's start pose to a top-down close-up
    of the settled die's up face. Returns the frame at which the orbit ends
    (orbit-arrive + hold), so the caller can clip render frame_end accordingly.

    The camera is constrained to TRACK_TO the `CameraTarget` empty (built by
    `build_camera`); we keyframe both the camera location and the target
    location so the camera glides while continuously aiming at the die.
    """
    from . import log

    target = bpy.data.objects.get("CameraTarget")
    if target is None:
        log.info("camera.orbit: no CameraTarget empty found; skipping")
        return settle_frame

    import math

    import mathutils

    die_pos = die.matrix_world.translation.copy()
    up_n = up_face_world_normal.normalized()

    start_f = settle_frame + cfg.orbit_start_offset_frames
    arrive_f = start_f + cfg.orbit_duration_frames
    end_f = arrive_f + cfg.orbit_hold_frames

    # End pose: camera at `orbit_end_distance` from die center, tilted
    # `orbit_end_tilt_deg` off straight-down toward where it started.
    # This keeps a few face edges visible and avoids the dead-black top-down look.
    tilt_rad = math.radians(cfg.orbit_end_tilt_deg)
    horiz = cam.location.copy() - die_pos
    horiz.z = 0.0
    horiz_len = horiz.length
    if horiz_len > 1e-4:
        horiz_dir = horiz / horiz_len
    else:
        horiz_dir = mathutils.Vector((1.0, 0.0, 0.0))
    tilt_dir = (up_n * math.cos(tilt_rad) + horiz_dir * math.sin(tilt_rad)).normalized()
    end_cam_loc = die_pos + tilt_dir * cfg.orbit_end_distance

    # Start pose: keyframe the camera's *current* values so it freezes in place
    # until the orbit begins.
    start_cam_loc = cam.location.copy()
    start_target_loc = target.location.copy()

    cam.location = start_cam_loc
    cam.keyframe_insert(data_path="location", frame=start_f)
    target.location = start_target_loc
    target.keyframe_insert(data_path="location", frame=start_f)

    cam.location = end_cam_loc
    cam.keyframe_insert(data_path="location", frame=arrive_f)
    target.location = die_pos
    target.keyframe_insert(data_path="location", frame=arrive_f)

    # Hold: same values at end_f so motion fully comes to rest.
    cam.keyframe_insert(data_path="location", frame=end_f)
    target.keyframe_insert(data_path="location", frame=end_f)

    # Roll: rotate the camera around its viewing axis at the orbit end pose.
    # TRACK_TO handles pointing during the glide; at arrive_f we fade it out
    # and take over with a manually computed rotation that includes the roll.
    if cfg.orbit_end_roll_deg != 0.0:
        track = next((c for c in cam.constraints if c.type == "TRACK_TO"), None)
        if track:
            # Hold at full influence through the glide, snap off at arrive_f.
            track.influence = 1.0
            track.keyframe_insert(data_path="influence", frame=arrive_f - 1)
            track.influence = 0.0
            track.keyframe_insert(data_path="influence", frame=arrive_f)
            track.keyframe_insert(data_path="influence", frame=end_f)
            # Make the pre-arrive keyframe constant so it snaps rather than fading.
            if cam.animation_data and cam.animation_data.action:
                fcurves = getattr(cam.animation_data.action, "fcurves", None)
                if fcurves:
                    for fc in fcurves:
                        if "influence" in fc.data_path:
                            for kp in fc.keyframe_points:
                                if abs(kp.co.x - (arrive_f - 1)) < 0.5:
                                    kp.interpolation = "CONSTANT"

        # Compute pointing direction from end camera location to die.
        view_vec = (die_pos - end_cam_loc).normalized()
        world_up = mathutils.Vector((0.0, 0.0, 1.0))
        right = view_vec.cross(world_up)
        if right.length < 1e-4:
            right = mathutils.Vector((1.0, 0.0, 0.0))
        right = right.normalized()
        cam_up = right.cross(view_vec).normalized()

        # Apply clockwise roll (positive = CW when looking toward die).
        roll_rot = mathutils.Matrix.Rotation(math.radians(cfg.orbit_end_roll_deg), 3, view_vec)
        right_r = roll_rot @ right
        up_r = roll_rot @ cam_up
        neg_view = -view_vec

        # Build rotation matrix: columns are (right, up, -view) in world space.
        rot = mathutils.Matrix(
            (
                (right_r.x, up_r.x, neg_view.x),
                (right_r.y, up_r.y, neg_view.y),
                (right_r.z, up_r.z, neg_view.z),
            )
        )
        cam.rotation_euler = rot.to_euler()
        cam.keyframe_insert(data_path="rotation_euler", frame=arrive_f)
        cam.keyframe_insert(data_path="rotation_euler", frame=end_f)
        log.debug(f"camera.orbit: roll={cfg.orbit_end_roll_deg}° applied at frame {arrive_f}")

    log.debug(
        f"camera.orbit: start_f={start_f} arrive_f={arrive_f} end_f={end_f}; "
        f"end_loc={tuple(round(x, 4) for x in end_cam_loc)} "
        f"target={tuple(round(x, 4) for x in die_pos)}"
    )
    return end_f


# ----------------------------------------------------------------------------
# Lighting
# ----------------------------------------------------------------------------


def build_lighting(cfg: LightingConfig) -> None:
    if cfg.key_enabled:
        _add_light(
            "KeyLight",
            cfg.key_type,
            cfg.key_location,
            cfg.key_rotation_euler,
            cfg.key_color,
            cfg.key_energy,
            size=cfg.key_size,
        )

    if cfg.fill_enabled:
        _add_light(
            "FillLight",
            "AREA",
            cfg.fill_location,
            (0.6, 0.0, 0.0),
            cfg.fill_color,
            cfg.fill_energy,
            size=0.6,
        )

    if cfg.rim_enabled:
        _add_light(
            "RimLight",
            "AREA",
            cfg.rim_location,
            (-0.4, 0.0, 0.0),
            cfg.rim_color,
            cfg.rim_energy,
            size=0.3,
        )

    _setup_world(cfg)


def _add_light(name, light_type, location, rotation, color, energy, size=0.5):
    bpy.ops.object.light_add(type=light_type, location=location, rotation=rotation)
    light = bpy.context.active_object
    light.name = name
    light.data.color = color[:3]
    light.data.energy = energy
    if light_type == "AREA":
        light.data.size = size


def _setup_world(cfg: LightingConfig) -> None:
    """Background: HDRI if path provided, otherwise a flat color."""
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputWorld")
    bg = nodes.new("ShaderNodeBackground")
    links.new(bg.outputs["Background"], output.inputs["Surface"])

    if cfg.hdri_path:
        env = nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(cfg.hdri_path)
        mapping = nodes.new("ShaderNodeMapping")
        tex_coord = nodes.new("ShaderNodeTexCoord")
        mapping.inputs["Rotation"].default_value[2] = cfg.hdri_rotation_z
        links.new(tex_coord.outputs["Generated"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], env.inputs["Vector"])
        links.new(env.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = cfg.hdri_strength
    else:
        bg.inputs["Color"].default_value = cfg.background_color
        bg.inputs["Strength"].default_value = cfg.background_strength
