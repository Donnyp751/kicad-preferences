"""Build the KiCad action catalog from KiCad's C++ source.

Every hotkey-able command in KiCad is a TOOL_ACTION declared with the
TOOL_ACTION_ARGS() builder, e.g.::

    TOOL_ACTION ACTIONS::save( TOOL_ACTION_ARGS()
            .Name( "common.Control.save" )
            .Scope( AS_GLOBAL )
            .DefaultHotkey( MD_CTRL + 'S' )
            .FriendlyName( _( "Save" ) )
            .Tooltip( _( "Save changes" ) ) );

We extract name, scope, default hotkeys, friendly name and tooltip, and work
out which editor frames reference each action (used for conflict checking).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from . import keys

REPO_URL = "https://gitlab.com/kicad/code/kicad.git"
SPARSE_DIRS = ["common", "eeschema", "pcbnew", "3d-viewer", "gerbview",
               "pagelayout_editor", "kicad", "cvpcb", "include"]
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "kicad-preferences" / "src"

# Linux build: platform macros that are defined.
DEFINED_MACROS = {"__WXGTK__", "__linux__", "__UNIX__", "__unix__"}
PLATFORM_MACROS = {"__WXMAC__", "__APPLE__", "__WXMSW__", "_WIN32", "__WINDOWS__",
                   "__WXOSX__", "__WXOSX_MAC__"} | DEFINED_MACROS


def ensure_source(tag: str) -> Path:
    dest = CACHE / tag
    if (dest / "common" / "tool" / "actions.cpp").exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", tag, "--filter=blob:none",
                    "--sparse", REPO_URL, str(dest)], check=True)
    subprocess.run(["git", "-C", str(dest), "sparse-checkout", "set", *SPARSE_DIRS], check=True)
    return dest


# --------------------------------------------------------------------------- C++ helpers

def strip_comments(src: str) -> str:
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in "\"'":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:j + 1])
            i = j + 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            out.append(" ")
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _eval_cond(directive: str, cond: str) -> bool:
    if directive == "ifdef":
        return cond.strip() in DEFINED_MACROS if cond.strip() in PLATFORM_MACROS else True
    if directive == "ifndef":
        return cond.strip() not in DEFINED_MACROS if cond.strip() in PLATFORM_MACROS else True
    if not any(m in cond for m in PLATFORM_MACROS):
        return True  # unrelated build options: assume enabled
    expr = re.sub(r"defined\s*\(\s*(\w+)\s*\)", lambda m: str(m.group(1) in DEFINED_MACROS), cond)
    expr = re.sub(r"\b(" + "|".join(PLATFORM_MACROS) + r")\b",
                  lambda m: str(m.group(1) in DEFINED_MACROS), expr)
    expr = expr.replace("||", " or ").replace("&&", " and ").replace("!", " not ")
    try:
        return bool(eval(expr, {"__builtins__": {}}, {}))  # noqa: S307 - tiny boolean expr
    except Exception:
        return True


def preprocess(src: str) -> str:
    """Resolve #if/#ifdef blocks that depend on platform macros (Linux build)."""
    out, stack = [], []  # stack of (parent_active, this_active, taken)
    active = True
    for line in src.split("\n"):
        m = re.match(r"\s*#\s*(ifdef|ifndef|if|elif|else|endif)\b(.*)", line)
        if not m:
            if active:
                out.append(line)
            continue
        d, rest = m.group(1), m.group(2)
        if d in ("if", "ifdef", "ifndef"):
            cond = _eval_cond(d, rest)
            stack.append((active, cond, cond))
            active = active and cond
        elif d == "elif" and stack:
            parent, _, taken = stack.pop()
            cond = not taken and _eval_cond("if", rest)
            stack.append((parent, cond, taken or cond))
            active = parent and cond
        elif d == "else" and stack:
            parent, _, taken = stack.pop()
            stack.append((parent, not taken, True))
            active = parent and not taken
        elif d == "endif" and stack:
            parent, _, _ = stack.pop()
            active = parent
    return "\n".join(out)


def _balanced(src: str, start: int) -> int:
    """Index just past the ')' matching the '(' at src[start]."""
    depth, i, n = 0, start, len(src)
    while i < n:
        c = src[i]
        if c in "\"'":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            i = j + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unbalanced parentheses")


def _c_strings(arg: str) -> str:
    parts = re.findall(r'"((?:\\.|[^"\\])*)"', arg)
    s = "".join(parts)
    return s.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8") if s else ""


def _methods(block: str) -> dict[str, str]:
    """Top-level `.Method( args )` calls of a TOOL_ACTION_ARGS() builder chain."""
    res: dict[str, str] = {}
    for m in re.finditer(r"\.\s*(\w+)\s*(?:<[^>]*>)?\s*\(", block):
        start = m.end() - 1
        try:
            end = _balanced(block, start)
        except ValueError:
            continue
        res.setdefault(m.group(1), block[start + 1:end - 1])
    return res


DECL_RE = re.compile(
    r"TOOL_ACTION\s+(?:(?P<cls>\w+)::)?(?P<member>\w+)\s*\(\s*TOOL_ACTION_ARGS\s*\(\s*\)")


def parse_file(path: Path) -> list[dict]:
    src = preprocess(strip_comments(path.read_text(encoding="utf-8", errors="replace")))
    actions = []
    for m in DECL_RE.finditer(src):
        open_paren = src.index("(", m.start("member") + len(m.group("member")))
        block = src[m.end():_balanced(src, open_paren) - 1]
        meth = _methods(block)
        name = _c_strings(meth.get("Name", ""))
        if not name:
            continue
        actions.append({
            "id": name,
            "member": m.group("member"),
            "cls": m.group("cls") or "",
            "scope": meth.get("Scope", "AS_CONTEXT").strip(),
            "default": keys.from_cpp(meth.get("DefaultHotkey", "")),
            "default_alt": keys.from_cpp(meth.get("DefaultHotkeyAlt", "")),
            "friendly": _c_strings(meth.get("FriendlyName", "")),
            "tooltip": _c_strings(meth.get("Tooltip", "")),
            "source": "",
        })
    return actions


# --------------------------------------------------------------------------- frames

FRAME_RULES = {
    # app prefix -> list of (regex on relative path, frame)
    "eeschema": [(r"sim/|simulator", "sim"),
                 (r"symbol_editor|symbol_viewer|lib_symbol|symbol_edit|symbol_lib|symbol_tree|toolbars_symbol",
                  "symedit"),
                 (r".", "sch")],
    "pcbnew": [(r"footprint_wizard", "fpedit"),
               (r"footprint_edit|footprint_viewer|fp_|pad_tool|toolbars_footprint|footprint_libraries|"
                r"footprint_tree|menubar_footprint", "fpedit"),
               (r".", "pcb")],
}
APP_FRAMES = {"common": ["*"], "kicad": ["kicad"], "3DViewer": ["3d"], "gerbview": ["gerbview"],
              "plEditor": ["pl"], "cvpcb": ["cvpcb"]}
ACTION_CLS = {"eeschema": "SCH_ACTIONS", "pcbnew": "PCB_ACTIONS"}


def assign_frames(root: Path, actions: list[dict]) -> None:
    """Find which editor frames reference each eeschema/pcbnew action."""
    refs: dict[str, dict[str, set[str]]] = {"eeschema": {}, "pcbnew": {}}
    for app, cls in ACTION_CLS.items():
        pat = re.compile(cls + r"::(\w+)")
        for p in (root / app).rglob("*.cpp"):
            rel = p.relative_to(root / app).as_posix()
            if rel.endswith("_actions.cpp"):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            members = set(pat.findall(text))
            if not members:
                continue
            frame = next(f for rx, f in FRAME_RULES[app] if re.search(rx, rel))
            for mem in members:
                refs[app].setdefault(mem, set()).add(frame)
    for a in actions:
        app = a["id"].split(".")[0]
        if app in APP_FRAMES:
            a["frames"] = APP_FRAMES[app]
        elif app in refs:
            if a["cls"] in ("SCH_ACTIONS", "PCB_ACTIONS"):
                f = refs[app].get(a["member"])
            else:  # file-static actions (e.g. router) belong to the file's frame
                f = {next(f for rx, f in FRAME_RULES[app] if re.search(rx, a["source"]))}
            a["frames"] = sorted(f) if f else (["sch"] if app == "eeschema" else ["pcb"])
        else:
            a["frames"] = [app]


def build(tag: str) -> dict:
    root = ensure_source(tag)
    actions: dict[str, dict] = {}
    for p in sorted(root.rglob("*.cpp")):
        if "TOOL_ACTION_ARGS" not in p.read_text(encoding="utf-8", errors="replace"):
            continue
        rel = p.relative_to(root).as_posix()
        for a in parse_file(p):
            a["source"] = rel
            actions.setdefault(a["id"], a)
    lst = list(actions.values())
    assign_frames(root, lst)
    for a in lst:
        a["tool"] = a["id"].rsplit(".", 1)[0]
        a["app"] = a["id"].split(".")[0]
        a.pop("cls", None)
        a.pop("member", None)
    return {"kicad_tag": tag, "actions": sorted(lst, key=lambda a: a["id"])}


def load(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text())
    return {a["id"]: a for a in data["actions"]}
