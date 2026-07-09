"""
Scene assembly: table, lights, camera, and world background.

Each function takes the relevant config sub-section and returns the created
Blender object(s). Functions are idempotent in spirit — they should be called
on a freshly cleared scene (see `clear_scene` in `pipeline.py`).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import bpy

from .config import BowlConfig, CameraConfig, LightingConfig, TableConfig

if TYPE_CHECKING:
    from bpy.types import Object


# ----------------------------------------------------------------------------
# Table
# ----------------------------------------------------------------------------


def build_table(cfg: TableConfig) -> Object:
    """Create the table surface as a passive rigid body."""
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=8, radius=0.5, depth=1.0, location=cfg.location
    )
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

    table.hide_render = not cfg.visible

    if cfg.physics_enabled:
        bpy.ops.rigidbody.object_add()
        table.rigid_body.type = "PASSIVE"
        table.rigid_body.collision_shape = "CONVEX_HULL"
        table.rigid_body.friction = cfg.friction
        table.rigid_body.restitution = cfg.restitution

        if cfg.bumpers_enabled:
            _build_bumpers(cfg, table)

    return table


def _build_bumpers(cfg: TableConfig, table: Object) -> None:
    """Octagonal ring of walls (invisible by default) hugging the table edge.

    The table is an 8-vertex cylinder, so eight walls — one per facet —
    contain the die on every side. Wall mid-planes sit at the octagon's
    apothem, so the ring never lies outside the table polygon regardless of
    the cylinder's vertex phase, and wall bottoms sink to the table's
    mid-plane so there is no gap for the die to slip under.
    """
    sx, sy, sz = cfg.size
    h = cfg.bumpers_height
    t = cfg.bumpers_thickness
    n = 8
    apothem = math.cos(math.pi / n)  # per unit circumradius
    facet = 2.0 * math.tan(math.pi / n)  # facet length per unit circumradius
    for i in range(n):
        ang = (i + 0.5) * (2.0 * math.pi / n)
        cx = cfg.location[0] + 0.5 * sx * apothem * math.cos(ang)
        cy = cfg.location[1] + 0.5 * sy * apothem * math.sin(ang)
        cz = cfg.location[2] + h / 2.0
        # Overlap neighbouring walls at the corners so there are no gaps.
        length = facet * 0.5 * max(sx, sy) + 2.0 * t
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(cx, cy, cz))
        wall = bpy.context.active_object
        wall.name = f"Bumper_{i}"
        wall.scale = (t, length, h)
        # Scale is applied to the mesh; rotation stays on the object so the
        # BOX collision shape follows the wall's local axes.
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        wall.rotation_euler = (0.0, 0.0, ang)

        bpy.ops.rigidbody.object_add()
        wall.rigid_body.type = "PASSIVE"
        wall.rigid_body.collision_shape = "BOX"
        wall.rigid_body.friction = cfg.bumpers_friction
        wall.rigid_body.restitution = cfg.bumpers_restitution

        wall.hide_render = not cfg.bumpers_visible


# ----------------------------------------------------------------------------
# Bowl
# ----------------------------------------------------------------------------


def build_bowl(cfg: BowlConfig) -> "Object":
    """Create a hemispherical bowl as a passive rigid body.

    Concave geometry requires collision_shape=MESH (not CONVEX_HULL, which
    would hull-wrap to a flat disc and let the die pass straight through).
    The rim is positioned at cfg.location; the bowl opens upward.
    """
    import bmesh as _bmesh

    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=cfg.segments,
        ring_count=cfg.segments // 2,
        radius=1.0,
        location=cfg.location,
    )
    obj = bpy.context.active_object
    obj.name = "Bowl"

    # Keep only the lower hemisphere: delete verts at z > 0 (local space).
    bm = _bmesh.new()
    bm.from_mesh(obj.data)
    upper = [v for v in bm.verts if v.co.z > 1e-4]
    _bmesh.ops.delete(bm, geom=upper, context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()

    # Scale unit hemisphere to (radius, radius, depth).
    # After delete: rim at z=0, bottom at z=-1 → scaled to z=-depth.
    obj.scale = (cfg.radius, cfg.radius, cfg.depth)
    bpy.ops.object.transform_apply(scale=True)

    mat = bpy.data.materials.new(name="BowlMaterial")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = cfg.color
    bsdf.inputs["Roughness"].default_value = cfg.roughness
    obj.data.materials.append(mat)

    bpy.ops.rigidbody.object_add()
    obj.rigid_body.type = "PASSIVE"
    obj.rigid_body.collision_shape = "MESH"  # required for concave geometry
    obj.rigid_body.friction = cfg.friction
    obj.rigid_body.restitution = cfg.restitution

    obj.hide_render = not cfg.visible

    return obj


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


def _aim_rotation(loc, aim_at, roll_deg, prev_euler=None):
    """Euler rotation for a camera at `loc` aiming at `aim_at`, with a
    clockwise roll around the view axis. Same world-up convention as the
    TRACK_TO constraint (local +Y toward world +Z), so a roll of 0 reproduces
    the constraint's pose. `prev_euler` keeps successive keys flip-free.
    """
    import mathutils

    view_vec = (aim_at - loc).normalized()
    world_up = mathutils.Vector((0.0, 0.0, 1.0))
    right = view_vec.cross(world_up)
    if right.length < 1e-4:
        right = mathutils.Vector((1.0, 0.0, 0.0))
    right = right.normalized()
    cam_up = right.cross(view_vec).normalized()
    roll_rot = mathutils.Matrix.Rotation(math.radians(roll_deg), 3, view_vec)
    right_r = roll_rot @ right
    up_r = roll_rot @ cam_up
    neg_view = -view_vec
    rot = mathutils.Matrix(
        (
            (right_r.x, up_r.x, neg_view.x),
            (right_r.y, up_r.y, neg_view.y),
            (right_r.z, up_r.z, neg_view.z),
        )
    )
    if prev_euler is not None:
        return rot.to_euler("XYZ", prev_euler)
    return rot.to_euler("XYZ")


def animate_camera_track(die: Object, settle_frame: int, cfg: CameraConfig) -> None:
    """Aim the camera at the die along its baked trajectory.

    With no roll configured, this keyframes the CameraTarget empty and lets
    the TRACK_TO constraint do the aiming. With `orbit_end_roll_deg` set, the
    constraint can't express the roll, so it is disabled and the camera's
    rotation is keyed directly — the roll is constant across the whole shot
    (invisible against the void background), which is what makes the settled
    face read right-side-up without any on-screen rotation later.

    Sampling every 3rd frame lets bezier interpolation smooth out bounce
    jitter. Stops at the settle frame; `animate_camera_orbit` continues from
    there, and the die's settle position makes the handoff continuous.
    """
    target = bpy.data.objects.get("CameraTarget")
    cam = bpy.context.scene.camera
    if target is None or cam is None:
        from . import log

        log.info("camera.track: no CameraTarget/camera found; skipping")
        return

    roll = cfg.orbit_end_roll_deg
    if roll != 0.0:
        track = next((c for c in cam.constraints if c.type == "TRACK_TO"), None)
        if track:
            track.influence = 0.0

    scene = bpy.context.scene
    frames = list(range(scene.frame_start, settle_frame + 1, 3))
    if frames[-1] != settle_frame:
        frames.append(settle_frame)
    prev_euler = None
    for f in frames:
        scene.frame_set(f)
        die_pos = die.matrix_world.translation.copy()
        target.location = die_pos
        target.keyframe_insert(data_path="location", frame=f)
        if roll != 0.0:
            prev_euler = _aim_rotation(cam.location, die_pos, roll, prev_euler)
            cam.rotation_euler = prev_euler
            cam.keyframe_insert(data_path="rotation_euler", frame=f)


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

    # Roll: the roll is constant across the whole shot (applied per-frame by
    # `animate_camera_track` before the orbit begins), so here we only keep
    # aiming at the settled die with the same roll while the camera glides.
    # The aim point never moves during the glide — only the camera does.
    if cfg.orbit_end_roll_deg != 0.0:
        track = next((c for c in cam.constraints if c.type == "TRACK_TO"), None)
        if track:
            track.influence = 0.0
        scene = bpy.context.scene
        scene.frame_set(start_f)
        prev_euler = cam.rotation_euler.copy()
        key_frames = list(range(start_f, arrive_f + 1, 2))
        if key_frames[-1] != arrive_f:
            key_frames.append(arrive_f)
        for f in key_frames:
            scene.frame_set(f)
            prev_euler = _aim_rotation(
                cam.location.copy(), die_pos, cfg.orbit_end_roll_deg, prev_euler
            )
            cam.rotation_euler = prev_euler
            cam.keyframe_insert(data_path="rotation_euler", frame=f)
        # Hold the final pose through the hold segment.
        cam.keyframe_insert(data_path="rotation_euler", frame=end_f)
        log.debug(
            f"camera.orbit: constant roll={cfg.orbit_end_roll_deg}° held over frames "
            f"{start_f}..{end_f}"
        )
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

    if cfg.top_enabled:
        _add_light(
            "TopLight",
            "AREA",
            cfg.top_location,
            cfg.top_rotation_euler,
            cfg.top_color,
            cfg.top_energy,
            size=cfg.top_size,
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
