"""
D20 die: mesh creation, body material, and per-face number labeling.

Key design point
----------------
Numbers are placed as separate text objects parented to the die, one per face,
positioned at each face center and oriented along that face's normal. This
makes it trivial to *re-assign* which number sits on which face after the
simulation has run — we just rewrite the text on each label without touching
the physics, geometry, or anything else.

Alternative approach (not used here): per-face material slots with baked
number textures. That works too but requires 20 image textures or 20 UV
islands, which is more setup for the same flexibility.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Tuple

import bpy
import bmesh
from mathutils import Vector, Matrix

from .config import DieConfig

if TYPE_CHECKING:
    from bpy.types import Object


def build_die(cfg: DieConfig) -> "Object":
    """
    Build a D20 (icosahedron) with rounded edges, a body material, and
    20 child text labels (one per face). Returns the die object; labels are
    accessible as `die.children` and can be looked up by name.
    """
    die = _build_icosahedron_mesh(cfg)
    _apply_body_material(die, cfg)
    _setup_rigid_body(die, cfg)
    labels = _build_face_labels(die, cfg)
    _apply_initial_face_values(labels, cfg.face_values)
    return die


# ----------------------------------------------------------------------------
# Geometry
# ----------------------------------------------------------------------------

def _build_icosahedron_mesh(cfg: DieConfig) -> "Object":
    bpy.ops.mesh.primitive_ico_sphere_add(
        subdivisions=1,           # subdivisions=1 gives the 20-face icosahedron
        radius=cfg.size,
        location=(0, 0, 0),       # placement done later by physics module
    )
    die = bpy.context.active_object
    die.name = "Die"

    # Optional bevel for rounded edges
    if cfg.bevel_amount > 0:
        bevel = die.modifiers.new(name="Bevel", type="BEVEL")
        bevel.width = cfg.bevel_amount
        bevel.segments = cfg.bevel_segments
        bevel.limit_method = "ANGLE"

    # Apply modifiers so the *physics* sees the beveled shape.
    # (Convex hull collision won't change much with bevels, but mesh collision
    # would, and we want consistency between visual and physical geometry.)
    bpy.ops.object.select_all(action="DESELECT")
    die.select_set(True)
    bpy.context.view_layer.objects.active = die
    if cfg.bevel_amount > 0:
        bpy.ops.object.modifier_apply(modifier="Bevel")

    return die


# ----------------------------------------------------------------------------
# Material
# ----------------------------------------------------------------------------

def _apply_body_material(die: "Object", cfg: DieConfig) -> None:
    mat = bpy.data.materials.new(name="DieBody")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = cfg.body_color
    bsdf.inputs["Roughness"].default_value = cfg.body_roughness
    bsdf.inputs["Metallic"].default_value = cfg.body_metallic
    bsdf.inputs["IOR"].default_value = cfg.body_ior

    # Transmission / subsurface input names vary across Blender versions;
    # guard the lookups so this works on 4.x.
    if "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = cfg.body_transmission
    elif "Transmission" in bsdf.inputs:
        bsdf.inputs["Transmission"].default_value = cfg.body_transmission

    if "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = cfg.body_subsurface
    elif "Subsurface" in bsdf.inputs:
        bsdf.inputs["Subsurface"].default_value = cfg.body_subsurface

    # Enable alpha blending if transmission > 0 so transparency renders right
    if cfg.body_transmission > 0:
        mat.blend_method = "BLEND"

    die.data.materials.append(mat)


# ----------------------------------------------------------------------------
# Rigid body
# ----------------------------------------------------------------------------

def _setup_rigid_body(die: "Object", cfg: DieConfig) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    die.select_set(True)
    bpy.context.view_layer.objects.active = die
    bpy.ops.rigidbody.object_add()

    rb = die.rigid_body
    rb.type = "ACTIVE"
    rb.mass = cfg.mass
    rb.friction = cfg.friction
    rb.restitution = cfg.restitution
    rb.linear_damping = cfg.linear_damping
    rb.angular_damping = cfg.angular_damping
    rb.collision_shape = cfg.collision_shape
    rb.collision_margin = cfg.collision_margin


# ----------------------------------------------------------------------------
# Face labels
# ----------------------------------------------------------------------------

def get_face_centers_and_normals(die: "Object") -> List[Tuple[int, Vector, Vector]]:
    """
    Return a list of (face_index, center_local, normal_local) tuples, one per
    triangular face of the icosahedron. All vectors are in the die's local space.
    """
    mesh = die.data
    out = []
    for poly in mesh.polygons:
        out.append((poly.index, poly.center.copy(), poly.normal.copy()))
    return out


def _build_face_labels(die: "Object", cfg: DieConfig) -> List["Object"]:
    """
    Create one text object per face, positioned just above the face center
    along its outward normal, and oriented so the text reads when looking
    straight at that face. Each label is parented to the die so it tumbles
    along with the die through the simulation.
    """
    labels: List["Object"] = []
    faces = get_face_centers_and_normals(die)
    inradius = _icosahedron_inradius(cfg.size)
    text_height = cfg.font_scale * inradius
    # Lift labels just slightly off the surface so they don't z-fight
    lift = max(0.0001, cfg.size * 0.002)

    for i, (face_idx, center_local, normal_local) in enumerate(faces):
        bpy.ops.object.text_add(location=(0, 0, 0))
        txt = bpy.context.active_object
        txt.name = f"DieLabel_{face_idx:02d}"
        txt.data.body = ""  # filled in by _apply_initial_face_values
        txt.data.size = text_height
        txt.data.align_x = "CENTER"
        txt.data.align_y = "CENTER"
        if cfg.font_path:
            try:
                txt.data.font = bpy.data.fonts.load(cfg.font_path)
            except RuntimeError:
                pass  # fall back to default
        if cfg.font_bold:
            txt.data.font_bold = txt.data.font  # crude bold; replace with real bold .ttf for production

        # Orient: place at face center, push out along normal by `lift`,
        # rotate so the text's local +Z aligns with the face normal.
        position = center_local + normal_local * lift
        rot_quat = normal_local.to_track_quat("Z", "Y")
        txt.location = position
        txt.rotation_mode = "QUATERNION"
        txt.rotation_quaternion = rot_quat

        # Material: emissive ink color, ignores transmission of body
        mat = bpy.data.materials.new(name=f"DieInk_{face_idx:02d}")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = cfg.number_color
        bsdf.inputs["Roughness"].default_value = 0.6
        txt.data.materials.append(mat)

        # Convert text to mesh? Keeping as text is fine — Blender renders it
        # directly. For inset/raised number_style, we'd convert and boolean
        # against the body. (TODO if you want engraving instead of decals.)
        if cfg.number_style != "decal":
            # Placeholder: real implementation would convert to mesh and use
            # a Boolean modifier on the die. Decal mode (default) is the
            # easiest and works fine for most purposes.
            pass

        # Parent to die so it follows the tumble
        txt.parent = die
        # Counter-act the parenting so position is correct in die's local frame
        txt.matrix_parent_inverse = die.matrix_world.inverted()

        labels.append(txt)

    return labels


def _icosahedron_inradius(circumradius: float) -> float:
    """Inradius (face center distance) for an icosahedron of given circumradius."""
    # r_in = (sqrt(3)/12) * (3 + sqrt(5)) * a, where a = edge length
    # a = circumradius * 4 / sqrt(10 + 2*sqrt(5))
    import math
    a = circumradius * 4.0 / math.sqrt(10 + 2 * math.sqrt(5))
    return (math.sqrt(3) / 12.0) * (3 + math.sqrt(5)) * a


# ----------------------------------------------------------------------------
# Face value (re)assignment
# ----------------------------------------------------------------------------

def _apply_initial_face_values(labels: List["Object"], values: List[int]) -> None:
    """Set the text body of each label to its initial assigned value."""
    for label, value in zip(labels, values):
        label.data.body = str(value)


def assign_outcome_to_face(die: "Object", up_face_index: int, desired_value: int) -> None:
    """
    Re-label the faces so that the face at `up_face_index` shows `desired_value`,
    while preserving the standard D20 property that opposite faces sum to 21.

    We do this by finding the current label that says `desired_value` and the
    one currently on the up face, then swapping their text bodies. We also swap
    their *opposite* faces' labels so the sum-to-21 invariant holds.

    Caveat: this assumes the icosahedron mesh's face indices come in opposite
    pairs we can identify by negated normals — which they do for the default
    Blender icosphere, but verify in your version.
    """
    labels_by_face = {
        int(c.name.split("_")[1]): c
        for c in die.children
        if c.name.startswith("DieLabel_")
    }
    # Build map: face_index -> current text value (int)
    current = {idx: int(lbl.data.body) for idx, lbl in labels_by_face.items()}

    # Identify the face that currently shows `desired_value`
    src_face = next(idx for idx, v in current.items() if v == desired_value)

    # Find opposite-face partners by matching negated normals
    faces = get_face_centers_and_normals(die)
    normals = {idx: n for idx, _, n in faces}
    opposite = _build_opposite_face_map(normals)

    # Swap the up-face's value with the desired-value-face's value...
    a, b = up_face_index, src_face
    current[a], current[b] = current[b], current[a]
    # ...and do the same swap on their opposites, preserving sum-to-21.
    a_opp, b_opp = opposite[a], opposite[b]
    current[a_opp], current[b_opp] = current[b_opp], current[a_opp]

    # Write back
    for idx, value in current.items():
        labels_by_face[idx].data.body = str(value)


def _build_opposite_face_map(normals: dict) -> dict:
    """For each face index, find the face whose normal is most opposite."""
    opposite = {}
    items = list(normals.items())
    for i, (idx_a, n_a) in enumerate(items):
        best_idx = None
        best_dot = 1.0
        for idx_b, n_b in items:
            if idx_b == idx_a:
                continue
            d = n_a.dot(n_b)
            if d < best_dot:
                best_dot = d
                best_idx = idx_b
        opposite[idx_a] = best_idx
    return opposite
