"""
Tiny logging facade so every module can respect verbose/quiet/dry-run.

Not using stdlib `logging` to avoid having to wire handlers/formatters across
Blender's subprocess context — a print wrapper is enough for our needs.
"""

from __future__ import annotations

from .config import LoggingConfig


_state = {"verbose": False, "quiet": False, "dry_run": False}


def configure(cfg: LoggingConfig) -> None:
    _state["verbose"] = cfg.verbose
    _state["quiet"] = cfg.quiet
    _state["dry_run"] = cfg.dry_run


def is_dry_run() -> bool:
    return _state["dry_run"]


def info(msg: str) -> None:
    if not _state["quiet"]:
        print(f"[d20] {msg}")


def debug(msg: str) -> None:
    if _state["verbose"] and not _state["quiet"]:
        print(f"[d20:debug] {msg}")


def warn(msg: str) -> None:
    print(f"[d20:warn] {msg}")


def error(msg: str) -> None:
    print(f"[d20:error] {msg}")


def stage(name: str, action: str) -> None:
    """Log a stage-level action: 'skipped', 'running', 'forced', 'dry-run'."""
    if not _state["quiet"]:
        print(f"[d20] {name}: {action}")
