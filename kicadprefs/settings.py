"""Curated settings overlays: settings/<name>.json holds only the keys we manage.

Overlays are deep-merged into KiCad's JSON files.  Lists and scalars replace
the existing value; objects merge recursively.  Keys that are absent from the
overlay are never touched.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterator

# Files we know how to overlay (KiCad file name without .json).
KNOWN = ("kicad_common", "eeschema", "pcbnew", "symbol_editor", "fpedit", "3d_viewer", "gerbview",
         "pl_editor", "cvpcb", "kicad")


def deep_merge(base: Any, overlay: Any) -> Any:
    if isinstance(base, dict) and isinstance(overlay, dict):
        out = dict(base)
        for k, v in overlay.items():
            out[k] = deep_merge(base.get(k), v) if k in base else copy.deepcopy(v)
        return out
    return copy.deepcopy(overlay)


def leaves(d: Any, prefix: tuple = ()) -> Iterator[tuple[tuple, Any]]:
    if isinstance(d, dict) and d:
        for k, v in d.items():
            yield from leaves(v, prefix + (k,))
    else:
        yield prefix, d


_MISSING = object()


def get_path(d: Any, path: tuple) -> Any:
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return _MISSING
        d = d[k]
    return d


def set_path(d: dict, path: tuple, value: Any) -> None:
    for k in path[:-1]:
        d = d.setdefault(k, {})
    d[path[-1]] = value


def diff(overlay: dict, current: dict) -> list[tuple[str, Any, Any]]:
    """Managed leaves whose installed value differs: (dotted path, installed, wanted)."""
    out = []
    for path, want in leaves(overlay):
        have = get_path(current, path)
        if have != want:
            out.append((".".join(path), "<missing>" if have is _MISSING else have, want))
    return out


def capture(overlay: dict, current: dict) -> dict:
    """Refresh overlay values from the installed file (only managed keys)."""
    out = copy.deepcopy(overlay)
    for path, _ in leaves(overlay):
        have = get_path(current, path)
        if have is not _MISSING:
            set_path(out, path, have)
    return out


def load_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def dump_json(path: Path, data: dict) -> None:
    # KiCad writes 2-space indented, sorted JSON
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def overlays(settings_dir: Path) -> dict[str, dict]:
    res = {}
    for p in sorted(settings_dir.glob("*.json")):
        if p.stem not in KNOWN:
            raise SystemExit(f"unknown settings overlay {p.name}; expected one of {', '.join(KNOWN)}")
        res[p.stem] = json.loads(p.read_text())
    return res
