"""Keymap model: repo keymap.toml + contexts.toml + catalog -> effective bindings & analysis."""

from __future__ import annotations

import re
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import keys

EDITOR_FRAMES = ("sch", "symedit", "pcb", "fpedit")


@dataclass
class Binding:
    key: str
    alt: str
    why: str = ""


@dataclass
class Contexts:
    frames: dict[str, str]
    common_frames: list[str]
    frame_overrides: dict[str, list[str]]
    modal_tools: list[str]
    categories: list[tuple[str, str]]
    category_info: dict[str, dict]
    allow: list[set[str]]
    equivalents: list[tuple[str, str]]
    must_bind: list[str]
    mnemonics: dict[str, str] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Contexts":
        d = tomllib.loads(path.read_text())
        cats = sorted(d.get("category_rules", {}).items(), key=lambda kv: -len(kv[0]))
        return cls(
            frames=d["frames"],
            common_frames=d.get("common_frames", {}).get("frames", list(d["frames"])),
            frame_overrides=d.get("frame_overrides", {}),
            modal_tools=d.get("modal_tools", {}).get("tools", []),
            categories=cats,
            category_info=d.get("categories", {}),
            allow=[set(x) for x in d.get("allowed_conflicts", {}).get("groups", [])],
            equivalents=[tuple(x) for x in d.get("equivalents", {}).get("pairs", [])],
            must_bind=d.get("must_bind", {}).get("actions", []),
            mnemonics=d.get("menu_mnemonics", {}),
            labels=d.get("labels", {}),
        )

    def category(self, action_id: str) -> str:
        for pat, cat in self.categories:
            if action_id == pat or action_id.startswith(pat if pat.endswith(".") else pat + ".") \
                    or (pat.startswith("~") and re.search(pat[1:], action_id)):
                return cat
        return "other"


@dataclass
class Keymap:
    meta: dict
    bind: dict[str, Binding]

    @classmethod
    def load(cls, path: Path) -> "Keymap":
        d = tomllib.loads(path.read_text())
        bind: dict[str, Binding] = {}
        for action, v in d.get("bind", {}).items():
            if isinstance(v, str):
                bind[action] = Binding(v, None)  # type: ignore[arg-type]  # alt: keep default
            else:
                bind[action] = Binding(v.get("key", ""), v.get("alt"), v.get("why", ""))
        return cls(d.get("meta", {}), bind)


@dataclass
class Model:
    catalog: dict[str, dict]
    ctx: Contexts
    effective: dict[str, tuple[str, str]]
    why: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def frames_of(self, aid: str) -> list[str]:
        if aid in self.ctx.frame_overrides:
            return self.ctx.frame_overrides[aid]
        f = self.catalog[aid]["frames"]
        return self.ctx.common_frames if f == ["*"] else f


def effective_from_keymap(catalog: dict[str, dict], km: Keymap, ctx: Contexts) -> Model:
    eff = {aid: (a["default"], a["default_alt"]) for aid, a in catalog.items()}
    m = Model(catalog, ctx, eff)
    for aid, b in km.bind.items():
        if aid not in catalog:
            m.errors.append(f"unknown action id in keymap: {aid}")
            continue
        try:
            prim = keys.normalize(b.key)
            alt = keys.normalize(b.alt) if b.alt is not None else catalog[aid]["default_alt"]
        except keys.KeyError_ as e:
            m.errors.append(f"{aid}: {e}")
            continue
        for w in keys.warnings_for(prim) + (keys.warnings_for(alt) if alt else []):
            m.warnings.append(f"{aid}: {w}")
        eff[aid] = (prim, alt)
        if b.why:
            m.why[aid] = b.why
    return m


def effective_from_file(catalog: dict[str, dict], filemap: dict[str, tuple[str, str]], ctx: Contexts) -> Model:
    eff = {aid: filemap.get(aid, (a["default"], a["default_alt"])) for aid, a in catalog.items()}
    m = Model(catalog, ctx, eff)
    for aid, (p, _) in filemap.items():
        if aid not in catalog and p:
            m.warnings.append(f"stale action in hotkeys file (not in KiCad catalog): {aid} = {p}")
    return m


# --------------------------------------------------------------------------- analysis

def bindings_by_frame(m: Model) -> dict[str, dict[str, list[str]]]:
    """frame -> key -> [action ids]"""
    res: dict[str, dict[str, list[str]]] = {f: defaultdict(list) for f in m.ctx.frames}
    for aid, (p, a) in m.effective.items():
        for k in {p, a} - {""}:
            for f in m.frames_of(aid):
                if f in res:
                    res[f][k].append(aid)
    return res


def _is_modal(m: Model, aid: str) -> bool:
    tool = m.catalog[aid]["tool"]
    return any(tool == t or aid == t for t in m.ctx.modal_tools)


def conflicts(m: Model) -> list[dict]:
    """Return conflicts as dicts {frame, key, actions, severity, reason}.

    KiCad's dispatcher (ACTION_MANAGER::RunHotKey) prefers a context-scoped
    action whose tool is on the active stack; otherwise it runs the first
    enabled global action.  So two globals on one key in one frame is a real
    conflict, while a modal tool's context action layered over a global is fine.
    """
    out = []
    for frame, kmap in bindings_by_frame(m).items():
        for key, aids in kmap.items():
            if len(aids) < 2:
                continue
            aset = frozenset(aids)
            if any(aset <= g for g in m.ctx.allow):
                continue
            glob = [a for a in aids if m.catalog[a]["scope"] == "AS_GLOBAL" and not _is_modal(m, a)]
            ctx_by_tool: dict[str, list[str]] = defaultdict(list)
            for a in aids:
                if a not in glob:
                    ctx_by_tool[m.catalog[a]["tool"]].append(a)
            problems = []
            if len(glob) > 1:
                problems.append(("global", glob))
            for tool, lst in ctx_by_tool.items():
                if len(lst) > 1:
                    problems.append((f"same tool {tool}", lst))
            for reason, lst in problems:
                sev = "error" if frame in EDITOR_FRAMES else "warning"
                out.append({"frame": frame, "frames": [frame], "key": key, "actions": sorted(lst),
                            "severity": sev, "reason": reason})
    # merge identical conflicts across frames
    merged: dict[tuple, dict] = {}
    for c in out:
        sig = (c["key"], tuple(c["actions"]), c["reason"])
        if sig in merged:
            merged[sig]["frames"].append(c["frame"])
            if c["severity"] == "error":
                merged[sig]["severity"] = "error"
        else:
            merged[sig] = c
    return sorted(merged.values(), key=lambda c: (c["severity"] != "error", c["key"]))


def layered(m: Model) -> list[dict]:
    """Modal/context actions intentionally sharing a key with a global action (informational)."""
    out = []
    by_frame = bindings_by_frame(m)
    for frame in EDITOR_FRAMES:
        for key, aids in by_frame.get(frame, {}).items():
            mod = [a for a in aids if m.catalog[a]["scope"] != "AS_GLOBAL" or _is_modal(m, a)]
            glob = [a for a in aids if a not in mod]
            if mod and glob:
                out.append({"frame": frame, "key": key, "modal": sorted(mod), "global": sorted(glob)})
    return out


def mnemonic_clashes(m: Model) -> list[dict]:
    """Alt+<letter> bindings that a GTK menu-bar mnemonic would swallow."""
    out = []
    for aid, (p, a) in m.effective.items():
        for k in {p, a} - {""}:
            parsed = keys.parse(k)
            if parsed and parsed.mods == ("Alt",) and len(parsed.base) == 1:
                frames = [f for f in m.frames_of(aid) if parsed.base in m.ctx.mnemonics.get(f, "")]
                if frames:
                    out.append({"action": aid, "key": k, "frames": frames})
    return out


def equivalence_report(m: Model) -> list[dict]:
    out = []
    for a, b in m.ctx.equivalents:
        if a not in m.catalog or b not in m.catalog:
            out.append({"pair": [a, b], "issue": "unknown action"})
            continue
        if m.effective[a][0] != m.effective[b][0]:
            out.append({"pair": [a, b], "keys": [m.effective[a][0], m.effective[b][0]],
                        "issue": "different keys"})
    return out


def unbound_must(m: Model) -> list[str]:
    return [a for a in m.ctx.must_bind if a in m.catalog and not m.effective[a][0]]


def unknown_refs(m: Model) -> list[str]:
    ids = list(m.ctx.must_bind) + [x for p in m.ctx.equivalents for x in p] + \
        [x for g in m.ctx.allow for x in g] + list(m.ctx.frame_overrides) + list(m.ctx.labels)
    return sorted({i for i in ids if i not in m.catalog})


def changed_from_default(m: Model) -> dict[str, tuple[tuple[str, str], tuple[str, str]]]:
    return {aid: ((a["default"], a["default_alt"]), m.effective[aid])
            for aid, a in m.catalog.items()
            if m.effective[aid] != (a["default"], a["default_alt"])}
