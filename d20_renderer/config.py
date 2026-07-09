"""
Configuration dataclasses for the D20 renderer.

All tunable parameters live here. The top-level `RenderConfig` aggregates
sub-configs by concern (table, die, physics, camera, lighting, render).
Anything you might want to vary between runs should be a field here, not
hard-coded elsewhere in the codebase.

Design notes
------------
- Use `dataclasses.field(default_factory=...)` for mutable defaults (vectors,
  dicts) to avoid the classic "shared mutable default" bug.
- Vectors are typed as `Tuple[float, float, float]` rather than mathutils.Vector
  so the config can be imported and inspected outside of Blender (e.g. from
  unit tests, or from a CLI runner that hasn't yet started Blender).
- Defaults aim for "looks reasonable on first run" — a tabletop with a
  visible white-ish die, simple lighting, Cycles render at modest sample count.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Vec3 = tuple[float, float, float]
RGBA = tuple[float, float, float, float]


# ----------------------------------------------------------------------------
# Table / environment
# ----------------------------------------------------------------------------


@dataclass
class TableConfig:
    """The surface the die rolls on, plus optional bumper walls."""

    size: Vec3 = (0.6, 0.6, 0.02)  # x, y, z extents (meters). z = thickness
    location: Vec3 = (0.0, 0.0, 0.0)  # center of the table top surface
    rotation_euler: Vec3 = (0.0, 0.0, 0.0)  # tilt the table if you want a slope
    color: RGBA = (0.06, 0.14, 0.08, 1.0)  # dark felt-green
    roughness: float = 0.85
    friction: float = 0.8  # surface friction for the rigid body
    restitution: float = 0.3  # how bouncy the surface is
    texture_path: str | None = None  # optional image texture (felt, wood, etc.)
    normal_map_path: str | None = None  # optional normal map for surface detail

    visible: bool = True         # set False to hide table in render
    physics_enabled: bool = True # set False to remove table rigid body entirely

    # Bumpers: invisible octagonal wall ring to keep the die in frame.
    bumpers_enabled: bool = True
    bumpers_height: float = 0.10  # meters above the table top
    bumpers_thickness: float = 0.02  # wall thickness; too thin lets a fast die tunnel through
    bumpers_visible: bool = False  # render them or just collide with them
    bumpers_restitution: float = 0.4
    bumpers_friction: float = 0.5


@dataclass
class BowlConfig:
    """Hemispherical bowl the die rolls into — an alternative to the flat table.

    The bowl is a passive rigid body with MESH collision (required for concave
    geometry). Its rim sits at `location`; the bowl extends downward by `depth`.
    Pair with `table.visible=False` (or `--no-table`) when using this.
    """

    enabled: bool = False
    radius: float = 0.12       # inner radius in meters
    depth: float = 0.06        # bowl depth in meters (rim to bottom)
    segments: int = 32         # mesh density; higher = smoother but more polys
    location: Vec3 = (0.0, 0.0, 0.0)  # world position of the rim centre
    color: RGBA = (0.15, 0.08, 0.05, 1.0)  # dark wood
    roughness: float = 0.7
    friction: float = 0.4
    restitution: float = 0.25
    visible: bool = True


# ----------------------------------------------------------------------------
# The die itself
# ----------------------------------------------------------------------------


@dataclass
class DieConfig:
    """Geometry, material, and per-face numbering of the D20."""

    # Geometry
    size: float = 0.025  # circumradius in meters (~25mm die)
    bevel_amount: float = 0.0015  # rounded edges; affects look AND bounce
    bevel_segments: int = 3
    subdivision_levels: int = 0  # 0 for sharp icosahedron faces

    # Body material
    body_color: RGBA = (0.55, 0.06, 0.05, 1.0)  # saturated deep red
    body_roughness: float = 0.35
    body_metallic: float = 0.0
    body_ior: float = 1.45  # ~resin / acrylic
    body_transmission: float = 0.08  # slight translucency for resin look
    body_subsurface: float = 0.12  # subsurface scatter for translucent depth

    # Number engraving
    number_color: RGBA = (0.02, 0.02, 0.02, 1.0)  # matte black ink (for decal/raised)
    number_roughness: float = 0.95  # matte finish; high = non-reflective
    number_metallic: float = 0.0  # metallic property
    number_style: Literal["decal", "inset", "raised"] = "decal"
    number_inset_depth: float = 0.0006  # only used for inset/raised

    # Inset-specific material properties (carved surface appearance)
    inset_color: RGBA = (0.05, 0.05, 0.05, 1.0)  # color of carved surface (darker/different)
    inset_roughness: float = 0.8  # carved surface finish
    inset_metallic: float = 0.0  # metallic property of carved surface
    inset_ior: float = 1.45  # refractive index of carved surface

    font_path: str | None = None  # path to .ttf/.otf; None = Blender default
    font_scale: float = 0.55  # fraction of face inradius
    font_bold: bool = True

    # Face value layout. Index i (0..19) maps to the number printed on the
    # i-th face of the icosahedron mesh as Blender generates it. The pipeline
    # will rewrite this after simulation so that the up-facing face shows the
    # desired roll outcome.
    face_values: list[int] = field(default_factory=lambda: list(range(1, 21)))

    # Physics-only properties
    mass: float = 0.012  # kg (~12g, typical D20)
    friction: float = 0.5
    restitution: float = 0.35
    linear_damping: float = 0.04
    angular_damping: float = 0.10
    collision_margin: float = 0.0002  # Bullet quirk; small but nonzero
    collision_shape: Literal["CONVEX_HULL", "MESH"] = "CONVEX_HULL"
    # Bullet sleep thresholds. Blender's defaults (0.4 m/s, 0.5 rad/s) freeze a
    # slow-tumbling die mid-roll; lower values let the roll play out longer.
    use_deactivation: bool = True
    deactivation_linear_velocity: float = 0.4  # m/s (Blender default)
    deactivation_angular_velocity: float = 0.5  # rad/s (Blender default)


# ----------------------------------------------------------------------------
# Physics / simulation
# ----------------------------------------------------------------------------


@dataclass
class PhysicsConfig:
    """World-level physics and the initial throw."""

    gravity: Vec3 = (0.0, 0.0, -9.81)
    substeps_per_frame: int = 10  # higher = more stable, slower
    solver_iterations: int = 10

    # Initial throw (the die starts mid-air, mid-tumble — see earlier discussion
    # about avoiding awkward "settling reversed" artifacts even though we're
    # not reversing here, a mid-air start just looks more natural anyway).
    initial_position: Vec3 = (0.0, 0.0, 0.15)  # centered above table
    initial_rotation_euler: Vec3 = (0.5, 1.2, 0.3)
    initial_linear_velocity: Vec3 = (0.8, -0.4, 0.2)   # m/s
    initial_angular_velocity: Vec3 = (10.0, 8.0, 12.0)  # rad/s

    # Simulation bounds
    max_simulation_frames: int = 360  # ~15s at 24fps for better balance of motion + settle
    settle_velocity_threshold: float = 0.01  # die is "settled" when vel & ang vel below this
    settle_required_frames: int = 8  # must stay below threshold this many frames

    # Determinism
    bake_cache: bool = True  # bake to disk so re-renders are identical


# ----------------------------------------------------------------------------
# Camera
# ----------------------------------------------------------------------------


@dataclass
class CameraConfig:
    location: Vec3 = (0.0, 0.0, 0.5)   # directly above table center
    look_at: Vec3 = (0.0, 0.0, 0.0)    # table center
    focal_length_mm: float = 35.0  # wider lens for better framing
    sensor_width_mm: float = 36.0
    dof_enabled: bool = True
    dof_fstop: float = 2.8
    dof_focus_object: str | None = "Die"  # name of object to focus on
    track_die: bool = False  # if True, camera re-aims at die each frame

    # Post-settle orbit: after the die comes to rest, smoothly move the camera
    # over `orbit_duration_frames` to a top-down close-up of the up-facing face,
    # then hold for `orbit_hold_frames`. Drives the final-shot composition.
    orbit_enabled: bool = True
    orbit_start_offset_frames: int = 6  # wait after settle before orbit begins
    orbit_duration_frames: int = 36  # 1.5s @ 24fps
    orbit_hold_frames: int = 24  # 1s held on top-down view
    orbit_end_distance: float = 0.18  # camera distance from die center at end (m)
    orbit_end_tilt_deg: float = 15.0  # degrees off straight-down; 0 = exactly overhead
    # Clockwise camera roll (degrees) held constant across the entire shot —
    # invisible against a void background, but it sets which way the settled
    # up-face reads. Requires track_die for the pre-orbit phase.
    orbit_end_roll_deg: float = 0.0


# ----------------------------------------------------------------------------
# Lighting
# ----------------------------------------------------------------------------


@dataclass
class LightingConfig:
    # Three-point lighting setup; any can be disabled.
    key_enabled: bool = True
    key_type: Literal["AREA", "SUN", "POINT", "SPOT"] = "AREA"
    key_location: Vec3 = (0.4, -0.3, 0.6)
    key_rotation_euler: Vec3 = (0.7, 0.3, 0.5)
    key_color: RGBA = (0.12, 0.12, 1.0, 1.0)  # deep blue
    key_energy: float = 25.0
    key_size: float = 0.4  # area light size

    fill_enabled: bool = True
    fill_location: Vec3 = (-0.5, -0.2, 0.4)
    fill_color: RGBA = (1.0, 0.97, 0.78, 1.0)  # pale yellow
    fill_energy: float = 8.0

    rim_enabled: bool = True
    rim_location: Vec3 = (0.0, 0.5, 0.5)
    rim_color: RGBA = (1.0, 1.0, 1.0, 1.0)
    rim_energy: float = 35.0

    # Top ("result") light: a near-overhead area light placed close to the
    # camera's mirror position about the vertical, so its reflection off the
    # horizontal up-face lands almost directly in the camera — making the
    # settled result face read visibly brighter than the tilted faces.
    top_enabled: bool = False
    top_location: Vec3 = (-0.01, 0.10, 1.0)
    top_rotation_euler: Vec3 = (0.0, 0.0, 0.0)  # area light faces -Z: straight down
    top_color: RGBA = (1.0, 1.0, 1.0, 1.0)
    top_energy: float = 60.0
    top_size: float = 0.3

    # Environment
    hdri_path: str | None = None  # if set, overrides background color
    hdri_strength: float = 1.0
    hdri_rotation_z: float = 0.0
    background_color: RGBA = (0.05, 0.05, 0.06, 1.0)
    background_strength: float = (
        3.0  # world ambient strength; higher = more fill from all directions
    )


# ----------------------------------------------------------------------------
# Render settings
# ----------------------------------------------------------------------------


@dataclass
class RenderConfig:
    engine: Literal["CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"] = "CYCLES"
    resolution_x: int = 1920
    resolution_y: int = 1080
    resolution_percentage: int = 100  # 25/50/75/100 — quick downscale lever
    fps: int = 30
    samples: int = 128  # Cycles samples
    use_denoiser: bool = False  # bundled Blender lacks OIDN support
    # Render-time slow motion via Blender's frame remap. 2.0 = half speed.
    # Stretches everything (roll AND camera moves) — shorten orbit frame
    # counts to keep the reveal tempo. Does not touch the physics bake.
    slow_motion_factor: float = 1.0
    use_motion_blur: bool = True
    motion_blur_shutter: float = 0.5
    output_format: Literal["FFMPEG", "PNG"] = "FFMPEG"
    ffmpeg_codec: str = "H264"
    ffmpeg_quality: Literal["LOW", "MEDIUM", "HIGH", "PERC_LOSSLESS", "LOSSLESS"] = "HIGH"
    output_dir: str = "./renders"
    output_filename_pattern: str = "d20_roll_{outcome:02d}"  # extension auto-appended

    # --- Hardware levers ---
    device: Literal["CPU", "GPU"] = "CPU"
    persistent_data: bool = False  # Cycles: keep BVH in memory between frames
    simplify_enabled: bool = False  # global geometry/shadow simplify
    simplify_subdivision: int = 2  # max subdiv level when simplify_enabled
    tile_size: int = 2048  # Cycles tile size

    # --- Frame range overrides ---
    # If set, only render this slice [start, end] instead of the full simulation
    # range. Useful for previewing the settle segment without re-rendering
    # the bouncing portion.
    frame_start_override: int | None = None
    frame_end_override: int | None = None

    # --- Single-frame preview mode ---
    # If set, render exactly this one frame as a PNG (ignores output_format).
    # Useful for sanity-checking lighting/composition cheaply.
    single_frame: int | None = None


# ----------------------------------------------------------------------------
# Top-level
# ----------------------------------------------------------------------------

# ----------------------------------------------------------------------------
# Caching & incremental execution
# ----------------------------------------------------------------------------


@dataclass
class CacheConfig:
    """
    Controls which pipeline stages get skipped when their inputs haven't
    changed since the last run. Each stage hashes its relevant config inputs
    and writes a `.cache_key` file next to its output; subsequent runs skip
    the stage if the key matches.

    Use `force_*` flags to override individual stages, or `--force-all` from
    the CLI to bust everything.
    """

    enabled: bool = True
    cache_dir: str = "./.d20_cache"

    # Force flags — re-do the stage even if the cache key matches.
    force_physics: bool = False  # rebuild + rebake physics
    force_render: bool = False  # re-render even if output exists


@dataclass
class LoggingConfig:
    """Verbosity and dry-run controls."""

    verbose: bool = False
    quiet: bool = False  # suppress all but warnings/errors
    dry_run: bool = False  # build scene + log plan, skip bake/render
    log_file: str | None = None  # path to log file for recording invocations


@dataclass
class StageConfig:
    """
    Master switches for entire pipeline stages. These are above and beyond
    individual feature flags — use these to skip whole phases of the pipeline.
    """

    do_simulate: bool = True  # run + bake physics (False = use existing cache)
    do_render: bool = True  # render videos (False = stop after sim)
    # If both above are False, you get a scene-build-only run, useful for
    # opening the .blend in the GUI to inspect manually.


@dataclass
class PipelineConfig:
    """Top-level config — pass one of these to the pipeline."""

    table: TableConfig = field(default_factory=TableConfig)
    bowl: BowlConfig = field(default_factory=BowlConfig)
    die: DieConfig = field(default_factory=DieConfig)
    physics: PhysicsConfig = field(default_factory=PhysicsConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    lighting: LightingConfig = field(default_factory=LightingConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    stages: StageConfig = field(default_factory=StageConfig)

    # What outcomes to render from this simulation. e.g. [20] for a single
    # "natural 20" video, or list(range(1, 21)) for a full set.
    desired_outcomes: list[int] = field(default_factory=lambda: [20])

    # Random seed used only for non-physics aesthetic variation (e.g. minor
    # camera jitter, if you add it later). Bullet itself is deterministic.
    seed: int = 42
