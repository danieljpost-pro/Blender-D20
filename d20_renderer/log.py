"""
Tiny logging facade so every module can respect verbose/quiet/dry-run.

Not using stdlib `logging` to avoid having to wire handlers/formatters across
Blender's subprocess context — a print wrapper is enough for our needs.
"""

from __future__ import annotations

import os
from .config import LoggingConfig


_state = {"verbose": False, "quiet": False, "dry_run": False, "log_file": None}


def configure(cfg: LoggingConfig) -> None:
    _state["verbose"] = cfg.verbose
    _state["quiet"] = cfg.quiet
    _state["dry_run"] = cfg.dry_run
    _state["log_file"] = cfg.log_file


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


def file_log(msg: str) -> None:
    """Append a message to the log file (if configured)."""
    if not _state["log_file"]:
        return
    try:
        log_path = _state["log_file"]
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        with open(log_path, "a") as f:
            f.write(msg + "\n")
    except OSError as e:
        warn(f"failed to write to log file {_state['log_file']}: {e}")
