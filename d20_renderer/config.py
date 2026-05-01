"""
Configuration dataclasses for the D20 renderer.

All tunable parameters live here. The top-level `RenderConfig` aggregates
sub-configs by concern (table, die, physics, camera, lighting, banner, render).
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
from typing import Optional, Tuple, List, Literal

Vec3 = Tuple[float, float, float]
RGBA = Tuple[float, float, float, float]


# ----------------------------------------------------------------------------
# Table / environment
# ----------------------------------------------------------------------------

@dataclass
class TableConfig:
    """The surface the die rolls on, plus optional bumper walls."""

    size: Vec3 = (0.6, 0.6, 0.02)              # x, y, z extents (meters). z = thickness
    location: Vec3 = (0.0, 0.0, 0.0)           # center of the table top surface
    rotation_euler: Vec3 = (0.0, 0.0, 0.0)     # tilt the table if you want a slope
    color: RGBA = (0.15, 0.35, 0.20, 1.0)      # default felt-green
    roughness: float = 0.85
    friction: float = 0.8                       # surface friction for the rigid body
    restitution: float = 0.3                    # how bouncy the surface is
    texture_path: Optional[str] = None          # optional image texture (felt, wood, etc.)
    normal_map_path: Optional[str] = None       # optional normal map for surface detail

    # Bumpers: invisible walls to keep the die in frame.
    bumpers_enabled: bool = True
    bumpers_height: float = 0.10                # meters above the table top
    bumpers_visible: bool = False               # render them or just collide with them
    bumpers_restitution: float = 0.4
    bumpers_friction: float = 0.5


# ----------------------------------------------------------------------------
# The die itself
# ----------------------------------------------------------------------------

@dataclass
class DieConfig:
    """Geometry, material, and per-face numbering of the D20."""

    # Geometry
    size: float = 0.025                         # circumradius in meters (~25mm die)
    bevel_amount: float = 0.0015                # rounded edges; affects look AND bounce
    bevel_segments: int = 3
    subdivision_levels: int = 0                 # 0 for sharp icosahedron faces

    # Body material
    body_color: RGBA = (0.95, 0.95, 0.92, 1.0)  # off-white
    body_roughness: float = 0.35
    body_metallic: float = 0.0
    body_ior: float = 1.45                      # ~resin / acrylic
    body_transmission: float = 0.0              # 0 = opaque, 1 = fully transparent (glass)
    body_subsurface: float = 0.0                # for translucent resin look

    # Number engraving
    number_color: RGBA = (0.05, 0.05, 0.05, 1.0)  # ink color
    number_style: Literal["decal", "inset", "raised"] = "decal"
    number_inset_depth: float = 0.0006          # only used for inset/raised
    font_path: Optional[str] = None             # path to .ttf/.otf; None = Blender default
    font_scale: float = 0.55                    # fraction of face inradius
    font_bold: bool = True

    # Face value layout. Index i (0..19) maps to the number printed on the
    # i-th face of the icosahedron mesh as Blender generates it. The pipeline
    # will rewrite this after simulation so that the up-facing face shows the
    # desired roll outcome.
    face_values: List[int] = field(default_factory=lambda: list(range(1, 21)))

    # Physics-only properties
    mass: float = 0.012                          # kg (~12g, typical D20)
    friction: float = 0.5
    restitution: float = 0.35
    linear_damping: float = 0.04
    angular_damping: float = 0.10
    collision_margin: float = 0.0002             # Bullet quirk; small but nonzero
    collision_shape: Literal["CONVEX_HULL", "MESH"] = "CONVEX_HULL"


# ----------------------------------------------------------------------------
# Physics / simulation
# ----------------------------------------------------------------------------

@dataclass
class PhysicsConfig:
    """World-level physics and the initial throw."""

    gravity: Vec3 = (0.0, 0.0, -9.81)
    substeps_per_frame: int = 10                 # higher = more stable, slower
    solver_iterations: int = 10

    # Initial throw (the die starts mid-air, mid-tumble — see earlier discussion
    # about avoiding awkward "settling reversed" artifacts even though we're
    # not reversing here, a mid-air start just looks more natural anyway).
    initial_position: Vec3 = (-0.20, 0.10, 0.15)
    initial_rotation_euler: Vec3 = (0.5, 1.2, 0.3)
    initial_linear_velocity: Vec3 = (1.4, -0.6, 0.2)    # m/s
    initial_angular_velocity: Vec3 = (12.0, 8.0, 15.0)  # rad/s

    # Simulation bounds
    max_simulation_frames: int = 240             # safety cap; ~10s at 24fps
    settle_velocity_threshold: float = 0.01      # die is "settled" when vel & ang vel below this
    settle_required_frames: int = 8              # must stay below threshold this many frames

    # Determinism
    bake_cache: bool = True                      # bake to disk so re-renders are identical


# ----------------------------------------------------------------------------
# Camera
# ----------------------------------------------------------------------------

@dataclass
class CameraConfig:
    location: Vec3 = (0.0, -0.55, 0.45)
    look_at: Vec3 = (0.0, 0.0, 0.02)             # aim at the table center
    focal_length_mm: float = 50.0
    sensor_width_mm: float = 36.0
    dof_enabled: bool = True
    dof_fstop: float = 2.8
    dof_focus_object: Optional[str] = "Die"      # name of object to focus on
    track_die: bool = False                       # if True, camera re-aims at die each frame


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
    key_color: RGBA = (1.0, 0.98, 0.95, 1.0)
    key_energy: float = 80.0
    key_size: float = 0.4                         # area light size

    fill_enabled: bool = True
    fill_location: Vec3 = (-0.5, -0.2, 0.4)
    fill_color: RGBA = (0.85, 0.92, 1.0, 1.0)
    fill_energy: float = 30.0

    rim_enabled: bool = True
    rim_location: Vec3 = (0.0, 0.5, 0.5)
    rim_color: RGBA = (1.0, 1.0, 1.0, 1.0)
    rim_energy: float = 50.0

    # Environment
    hdri_path: Optional[str] = None               # if set, overrides background color
    hdri_strength: float = 1.0
    hdri_rotation_z: float = 0.0
    background_color: RGBA = (0.05, 0.05, 0.06, 1.0)


# ----------------------------------------------------------------------------
# Banner audio (optional sound effect + ambience layered with the banner)
# ----------------------------------------------------------------------------

@dataclass
class BannerAudioConfig:
    """
    Optional audio that plays alongside the banner. Configured independently
    of the visual banner — you can have:
      - banner + audio
      - banner + no audio
      - audio + no banner (e.g. a sting on every roll regardless of overlay)
      - neither

    Two layers, both optional and independent:
      1. `sting`: a one-shot SFX (fanfare, "ding", crit hit sound) that fires
         at the banner trigger frame.
      2. `ambience`: a background loop (crowd cheer, tavern murmur, drone)
         that plays for the duration the banner is on-screen.

    Each layer can be a single file, OR a per-outcome map (e.g. play
    "crit_hit.wav" for outcome=20, "miss.wav" for outcome=1, fall back to
    `default_path` for everything else).
    """

    enabled: bool = False

    # --- Sting (one-shot SFX) ---
    sting_enabled: bool = True
    sting_default_path: Optional[str] = None
    sting_per_outcome: dict = field(default_factory=dict)  # {20: "/path/crit.wav", 1: "/path/fail.wav"}
    sting_volume: float = 1.0
    sting_offset_frames: int = 0          # +/- frames relative to banner trigger

    # --- Ambience (background loop) ---
    ambience_enabled: bool = False
    ambience_default_path: Optional[str] = None
    ambience_per_outcome: dict = field(default_factory=dict)
    ambience_volume: float = 0.4
    ambience_loop: bool = True
    ambience_fade_in_frames: int = 8
    ambience_fade_out_frames: int = 12
    # Timing: when does ambience start/stop relative to the banner?
    # By default, follows the banner's visible window.
    ambience_follow_banner: bool = True
    ambience_start_frame_absolute: Optional[int] = None  # only if follow_banner=False
    ambience_end_frame_absolute: Optional[int] = None


# ----------------------------------------------------------------------------
# Banner overlay ("You rolled a 20!")
# ----------------------------------------------------------------------------

@dataclass
class BannerConfig:
    """
    A 2D overlay rendered via the compositor on top of the 3D scene.
    Configured entirely separately from everything else — turn off by setting
    `enabled = False`.
    """

    enabled: bool = True

    # Content. `{value}` is substituted with the actual roll outcome.
    text_template: str = "You rolled a {value}!"
    font_path: Optional[str] = None
    font_size_px: int = 96
    text_color: RGBA = (1.0, 1.0, 1.0, 1.0)
    outline_color: RGBA = (0.0, 0.0, 0.0, 1.0)
    outline_width_px: int = 4
    bold: bool = True

    # Background behind the text
    background_enabled: bool = True
    background_color: RGBA = (0.0, 0.0, 0.0, 0.6)  # semi-transparent black
    background_padding_px: int = 30
    background_border_radius_px: int = 16

    # Position (normalized: 0,0 = bottom-left, 1,1 = top-right)
    anchor: Literal["top", "center", "bottom"] = "bottom"
    horizontal_align: Literal["left", "center", "right"] = "center"
    margin_px: int = 80                           # distance from anchor edge

    # Animation
    scroll_direction: Literal["left", "right", "up", "down", "none"] = "left"
    scroll_duration_frames: int = 24              # frames to scroll fully into place
    fade_in: bool = True
    fade_duration_frames: int = 12
    hold_frames: int = 60                         # how long it stays after arriving
    fade_out: bool = True

    # Timing — when does the banner start, relative to the simulation?
    # "after_settle" = trigger the moment the die has come to rest.
    # "absolute" = trigger at `trigger_frame` regardless.
    trigger_mode: Literal["after_settle", "absolute"] = "after_settle"
    trigger_frame_offset: int = 6                 # frames after settle to start
    trigger_frame_absolute: int = 120             # only used if trigger_mode == "absolute"


# ----------------------------------------------------------------------------
# Render settings
# ----------------------------------------------------------------------------

@dataclass
class RenderConfig:
    engine: Literal["CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"] = "CYCLES"
    resolution_x: int = 1920
    resolution_y: int = 1080
    resolution_percentage: int = 100              # 25/50/75/100 — quick downscale lever
    fps: int = 30
    samples: int = 128                            # Cycles samples
    use_denoiser: bool = True
    use_motion_blur: bool = True
    motion_blur_shutter: float = 0.5
    output_format: Literal["FFMPEG", "PNG"] = "FFMPEG"
    ffmpeg_codec: str = "H264"
    ffmpeg_quality: Literal["LOW", "MEDIUM", "HIGH", "PERC_LOSSLESS", "LOSSLESS"] = "HIGH"
    output_dir: str = "./renders"
    output_filename_pattern: str = "d20_roll_{outcome:02d}"  # extension auto-appended

    # --- Hardware levers ---
    device: Literal["CPU", "GPU"] = "CPU"
    persistent_data: bool = False                  # Cycles: keep BVH in memory between frames
    simplify_enabled: bool = False                 # global geometry/shadow simplify
    simplify_subdivision: int = 2                  # max subdiv level when simplify_enabled
    tile_size: int = 2048                          # Cycles tile size

    # --- Frame range overrides ---
    # If set, only render this slice [start, end] instead of the full simulation
    # range. Useful for previewing the settle+banner segment without re-rendering
    # the bouncing portion.
    frame_start_override: Optional[int] = None
    frame_end_override: Optional[int] = None

    # --- Single-frame preview mode ---
    # If set, render exactly this one frame as a PNG (ignores output_format).
    # Useful for sanity-checking lighting/composition cheaply.
    single_frame: Optional[int] = None


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
    force_physics: bool = False                    # rebuild + rebake physics
    force_banner_image: bool = False               # regenerate banner PNG
    force_render: bool = False                     # re-render even if output exists


@dataclass
class LoggingConfig:
    """Verbosity and dry-run controls."""
    verbose: bool = False
    quiet: bool = False                            # suppress all but warnings/errors
    dry_run: bool = False                          # build scene + log plan, skip bake/render
    log_file: Optional[str] = None                 # path to log file for recording invocations


@dataclass
class StageConfig:
    """
    Master switches for entire pipeline stages. These are above and beyond
    the individual feature flags (banner.enabled, banner_audio.enabled, etc.)
    — use these to skip whole phases of the pipeline.
    """
    do_simulate: bool = True                       # run + bake physics (False = use existing cache)
    do_render: bool = True                         # render videos (False = stop after sim)
    # If both above are False, you get a scene-build-only run, useful for
    # opening the .blend in the GUI to inspect manually.



@dataclass
class PipelineConfig:
    """Top-level config — pass one of these to the pipeline."""
    table: TableConfig = field(default_factory=TableConfig)
    die: DieConfig = field(default_factory=DieConfig)
    physics: PhysicsConfig = field(default_factory=PhysicsConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    lighting: LightingConfig = field(default_factory=LightingConfig)
    banner: BannerConfig = field(default_factory=BannerConfig)
    banner_audio: BannerAudioConfig = field(default_factory=BannerAudioConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    stages: StageConfig = field(default_factory=StageConfig)

    # What outcomes to render from this simulation. e.g. [20] for a single
    # "natural 20" video, or list(range(1, 21)) for a full set.
    desired_outcomes: List[int] = field(default_factory=lambda: [20])

    # Random seed used only for non-physics aesthetic variation (e.g. minor
    # camera jitter, if you add it later). Bullet itself is deterministic.
    seed: int = 42
