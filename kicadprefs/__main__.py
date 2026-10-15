"""kprefs - manage KiCad hotkeys and settings from this repo.

Commands:
  catalog   regenerate catalog/kicad-<ver>.json from KiCad source
  check     validate keymap.toml: unknown ids, conflicts, gaps, sch/pcb consistency
  build     write build/user.hotkeys
  diff      compare repo config with the installed KiCad config
  install   install hotkeys + settings overlays + colour themes (KiCad must be closed)
  capture   pull changes made in KiCad's GUI back into the repo
  docs      generate docs/hotkeys.html
  analyze   run the check report against the installed user.hotkeys
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import catalog as catalog_mod
from . import hotkeys_file, install, keymap, settings

REPO = Path(__file__).resolve().parent.parent
DEFAULT_TAG = "10.0.7"


class Paths:
    def __init__(self, args):
        self.version = args.kicad_version or install.kicad_version()
        self.catalog = REPO / "catalog" / f"kicad-{self.version}.json"
        self.keymap = REPO / "keymap" / "keymap.toml"
        self.contexts = REPO / "keymap" / "contexts.toml"
        self.settings = REPO / "settings"
        self.colors = REPO / "settings" / "colors"
        self.build = REPO / "build" / "user.hotkeys"
        self.docs = REPO / "docs" / "hotkeys.html"
        self.cfg = install.config_dir(args.config_dir, self.version)


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text


def load_model(p: Paths) -> keymap.Model:
    if not p.catalog.exists():
        sys.exit(f"missing {p.catalog.relative_to(REPO)}; run `kprefs catalog` first")
    cat = catalog_mod.load(p.catalog)
    ctx = keymap.Contexts.load(p.contexts)
    km = keymap.Keymap.load(p.keymap)
    return keymap.effective_from_keymap(cat, km, ctx)


def fname(m: keymap.Model, aid: str) -> str:
    a = m.catalog.get(aid)
    return f"{a['friendly'] or aid} [{aid}]" if a else aid


# --------------------------------------------------------------------------- report

def report(m: keymap.Model, verbose: bool = False) -> int:
    errors = list(m.errors)
    warnings = list(m.warnings)
    for ref in keymap.unknown_refs(m):
        warnings.append(f"contexts.toml references unknown action {ref}")
    confl = keymap.conflicts(m)
    for c in confl:
        line = f"{c['key']:>14}  in {','.join(c['frames'])}: " + " | ".join(fname(m, a) for a in c["actions"])
        (errors if c["severity"] == "error" else warnings).append("conflict " + line)
    for e in keymap.equivalence_report(m):
        if e["issue"] == "different keys":
            warnings.append(f"same-purpose mismatch: {fname(m, e['pair'][0])} = {e['keys'][0] or '∅'}  vs  "
                            f"{fname(m, e['pair'][1])} = {e['keys'][1] or '∅'}")
    for a in keymap.unbound_must(m):
        warnings.append(f"gap: no hotkey for {fname(m, a)}")
    for w in warnings:
        print(_c("warning: ", "33") + w)
    for e in errors:
        print(_c("error:   ", "31") + e)
    if verbose:
        for l in keymap.layered(m):
            print(f"layered {l['key']:>10} in {l['frame']}: modal {', '.join(l['modal'])} over {', '.join(l['global'])}")
    bound = sum(1 for k in m.effective.values() if k[0])
    print(f"\n{len(m.catalog)} actions, {bound} bound, {len(keymap.changed_from_default(m))} changed from "
          f"KiCad defaults; {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


# --------------------------------------------------------------------------- commands

def cmd_catalog(args, p: Paths) -> int:
    data = catalog_mod.build(args.tag)
    p.catalog.parent.mkdir(exist_ok=True)
    p.catalog.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {p.catalog.relative_to(REPO)}: {len(data['actions'])} actions from KiCad {args.tag}")
    return 0


def cmd_check(args, p: Paths) -> int:
    return report(load_model(p), args.verbose)


def cmd_analyze(args, p: Paths) -> int:
    cat = catalog_mod.load(p.catalog)
    ctx = keymap.Contexts.load(p.contexts)
    m = keymap.effective_from_file(cat, hotkeys_file.read(p.cfg / "user.hotkeys"), ctx)
    print(f"analyzing {p.cfg / 'user.hotkeys'}\n")
    return report(m, args.verbose)


def built_bindings(m: keymap.Model) -> dict[str, tuple[str, str]]:
    return dict(m.effective)


def cmd_build(args, p: Paths) -> int:
    m = load_model(p)
    if m.errors:
        report(m)
        return 1
    hotkeys_file.write(p.build, built_bindings(m))
    print(f"wrote {p.build.relative_to(REPO)} ({len(m.effective)} actions)")
    return 0


def hotkey_diff(m: keymap.Model, installed: dict[str, tuple[str, str]]) -> list[str]:
    lines = []
    for aid in sorted(m.catalog):
        a = m.catalog[aid]
        have = installed.get(aid, (a["default"], a["default_alt"]))
        want = m.effective[aid]
        if have != want:
            fmt = lambda k: k[0] + (f" / {k[1]}" if k[1] else "") if k[0] or k[1] else "∅"
            lines.append(f"  {fname(m, aid)}: {fmt(have)} → {fmt(want)}")
    return lines


def cmd_diff(args, p: Paths) -> int:
    m = load_model(p)
    installed = hotkeys_file.read(p.cfg / "user.hotkeys")
    lines = hotkey_diff(m, installed)
    print(f"hotkeys ({p.cfg / 'user.hotkeys'}): {len(lines)} differences (installed → repo)")
    print("\n".join(lines))
    total = len(lines)
    for name, ov in settings.overlays(p.settings).items():
        cur = settings.load_json(p.cfg / f"{name}.json")
        d = settings.diff(ov, cur)
        total += len(d)
        print(f"\nsettings {name}.json: {len(d)} differences (installed → repo)")
        for path, have, want in d:
            print(f"  {path}: {json.dumps(have)} → {json.dumps(want)}")
    for src in sorted(p.colors.glob("*.json")):
        dst = p.cfg / "colors" / src.name
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            total += 1
            print(f"\ncolor theme {src.name}: {'missing' if not dst.exists() else 'differs'}")
    return 0 if total == 0 or not args.exit_code else 2


def cmd_install(args, p: Paths) -> int:
    m = load_model(p)
    if report_errors_only(m):
        return 1
    procs = install.running_kicad()
    if procs and not args.config_dir and not args.force:
        print("KiCad is running (it rewrites its settings on exit). Close it first, or pass --force:")
        print("\n".join("  " + x for x in procs))
        return 1
    if not p.cfg.exists():
        sys.exit(f"KiCad config dir {p.cfg} does not exist; start KiCad once first")
    backup = install.Backup(p.cfg)
    actions: list[str] = []

    hk_path = p.cfg / "user.hotkeys"
    new_hk = hotkeys_file.render(built_bindings(m))
    if not hk_path.exists() or hk_path.read_text() != new_hk:
        actions.append(f"write {hk_path} ({len(hotkey_diff(m, hotkeys_file.read(hk_path)))} binding changes)")
        if not args.dry_run:
            backup.save(hk_path)
            hk_path.write_text(new_hk, newline="\n")

    for name, ov in settings.overlays(p.settings).items():
        path = p.cfg / f"{name}.json"
        cur = settings.load_json(path)
        d = settings.diff(ov, cur)
        if d:
            actions.append(f"merge {len(d)} settings into {path}")
            if not args.dry_run:
                backup.save(path)
                settings.dump_json(path, settings.deep_merge(cur, ov))

    for src in sorted(p.colors.glob("*.json")):
        dst = p.cfg / "colors" / src.name
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            actions.append(f"copy color theme {src.name}")
            if not args.dry_run:
                backup.save(dst)
                dst.parent.mkdir(exist_ok=True)
                shutil.copy2(src, dst)

    if not actions:
        print(f"{p.cfg} already matches the repo")
        return 0
    print(("would " if args.dry_run else "") + ("\n" + ("would " if args.dry_run else "")).join(actions))
    if backup.saved:
        print(f"backup: {backup.dir}")
    return 0


def report_errors_only(m: keymap.Model) -> bool:
    errs = m.errors + [c for c in keymap.conflicts(m) if c["severity"] == "error"]
    if errs:
        print("keymap has errors; run `kprefs check`")
    return bool(errs)


def toml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def cmd_capture(args, p: Paths) -> int:
    do_hk = args.hotkeys or not args.settings
    do_set = args.settings or not args.hotkeys
    if do_hk:
        cat = catalog_mod.load(p.catalog)
        installed = hotkeys_file.read(p.cfg / "user.hotkeys")
        if args.write_keymap:
            text = render_keymap(cat, installed, p.version)
            p.keymap.write_text(text)
            print(f"wrote {p.keymap.relative_to(REPO)} from {p.cfg / 'user.hotkeys'}")
        else:
            m = load_model(p)
            lines = []
            for aid in sorted(cat):
                a = cat[aid]
                have = installed.get(aid, (a["default"], a["default_alt"]))
                if have != m.effective[aid]:
                    lines.append(_toml_bind_line(aid, have, a))
            print("# hotkeys changed in KiCad that differ from keymap.toml; paste into [bind]:" if lines
                  else "# installed hotkeys match keymap.toml")
            print("\n".join(lines))
    if do_set:
        for name, ov in settings.overlays(p.settings).items():
            cur = settings.load_json(p.cfg / f"{name}.json")
            new = settings.capture(ov, cur)
            if new != ov:
                (p.settings / f"{name}.json").write_text(json.dumps(new, indent=2, sort_keys=True) + "\n")
                print(f"updated settings/{name}.json from installed values")
    return 0


def _toml_bind_line(aid: str, keys_: tuple[str, str], a: dict) -> str:
    prim, alt = keys_
    friendly = f"  # {a['friendly']}" if a.get("friendly") else ""
    if alt == a["default_alt"]:
        return f"{toml_str(aid)} = {toml_str(prim)}{friendly}"
    return f"{toml_str(aid)} = {{ key = {toml_str(prim)}, alt = {toml_str(alt)} }}{friendly}"


def render_keymap(cat: dict[str, dict], installed: dict[str, tuple[str, str]], version: str) -> str:
    out = [
        "# KiCad keymap - source of truth for user.hotkeys.",
        "# Only differences from KiCad's built-in defaults are listed; everything else",
        "# keeps its default.  \"\" unbinds.  Table form: { key = ..., alt = ..., why = ... }",
        "",
        "[meta]",
        f'kicad = "{version}"',
        'layout = "qwerty"',
        "",
        "[bind]",
    ]
    by_tool: dict[str, list[str]] = {}
    for aid in sorted(cat, key=lambda s: s.lower()):
        a = cat[aid]
        if aid not in installed:
            continue
        have = installed[aid]
        if have != (a["default"], a["default_alt"]):
            by_tool.setdefault(a["tool"], []).append(_toml_bind_line(aid, have, a))
    for tool, lines in by_tool.items():
        out.append(f"\n# --- {tool}")
        out.extend(lines)
    return "\n".join(out) + "\n"


def cmd_docs(args, p: Paths) -> int:
    from . import docs
    m = load_model(p)
    p.docs.parent.mkdir(exist_ok=True)
    p.docs.write_text(docs.render(m, version=p.version))
    print(f"wrote {p.docs.relative_to(REPO)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kprefs", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config-dir", help="KiCad config dir (default: ~/.config/kicad/<version>)")
    ap.add_argument("--kicad-version", help="major.minor, default from `kicad-cli version`")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("catalog"); s.add_argument("--tag", default=DEFAULT_TAG)
    s = sub.add_parser("check"); s.add_argument("-v", "--verbose", action="store_true")
    s = sub.add_parser("analyze"); s.add_argument("-v", "--verbose", action="store_true")
    sub.add_parser("build")
    s = sub.add_parser("diff"); s.add_argument("--exit-code", action="store_true",
                                               help="exit 2 when differences exist")
    s = sub.add_parser("install")
    s.add_argument("-n", "--dry-run", action="store_true")
    s.add_argument("--force", action="store_true", help="install even if KiCad is running")
    s = sub.add_parser("capture")
    s.add_argument("--hotkeys", action="store_true")
    s.add_argument("--settings", action="store_true")
    s.add_argument("--write-keymap", action="store_true",
                   help="overwrite keymap.toml from the installed file (loses comments/why)")
    sub.add_parser("docs")
    args = ap.parse_args(argv)
    p = Paths(args)
    return globals()[f"cmd_{args.cmd}"](args, p)


if __name__ == "__main__":
    sys.exit(main())
