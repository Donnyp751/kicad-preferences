"""Locate the KiCad config dir, guard against running KiCad, back up files."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

KICAD_PROCS = ("kicad", "eeschema", "pcbnew", "kicad-cli-gui", "_eeschema", "_pcbnew")


def kicad_version() -> str:
    try:
        out = subprocess.run(["kicad-cli", "version"], capture_output=True, text=True, check=True).stdout
        m = re.match(r"(\d+)\.(\d+)", out.strip())
        if m:
            return f"{m.group(1)}.{m.group(2)}"
    except (OSError, subprocess.CalledProcessError):
        pass
    return "10.0"


def config_dir(override: str | None = None, version: str | None = None) -> Path:
    if override:
        return Path(override).expanduser()
    base = os.environ.get("KICAD_CONFIG_HOME")
    if base:
        return Path(base).expanduser() / (version or kicad_version())
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return xdg / "kicad" / (version or kicad_version())


def running_kicad() -> list[str]:
    try:
        out = subprocess.run(["ps", "-eo", "pid=,comm="], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    hits = []
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip() in KICAD_PROCS:
            hits.append(line.strip())
    return hits


class Backup:
    def __init__(self, cfg: Path):
        self.cfg = cfg
        self.dir = cfg / "kprefs-backups" / time.strftime("%Y%m%d-%H%M%S")
        self.saved: list[Path] = []

    def save(self, path: Path) -> None:
        if not path.exists():
            return
        rel = path.relative_to(self.cfg)
        dest = self.dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        self.saved.append(rel)
