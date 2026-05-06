"""Idempotently ensure Pillow is importable from Blender's Python.

Handles two installation models:
  - bundled Python (older Blender, sys.prefix inside Blender install): plain pip install
  - system Python (e.g. Debian-packaged Blender 5.x using /usr/bin/python): pip install
    --user --break-system-packages, since PEP 668 blocks unscoped installs

Run via:  blender --background --python-use-system-env --python scripts/install_blender_deps.py
"""

import subprocess
import sys


def main() -> int:
    try:
        import PIL  # noqa: F401

        print(f"[deps] PIL {PIL.__version__} already importable from {PIL.__file__}")
        return 0
    except ImportError:
        pass

    bundled = sys.prefix not in ("/usr", "/usr/local")
    cmd = [sys.executable, "-m", "pip", "install"]
    if bundled:
        print(f"[deps] bundled Python detected ({sys.executable}); installing into Blender")
    else:
        print(
            f"[deps] system Python detected ({sys.executable}); "
            "installing to user site with --break-system-packages"
        )
        cmd += ["--user", "--break-system-packages"]
    cmd.append("Pillow")

    subprocess.check_call(cmd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
