import tempfile
import unittest
from pathlib import Path

from kicadprefs import catalog, hotkeys_file, keymap, keys, settings

REPO = Path(__file__).resolve().parent.parent


class KeysTest(unittest.TestCase):
    def test_from_cpp(self):
        self.assertEqual(keys.from_cpp("MD_CTRL + 'S'"), "Ctrl+S")
        self.assertEqual(keys.from_cpp("MD_SHIFT + MD_CTRL + 'Z'"), "Ctrl+Shift+Z")
        self.assertEqual(keys.from_cpp("MD_CTRL + '+'"), "Ctrl++")
        self.assertEqual(keys.from_cpp("'\\\\'"), "\\")
        self.assertEqual(keys.from_cpp("'`'"), "`")
        self.assertEqual(keys.from_cpp("' '"), "Space")
        self.assertEqual(keys.from_cpp("MD_ALT + static_cast<int>( WXK_BACK )"), "Alt+Back")
        self.assertEqual(keys.from_cpp("WXK_F4"), "F4")
        self.assertEqual(keys.from_cpp("0"), "")

    def test_parse_normalize(self):
        self.assertEqual(keys.normalize("shift+ctrl+a"), "Ctrl+Shift+A")
        self.assertEqual(keys.normalize("Ctrl++"), "Ctrl++")
        self.assertEqual(keys.normalize("back"), "Back")
        self.assertEqual(keys.normalize(""), "")
        with self.assertRaises(keys.KeyError_):
            keys.parse("Ctrl+Banana")

    def test_physical(self):
        self.assertEqual(keys.parse("~").physical(), (frozenset({"Shift"}), "`"))
        self.assertEqual(keys.parse("Ctrl++").physical(), (frozenset({"Ctrl", "Shift"}), "="))

    def test_shift_symbol_warning(self):
        self.assertTrue(keys.warnings_for("Shift+2"))
        self.assertFalse(keys.warnings_for("Shift+A"))


class CatalogParseTest(unittest.TestCase):
    SRC = '''
// comment with TOOL_ACTION_ARGS() inside
TOOL_ACTION ACTIONS::zoomIn( TOOL_ACTION_ARGS()
        .Name( "common.Control.zoomIn" )
        .Scope( AS_GLOBAL )
#if defined( __WXMAC__ )
        .DefaultHotkey( MD_CTRL + '+' )
#else
        .DefaultHotkey( WXK_F1 )
#endif
        .FriendlyName( _( "Zoom In at Cursor" ) )
        .Tooltip( _( "Say \\"hi\\"" ) ) );

static const TOOL_ACTION ACT_Via( TOOL_ACTION_ARGS()
        .Name( "pcbnew.InteractiveRouter.PlaceVia" )
        .Scope( AS_CONTEXT )
        .DefaultHotkey( 'V' )
        .Parameter<int>( 3 ) );
'''

    def test_parse_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.cpp"
            p.write_text(self.SRC)
            acts = {a["id"]: a for a in catalog.parse_file(p)}
        self.assertEqual(acts["common.Control.zoomIn"]["default"], "F1")
        self.assertEqual(acts["common.Control.zoomIn"]["tooltip"], 'Say "hi"')
        self.assertEqual(acts["pcbnew.InteractiveRouter.PlaceVia"]["scope"], "AS_CONTEXT")
        self.assertEqual(acts["pcbnew.InteractiveRouter.PlaceVia"]["default"], "V")


class HotkeysFileTest(unittest.TestCase):
    def test_roundtrip_and_order(self):
        b = {"pcbnew.b": ("Q", ""), "common.a": ("Ctrl+S", "F2"), "Zeta.x": ("", "")}
        text = hotkeys_file.render(b)
        self.assertEqual(text.splitlines()[0], "Zeta.x\t\t")  # byte order: upper case first
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "user.hotkeys"
            hotkeys_file.write(p, b)
            self.assertEqual(hotkeys_file.read(p), b)


class SettingsTest(unittest.TestCase):
    def test_deep_merge_and_diff(self):
        cur = {"a": {"b": 1, "c": [1, 2]}, "keep": True}
        ov = {"a": {"c": [3]}, "new": {"x": 1}}
        merged = settings.deep_merge(cur, ov)
        self.assertEqual(merged, {"a": {"b": 1, "c": [3]}, "keep": True, "new": {"x": 1}})
        self.assertEqual(settings.diff(ov, merged), [])
        self.assertEqual(len(settings.diff(ov, cur)), 2)
        self.assertEqual(settings.capture(ov, cur), {"a": {"c": [1, 2]}, "new": {"x": 1}})


class ConflictTest(unittest.TestCase):
    def model(self, eff):
        cat = {
            "pcbnew.EditorControl.trackWidthInc": dict(scope="AS_GLOBAL", frames=["pcb"], tool="pcbnew.EditorControl", default="", default_alt=""),
            "pcbnew.InteractiveRouter.DragFreeAngle": dict(scope="AS_GLOBAL", frames=["pcb"], tool="pcbnew.InteractiveRouter", default="", default_alt=""),
            "pcbnew.InteractiveRouter.PlaceVia": dict(scope="AS_CONTEXT", frames=["pcb"], tool="pcbnew.InteractiveRouter", default="", default_alt=""),
        }
        ctx = keymap.Contexts(frames={"pcb": "PCB"}, common_frames=["pcb"], frame_overrides={},
                              modal_tools=["pcbnew.InteractiveRouter.PlaceVia"], categories=[],
                              category_info={}, allow=[], equivalents=[], must_bind=[])
        m = keymap.Model(cat, ctx, {k: ("", "") for k in cat})
        m.effective.update(eff)
        return m

    def test_global_conflict(self):
        m = self.model({"pcbnew.EditorControl.trackWidthInc": ("G", ""),
                        "pcbnew.InteractiveRouter.DragFreeAngle": ("G", "")})
        self.assertEqual(len(keymap.conflicts(m)), 1)

    def test_modal_layering_ok(self):
        m = self.model({"pcbnew.EditorControl.trackWidthInc": ("S", ""),
                        "pcbnew.InteractiveRouter.PlaceVia": ("S", "")})
        self.assertEqual(keymap.conflicts(m), [])
        self.assertEqual(len(keymap.layered(m)), 1)


class RepoKeymapTest(unittest.TestCase):
    """The committed keymap must be valid against the committed catalog."""

    def test_repo_keymap_has_no_errors(self):
        cat = catalog.load(REPO / "catalog" / "kicad-10.0.json")
        ctx = keymap.Contexts.load(REPO / "keymap" / "contexts.toml")
        m = keymap.effective_from_keymap(cat, keymap.Keymap.load(REPO / "keymap" / "keymap.toml"), ctx)
        self.assertEqual(m.errors, [])
        self.assertEqual(keymap.unknown_refs(m), [])


if __name__ == "__main__":
    unittest.main()
