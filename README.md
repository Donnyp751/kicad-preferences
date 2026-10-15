# kicad-preferences

KiCad 10 hotkeys and settings, kept in git, with tools to check, diff and install them, plus a searchable visual hotkey map.

- `keymap/keymap.toml` is the hotkey source of truth. It lists only the differences from KiCad's defaults.
- `keymap/contexts.toml` holds the rules: which editor each action runs in, categories and colours, modal tools, allowed overlaps, schematic↔PCB equivalents, must-have bindings, GTK menu mnemonics and keycap labels.
- `settings/*.json` are curated **overlays**. Only the keys listed there are managed, and they are deep-merged into KiCad's JSON. Window geometry, recent files and the like are never touched.
- `settings/colors/*.json` holds colour themes that are copied verbatim.
- `catalog/kicad-10.0.json` lists every KiCad action with its default keys, name, tooltip, scope and editors. It is generated from the KiCad source.
- `docs/hotkeys.html` is the generated hotkey map. Open it in a browser; it works offline. `#sch`, `#pcb` and the other tab names deep-link to an editor.
- `docs/ANALYSIS.md` explains why the keymap is the way it is.

## Usage

```sh
./kprefs check            # validate keymap: unknown ids, conflicts, GTK Alt-mnemonic clashes, gaps, sch/pcb consistency
./kprefs diff             # what install would change in ~/.config/kicad/10.0 (hotkeys, settings, themes)
./kprefs install -n       # dry run
./kprefs install          # close KiCad first; backs up touched files to ~/.config/kicad/10.0/kprefs-backups/<time>/
./kprefs docs             # regenerate docs/hotkeys.html
./kprefs analyze          # run the check report against the *installed* user.hotkeys
./kprefs capture          # after changing things in KiCad's GUI: refresh settings overlays, print hotkey diffs as TOML
./kprefs catalog --tag 10.0.7   # rebuild the action catalog from KiCad source (sparse git clone into ~/.cache)
python3 -m unittest       # tests
```

Options: `--config-dir DIR` installs to another directory, which is handy for testing. `--kicad-version 10.0` overrides version detection, which otherwise uses `kicad-cli version`.

## Workflow

1. Edit `keymap/keymap.toml`, for example `"pcbnew.InteractiveRouter.SingleTrack" = { key = "Q", why = "..." }`. Search the catalog or the hotkey map for action ids.
2. Run `./kprefs check` and fix what it reports.
3. Run `./kprefs docs`, then `./kprefs diff`, then `./kprefs install`.
4. Commit.

If you change a hotkey or setting inside KiCad, `./kprefs capture` shows the difference. Settings overlays are updated in place. Hotkey changes are printed as TOML for you to paste, so the comments in `keymap.toml` survive.

To manage another setting, add its key path, with the current value, to the matching `settings/<file>.json`. `./kprefs capture --settings` refreshes the values from your installed config.

## After a KiCad upgrade

Run `./kprefs catalog --tag <new tag>` with `--kicad-version` set if the major.minor changed. Then run `./kprefs check`. It reports renamed or removed action ids, which is how the KiCad 10 losses were found, and new default bindings that now collide.
