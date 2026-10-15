"""Read/write KiCad's user.hotkeys (action<TAB>primary<TAB>alternate per line).

KiCad writes the file sorted by action name (std::map) with Unix line ends;
an action missing from the file uses its compiled-in default, an action
present with an empty key is explicitly unbound.
"""

from __future__ import annotations

from pathlib import Path

from . import keys


def read(path: Path) -> dict[str, tuple[str, str]]:
    res: dict[str, tuple[str, str]] = {}
    if not path.exists():
        return res
    for line in path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n"):
        parts = line.split("\t")
        if not parts[0]:
            continue
        prim = parts[1] if len(parts) > 1 else ""
        alt = parts[2] if len(parts) > 2 else ""
        res[parts[0]] = (_safe_norm(prim), _safe_norm(alt))
    return res


def _safe_norm(text: str) -> str:
    try:
        return keys.normalize(text)
    except keys.KeyError_:
        return ""  # KiCad treats unknown names as unbound


def render(bindings: dict[str, tuple[str, str]]) -> str:
    # std::map<std::string> ordering == byte-wise ordering
    names = sorted(bindings, key=lambda s: s.encode("utf-8"))
    return "".join(f"{n}\t{bindings[n][0]}\t{bindings[n][1]}\n" for n in names)


def write(path: Path, bindings: dict[str, tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(bindings), encoding="utf-8", newline="\n")
