"""Hotkey string handling.

KiCad stores hotkeys in user.hotkeys as strings such as ``Ctrl+Shift+Z``,
``Back`` or ``~`` (see ``KeyNameFromKeyCode`` in common/hotkeys_basic.cpp).
Modifiers are always written in the order Ctrl, Alt, Shift.  Printable ASCII
keys are written as the character itself; letters are upper case.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MOD_ORDER = ("Ctrl", "Alt", "Shift", "Meta", "Win", "AltGr")

# Named (non printable) keys that KiCad knows, in hotkeyNameList order.
NAMED_KEYS = (
    [f"F{i}" for i in range(1, 25)]
    + ["Esc", "Del", "Tab", "Back", "Ins", "Home", "End", "PgUp", "PgDn",
       "Up", "Down", "Left", "Right", "Return", "Space"]
    + [f"Num Pad {c}" for c in "0123456789+-*/."]
    + ["Num Pad Enter", "Num Pad F1", "Num Pad F2", "Num Pad F3", "Num Pad F4",
       "Click", "DblClick", "Wheel"]
)
_NAMED_LOWER = {k.lower(): k for k in NAMED_KEYS}

# wxWidgets key codes used in KiCad action definitions -> KiCad key names.
WXK_NAMES = {
    "WXK_ESCAPE": "Esc", "WXK_DELETE": "Del", "WXK_TAB": "Tab", "WXK_BACK": "Back",
    "WXK_INSERT": "Ins", "WXK_HOME": "Home", "WXK_END": "End", "WXK_PAGEUP": "PgUp",
    "WXK_PAGEDOWN": "PgDn", "WXK_UP": "Up", "WXK_DOWN": "Down", "WXK_LEFT": "Left",
    "WXK_RIGHT": "Right", "WXK_RETURN": "Return", "WXK_SPACE": "Space",
    "WXK_ADD": "+", "WXK_SUBTRACT": "-",
    "PSEUDO_WXK_CLICK": "Click", "PSEUDO_WXK_DBLCLICK": "DblClick", "PSEUDO_WXK_WHEEL": "Wheel",
    **{f"WXK_F{i}": f"F{i}" for i in range(1, 25)},
    **{f"WXK_NUMPAD{i}": f"Num Pad {i}" for i in range(10)},
}
MOD_TOKENS = {"MD_CTRL": "Ctrl", "MD_ALT": "Alt", "MD_SHIFT": "Shift",
              "MD_META": "Meta", "MD_SUPER": "Win", "MD_ALTGR": "AltGr"}

# US-QWERTY: shifted character -> unshifted physical key.  KiCad's dispatcher
# (ACTION_MANAGER::RunHotKey) retries a non-letter key without Shift, so a
# binding of "~" fires on Shift+` and "Ctrl++" fires on Ctrl+Shift+=.
SHIFTED = {
    "~": "`", "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7",
    "*": "8", "(": "9", ")": "0", "_": "-", "+": "=", "{": "[", "}": "]", "|": "\\",
    ":": ";", '"': "'", "<": ",", ">": ".", "?": "/",
}


class KeyError_(ValueError):
    pass


@dataclass(frozen=True)
class Key:
    mods: tuple[str, ...]
    base: str  # KiCad key name, e.g. "Q", "~", "Back", "F4"

    def __str__(self) -> str:
        return "+".join([*self.mods, self.base])

    def physical(self) -> tuple[frozenset[str], str]:
        """Return (modifiers, physical key cap) on a US keyboard."""
        mods = set(self.mods)
        base = self.base
        if base in SHIFTED:
            mods.add("Shift")
            base = SHIFTED[base]
        return frozenset(mods), base


def parse(text: str) -> Key | None:
    """Parse a KiCad key string. Empty string -> None (unbound)."""
    text = text.strip()
    if not text:
        return None
    mods: list[str] = []
    rest = text
    while True:
        for m in MOD_ORDER + ("Cmd", "Option", "Super"):
            if rest.lower().startswith(m.lower() + "+") and len(rest) > len(m) + 1:
                canon = {"Cmd": "Ctrl", "Option": "Alt", "Super": "Win"}.get(m, m)
                if canon not in mods:
                    mods.append(canon)
                rest = rest[len(m) + 1:]
                break
        else:
            break
    if len(rest) == 1 and " " < rest < "\x7f":
        base = rest.upper() if rest.isalpha() else rest
    elif rest.lower() in _NAMED_LOWER:
        base = _NAMED_LOWER[rest.lower()]
    else:
        raise KeyError_(f"unknown key {text!r}")
    return Key(tuple(m for m in MOD_ORDER if m in mods), base)


def normalize(text: str) -> str:
    k = parse(text)
    return str(k) if k else ""


def warnings_for(text: str) -> list[str]:
    """Bindings that parse but probably will not behave as intended."""
    k = parse(text)
    if not k:
        return []
    out = []
    if "Shift" in k.mods and len(k.base) == 1 and not k.base.isalpha():
        inv = {v: s for s, v in SHIFTED.items()}
        hint = inv.get(k.base)
        if hint and set(k.mods) == {"Shift"}:
            out.append(f"{text!r}: Shift+non-letter arrives as {hint!r}; bind {hint!r} instead")
    return out


def from_cpp(expr: str) -> str:
    """Convert a C++ DefaultHotkey(...) expression into a KiCad key string.

    Examples: ``MD_CTRL + 'S'`` -> ``Ctrl+S``, ``static_cast<int>( WXK_BACK )`` -> ``Back``.
    """
    expr = expr.strip()
    if not expr or expr == "0":
        return ""
    # char literals may contain '+' so tokenise rather than split
    tokens = re.findall(r"'(?:\\.|[^'])'|[A-Za-z_][A-Za-z_0-9]*|\d+", expr)
    mods: set[str] = set()
    base = None
    for t in tokens:
        if t in MOD_TOKENS:
            mods.add(MOD_TOKENS[t])
        elif t in WXK_NAMES:
            base = WXK_NAMES[t]
        elif t.startswith("'"):
            ch = t[1:-1]
            ch = {"\\\\": "\\", "\\'": "'", '\\"': '"'}.get(ch, ch)
            base = "Space" if ch == " " else ch
        elif t in ("static_cast", "int"):
            continue
        elif t.isdigit():
            if int(t) == 0:
                continue
            raise KeyError_(f"numeric key code in {expr!r}")
        else:
            raise KeyError_(f"unknown token {t!r} in {expr!r}")
    if base is None:
        return ""
    return str(Key(tuple(m for m in MOD_ORDER if m in mods), base))
