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
import math

from mathutils import Vector, Quaternion

from .config import DieConfig
from . import log

if TYPE_CHECKING:
    from bpy.types import Object


def build_die(cfg: DieConfig, with_labels: bool = True) -> "Object":
    """
    Build a D20 (icosahedron) with rounded edges and a body material.
    If with_labels=True, also add 20 child text labels (one per face with fixed numbers).
    If with_labels=False, create an unlabeled die for physics simulation.
    Returns the die object; labels are accessible as `die.children` if they exist.
    """
    die = _build_icosahedron_mesh(cfg)
    _apply_body_material(die, cfg)
    if with_labels:
        labels = _build_face_labels(die, cfg)
        _apply_initial_face_values(labels, cfg.face_values)
    _apply_bevel(die, cfg)
    _setup_rigid_body(die, cfg)
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
    return die


def _apply_bevel(die: "Object", cfg: DieConfig) -> None:
    """
    Add and destructively apply a Bevel modifier.

    Called *after* `_build_face_labels` so the label-creation loop iterates the
    original 20 face polygons; once applied, the bevel adds many new strip
    polygons (e.g. width=0.0015, segments=3 → ~140 polygons), which would
    otherwise leak into label creation and leave most labels with empty text.
    """
    if cfg.bevel_amount <= 0:
        log.debug("die.bevel: skipped (bevel_amount<=0)")
        return
    before = len(die.data.polygons)
    bevel = die.modifiers.new(name="Bevel", type="BEVEL")
    bevel.width = cfg.bevel_amount
    bevel.segments = cfg.bevel_segments
    bevel.limit_method = "ANGLE"
    bpy.ops.object.select_all(action="DESELECT")
    die.select_set(True)
    bpy.context.view_layer.objects.active = die
    bpy.ops.object.modifier_apply(modifier="Bevel")
    log.debug(f"die.bevel: applied (width={cfg.bevel_amount}, segments={cfg.bevel_segments}); "
              f"polygons {before} -> {len(die.data.polygons)}")


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
    log.debug(f"die.labels: building labels for {len(faces)} face polygons (expect 20)")
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
        bsdf.inputs["Roughness"].default_value = cfg.number_roughness
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
    Re-label every face so the face at `up_face_index` shows `desired_value`,
    by applying an icosahedral-symmetry rotation to the entire labeling.

    Concretely: find an element R of the icosahedral rotation group that maps
    the face currently showing `desired_value` onto `up_face_index`. The R-image
    of every face determines where each label moves. Because R is a true symmetry
    of the icosahedron, every face adjacency is preserved — the resulting
    layout is a valid D20, just rotated from the canonical arrangement.

    A naive pair-swap (which is what this used to do) puts the right number on
    top but breaks the magic adjacency pattern, so adjacent faces end up with
    relationships that don't occur on a real D20.
    """
    labels_by_face = {
        int(c.name.split("_")[1]): c
        for c in die.children
        if c.name.startswith("DieLabel_")
    }
    current = {idx: int(lbl.data.body) for idx, lbl in labels_by_face.items()}

    src_face = next(idx for idx, v in current.items() if v == desired_value)
    log.debug(
        f"die.assign_outcome: up_face={up_face_index}, desired={desired_value}, "
        f"src_face (face currently showing {desired_value})={src_face}"
    )

    if src_face == up_face_index:
        log.debug("die.assign_outcome: up face already shows desired value; no relabel")
        return

    faces = get_face_centers_and_normals(die)
    # Restrict to the original 20 icosphere faces; the bevel adds extra polygons
    # at indices >= 20 that aren't part of the symmetry group.
    normals = {idx: n for idx, _, n in faces if idx in labels_by_face}

    permutation = _icosahedral_permutation(normals, src_face, up_face_index)
    if permutation is None:
        log.warn(
            f"die.assign_outcome: no icosahedral symmetry found mapping "
            f"face {src_face} -> {up_face_index}; labels unchanged"
        )
        return

    # permutation[old] = new  ⇒  label that was on `old` should now sit on `new`.
    new_labels = {new: current[old] for old, new in permutation.items()}

    log.debug(
        f"die.assign_outcome: permutation places {new_labels[up_face_index]} "
        f"on up face {up_face_index} (expected {desired_value})"
    )

    for idx, val in new_labels.items():
        labels_by_face[idx].data.body = str(val)


def _icosahedral_permutation(
    normals: dict, src_idx: int, dst_idx: int, n_angles: int = 720, err_tol: float = 0.1
) -> dict | None:
    """
    Find the face-index permutation produced by an icosahedral rotation that
    maps `src_idx` onto `dst_idx`.

    Strategy: any rotation taking n_src to n_dst can be written as
    R = twist(θ, n_dst) ∘ Q_align, where Q_align is the shortest-arc rotation
    between the two normals. The 3 elements of the icosahedral group that map
    src→dst correspond to 3 specific values of θ (120° apart, with a per-pair
    offset that depends on geometry). We sweep θ over `n_angles` discretized
    values; an icosahedral rotation is detected when applying R to all 20 face
    normals lands every one of them onto a unique target normal within `err_tol`.
    """
    n_src = normals[src_idx]
    n_dst = normals[dst_idx]
    q_align = n_src.rotation_difference(n_dst)

    best_perm = None
    best_err = float("inf")
    best_bij_perm = None
    best_bij_err = float("inf")
    for i in range(n_angles):
        theta = 2.0 * math.pi * i / n_angles
        rot = Quaternion(n_dst, theta) @ q_align

        perm: dict = {}
        used: set = set()
        max_err = 0.0
        bijective = True
        for old_idx, n_old in normals.items():
            n_new = rot @ n_old
            target = max(normals.keys(), key=lambda j: normals[j].dot(n_new))
            err = (normals[target] - n_new).length
            if err > max_err:
                max_err = err
            if target in used:
                bijective = False
                break
            used.add(target)
            perm[old_idx] = target

        if bijective and perm.get(src_idx) == dst_idx:
            if max_err < best_bij_err:
                best_bij_err = max_err
                best_bij_perm = perm
            if max_err < err_tol and max_err < best_err:
                best_perm = perm
                best_err = max_err

    if best_perm is None:
        log.debug(
            f"die._icosahedral_permutation: no rotation under err_tol={err_tol}; "
            f"best bijective candidate had max_err={best_bij_err:.4f}"
        )
    return best_perm
