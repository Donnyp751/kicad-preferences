"""Render docs/hotkeys.html: a self-contained, searchable visual hotkey map."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import keymap, keys

TEMPLATE = Path(__file__).parent / "templates" / "hotkeys.html"

TABS = [
    ("sch", "Schematic"), ("symedit", "Symbol Editor"), ("pcb", "PCB"), ("fpedit", "Footprint Editor"),
    ("sim", "Simulator"), ("3d", "3D Viewer"), ("gerbview", "Gerber Viewer"), ("pl", "Drawing Sheet"),
    ("kicad", "Project Manager"),
]

_DROP = re.compile(r"^(Switch to |Toggle |Show |Place |Draw |Add |Run |Open |Edit )")


def short_label(friendly: str, aid: str, overrides: dict[str, str]) -> str:
    if aid in overrides:
        return overrides[aid]
    s = (friendly or aid.rsplit(".", 1)[-1]).replace("...", "").replace("…", "").strip()
    s2 = _DROP.sub("", s)
    s = s2 if len(s2) >= 3 else s
    return s[0].upper() + s[1:] if s else s


def render(m: keymap.Model, version: str) -> str:
    labels = m.ctx.labels
    modal_ids = {aid for aid in m.catalog if keymap._is_modal(m, aid) or m.catalog[aid]["scope"] != "AS_GLOBAL"}
    actions = []
    for aid, a in sorted(m.catalog.items()):
        if not a["friendly"] and not any(m.effective[aid]):
            continue  # internal actions KiCad does not show in the hotkey dialog
        key, alt = m.effective[aid]
        binds = []
        for k in (key, alt):
            if not k:
                continue
            pk = keys.parse(k)
            mods, base = pk.physical()
            binds.append({"k": k, "mods": sorted(mods, key=keys.MOD_ORDER.index), "base": base})
        actions.append({
            "id": aid,
            "name": a["friendly"] or aid.rsplit(".", 1)[-1],
            "label": short_label(a["friendly"], aid, labels),
            "tip": a["tooltip"],
            "key": key, "alt": alt, "def": a["default"], "defAlt": a["default_alt"],
            "binds": binds,
            "defBinds": [
                dict(zip(("mods", "base"), (sorted(p.physical()[0], key=keys.MOD_ORDER.index), p.physical()[1])), k=k)
                for k in (a["default"], a["default_alt"]) if k for p in [keys.parse(k)]
            ],
            "frames": m.frames_of(aid) if a["frames"] != ["*"] else ["*"],
            "cat": m.ctx.category(aid),
            "modal": aid in modal_ids,
            "why": m.why.get(aid, ""),
        })
    data = {
        "version": version,
        "generated": time.strftime("%Y-%m-%d"),
        "tabs": [{"id": t, "label": l} for t, l in TABS],
        "commonFrames": m.ctx.common_frames,
        "categories": m.ctx.category_info,
        "actions": actions,
        "conflicts": keymap.conflicts(m),
        "equivalents": [
            {"a": a, "b": b, "ka": m.effective[a][0], "kb": m.effective[b][0],
             "na": m.catalog[a]["friendly"], "nb": m.catalog[b]["friendly"]}
            for a, b in m.ctx.equivalents if a in m.catalog and b in m.catalog
        ],
    }
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.read_text().replace("/*__DATA__*/null", blob)
