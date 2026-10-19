# Keymap analysis: KiCad Unlocked map on KiCad 10

The baseline is the [KiCad Unlocked](https://kicadunlocked.fullstack-electronics.com/kicad-unlocked-the-very-hottest-hotkey-map)
QWERTY map (Pat Deegan, also covered on
[Hackaday](https://hackaday.com/2025/07/17/improve-your-kicad-productivity-with-these-considered-shortcut-keys/)).
It was imported into KiCad 10 on 2025-08-04 and is captured as-is in the first commit of this repo.

The map has four principles:

- **Proximity follows frequency.** Frequent actions go on the left-hand home cluster.
- **Same purpose, same place.** An action that exists in both the schematic and PCB editors uses the same key in both.
- **Birds of a feather.** Related actions sit next to each other.
- **Typing trounces topography.** A combo that needs two hands can go anywhere.

`./kprefs analyze` runs the checks below against whatever is installed. `./kprefs check` runs them against the repo keymap.

## How KiCad resolves hotkeys

This is in `common/tool/action_manager.cpp`, `ACTION_MANAGER::RunHotKey`, and it determines what counts as a real conflict.

- If one of the actions on a key is **context-scoped** and its tool is on the active tool stack, that action wins. Router via placement and drawing posture are examples. These overlaps are fine; the checker calls them "layered".
- Otherwise KiCad tries the global actions in turn and stops at the first one that is enabled and handled. Since KiCad 10 (`PromoteUserBoundFrameAction`), a global from the editor's own namespace (`eeschema.`, `pcbnew.`) whose key differs from its default is tried first. Two globals on one key are only a real conflict when that rule doesn't pick exactly one; the checker lists the resolved ones as "shadowed" under `check -v`.
- If no binding matches a non-letter key, KiCad retries it without Shift. This is why a binding of `~` fires on Shift+`, and why `Shift+2` should be written `@`.
- On GTK, the menu bar mnemonics run **before** KiCad sees the key: `&File &Edit &View &Place Ro&ute &Inspect &Tools P&references &Help`. Alt+E, Alt+T, Alt+U and the others open menus instead of running a hotkey.

## Findings in the installed map

| Problem | Detail |
|---|---|
| Lost in the v10 migration | Group (`U`): KiCad 10 moved it from `pcbnew.EditorControl.group` to `common.Interactive.group`. Open in Footprint Editor (`Ctrl+E`): the KU file used an older name. Both were unbound. |
| ~~Conflict `R` (sch)~~ | Not real: KiCad 10 runs the editor's own user-bound action (Place Power) before a common one, so R stays the Inactive Layer View cycle in PCB |
| Conflict `Ctrl+H` (sch) | Hierarchy Navigator vs Place Directive Label |
| Conflict `Alt+3` (sch) | 3D Viewer vs Select Node |
| Conflict `K` (pcb) | Draw Text vs Sketch Tracks |
| Conflict `G` (pcb) | Track Width + vs Drag Free Angle (both global) |
| Conflict `Ctrl+L` (pcb) | Library Tree Search vs Length Tuning Settings |
| Conflict `Ctrl+Shift+A` / `Ctrl+Shift+C` (pcb, fp) | Draw Arc / Draw Circle vs Unselect All / Copy as Text |
| Inconsistent | Sch Properties was **unbound**, while PCB Properties was on `D` |
| Inconsistent | Sch Rotate CW, Select Connection, Swap and Align had no key, while PCB had them |
| Gaps | Junction, bus entry, break wire, next unit, DNP, annotate, the standalone via tool, router mode cycle, net inspector |
| Symbol editor | No keys for lines, polygon or text |

## Changes

Every change is in `keymap/keymap.toml` with a `why`. They also appear in the hotkey map as "changed" badges with the reason.

**Fixes for conflicts**

| Action | Old | New | Reason |
|---|---|---|---|
| Place Directive Label | Ctrl+H | Shift+P | label cluster: P, Ctrl+P, Shift+P |
| Select Node | Alt+3 | Shift+E | E cluster: E highlight, Ctrl+E connection, Shift+E node |
| Sketch Tracks | K | Shift+K | K is Text in every editor |
| Drag Free Angle | G | Shift+Tab | pairs with Tab = Drag 45° |
| Length Tuning Settings | Ctrl+L | Ctrl+7 | next to the 7/8/9 tuners |
| Unselect All | Ctrl+Shift+A | — | Esc clears the selection |
| Copy as Text | Ctrl+Shift+C | Ctrl+Alt+C | frees the shape cluster |

**Restored after the v10 migration:** Group `Ctrl+G` and Ungroup `Ctrl+Shift+G` (common). Open in Footprint Editor `Ctrl+D`, which matches sch Edit Symbol on `Ctrl+D`. Sch Edit Library Symbol moves to `Ctrl+Shift+E`, which matches PCB Edit Library Footprint.

**Same purpose, same place**

| Action | Schematic | PCB |
|---|---|---|
| Properties dialog | **D** (was unbound) | D |
| Edit Value / Reference | Shift+D / Alt+D | — |
| Rotate CW | Shift+R | Shift+R |
| Select/Expand Connection | Ctrl+E | Ctrl+E |
| Swap | Alt+S | Alt+S (the router's Alt+S layer-via is modal) |
| Align left/right/top/bottom | Ctrl+←→↑↓ | Ctrl+←→↑↓ |
| Rectangle / Circle / Arc / Bezier / Rule area | Ctrl+Shift+R/C/A/B/K | the same |
| Lines / Text (symbol editor) | C / K | C / K |
| Polygon (symbol editor) | Ctrl+Shift+P | Ctrl+Shift+P |

The KU single keys `3` (rectangle) and `#` (rule area) stay as alternates in the schematic editor.

**New bindings for gaps**

| Action | Key | Placement |
|---|---|---|
| Measure | M (F7 alt) | mnemonic; move is on 1 in KU, so M was free |
| Junction | Shift+J | next to J hierarchical label |
| Bus entry | Alt+2 | next to 2 bus |
| Break wire | Shift+Q | wire cluster |
| Next symbol unit | Shift+A | symbol cluster |
| Toggle DNP | Alt+N | next to N no-connect |
| Annotate | F9 | F-row project ops: F2 setup, F4 ERC/DRC, F6 switch, F8 update |
| Via tool (pcb) | Ctrl+Shift+V | Ctrl+Shift drawing cluster; S still places a via while routing |
| Cycle router mode | Shift+Q | next to Q route |
| Track & Via Properties | Shift+T | next to T via size (Alt+T would open the Tools menu) |
| Net Inspector | Ctrl+4 | next to 4 ratsnest / sch 4 net navigator |
| Edit Footprint / Assign Footprints | F / Shift+F | footprint cluster; F is KiCad's default (KU had Y, which is now free in sch) |
| Undo | Backspace (Ctrl+Z alt) | Ctrl+Z restored for muscle memory |
| Drawing-sheet editor Move | 1 | same as sch/pcb move |

## Ideas not applied

- **Dvorak or left-handed variants.** KU ships a Dvorak map. A second `keymap-*.toml` plus `--keymap` support would cover these.
- **Fast grids.** Pat suggests switching between 100 mil and 50 mil grids. Your schematic fast grids are 50 mil and 25 mil, and your PCB fast grids are 0.5 mm and 0.25 mm. Change them in `settings/eeschema.json` / `settings/pcbnew.json` under `window.grid.fast_grid_1` and `window.grid.fast_grid_2`; the values are indexes into `window.grid.sizes`.
- **Auto zone fill.** `pcbnew.editing.auto_fill_zones` is off. Turning it on removes the need for `N`, but large boards slow down.
- **Router mode.** `tools.pns.mode` is 2 (walkaround). Shift+Q now cycles highlight, shove and walkaround while you work.
