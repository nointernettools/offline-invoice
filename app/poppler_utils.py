"""
Poppler path resolution.

Resolution order:
  1. Bundled inside exe (sys._MEIPASS/poppler/) — compiled build
  2. PATH environment variable (Scoop / Chocolatey / system installs)
  3. Common Windows install locations (ordered most-likely first)
  4. macOS / Linux — assume pdftoppm is on PATH, return None

Returns the path string to pass to pdf2image's poppler_path=,
or None to let pdf2image use the system PATH.
"""

from __future__ import annotations
import os
import shutil
import sys
from pathlib import Path


_WIN_CANDIDATES: list[Path] = [
    Path(r"E:\msys64\mingw64\bin"),
    Path(r"C:\msys64\mingw64\bin"),
    Path(r"D:\msys64\mingw64\bin"),
    Path(r"E:\poppler\Library\bin"),
    Path(r"C:\poppler\Library\bin"),
    Path(r"D:\poppler\Library\bin"),
    Path(r"C:\Program Files\poppler\bin"),
    Path(r"C:\Program Files (x86)\poppler\bin"),
    Path.home() / "poppler" / "bin",
    Path.home() / "poppler" / "Library" / "bin",
]


def _pdftoppm_exists(folder: Path) -> bool:
    exe = "pdftoppm.exe" if sys.platform == "win32" else "pdftoppm"
    return (folder / exe).is_file()


def find_poppler() -> str | None:
    """
    Return the best poppler bin path for this machine, or None.

    None is the correct value when Poppler is on PATH — pass it
    directly to pdf2image and it will find it automatically.
    """

    # 1. Bundled inside compiled exe — always check first when frozen
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS) / "poppler"  # type: ignore[attr-defined]
        if _pdftoppm_exists(bundled):
            return str(bundled)

    # 2. Poppler already on system PATH
    if shutil.which("pdftoppm"):
        return None

    # 3. Windows common locations
    if sys.platform == "win32":
        for candidate in _WIN_CANDIDATES:
            if _pdftoppm_exists(candidate):
                return str(candidate)

    # 4. Nothing found — pdf2image will raise a helpful error if preview is used
    return None


def verify_poppler(path: str | None) -> bool:
    """Return True if pdf2image can use this path."""
    if path is None:
        return bool(shutil.which("pdftoppm"))
    return _pdftoppm_exists(Path(path))