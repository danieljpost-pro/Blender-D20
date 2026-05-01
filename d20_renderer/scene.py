"""
Scene assembly: table, lights, camera, and world background.

Each function takes the relevant config sub-section and returns the created
Blender object(s). Functions are idempotent in spirit — they should be called
on a freshly cleared scene (see `clear_scene` in `pipeline.py`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from .config import TableConfig, CameraConfig, LightingConfig

if TYPE_CHECKING:
    from bpy.types import Object


# ----------------------------------------------------------------------------
# Table
# ----------------------------------------------------------------------------

def build_table(cfg: TableConfig) -> "Object":
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


def _build_bumpers(cfg: TableConfig, table: "Object") -> None:
    """Four invisible (or visible) walls around the table edge."""
    sx, sy, sz = cfg.size
    h = cfg.bumpers_height
    # Each wall is a thin box positioned at one edge of the table.
    walls = [
        ("Bumper_N", (0,  sy, sz + h / 2), (sx, 0.005, h)),
        ("Bumper_S", (0, -sy, sz + h / 2), (sx, 0.005, h)),
        ("Bumper_E", ( sx, 0, sz + h / 2), (0.005, sy, h)),
        ("Bumper_W", (-sx, 0, sz + h / 2), (0.005, sy, h)),
    ]
    for name, loc, scale in walls:
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(
            cfg.location[0] + loc[0],
            cfg.location[1] + loc[1],
            cfg.location[2] + loc[2],
        ))
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

def build_camera(cfg: CameraConfig) -> "Object":
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


# ----------------------------------------------------------------------------
# Lighting
# ----------------------------------------------------------------------------

def build_lighting(cfg: LightingConfig) -> None:
    if cfg.key_enabled:
        _add_light("KeyLight", cfg.key_type, cfg.key_location,
                   cfg.key_rotation_euler, cfg.key_color, cfg.key_energy,
                   size=cfg.key_size)

    if cfg.fill_enabled:
        _add_light("FillLight", "AREA", cfg.fill_location, (0.6, 0.0, 0.0),
                   cfg.fill_color, cfg.fill_energy, size=0.6)

    if cfg.rim_enabled:
        _add_light("RimLight", "AREA", cfg.rim_location, (-0.4, 0.0, 0.0),
                   cfg.rim_color, cfg.rim_energy, size=0.3)

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
        bg.inputs["Strength"].default_value = 1.0
