"""Run: python -m unittest discover tests"""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stakeout as s

FX = Path(__file__).parent / "fixtures"


class TestStakeout(unittest.TestCase):
    def lines(self, name):
        return s.extract_lines((FX / name).read_text(), s.DEFAULT_IGNORE)[1]

    def test_extract_drops_scripts_and_noise(self):
        lines = self.lines("v1.html")
        self.assertIn("Starting at $10/mo per seat", lines)   # inline tags stay on one line
        self.assertFalse(any("var x" in l for l in lines))     # scripts stripped
        self.assertFalse(any("©" in l for l in lines))         # footer noise stripped

    def test_diff_and_tags(self):
        added, removed = s.diff_lines(self.lines("v1.html"), self.lines("v2.html"))
        self.assertIn("$29/mo per seat", added)
        self.assertIn("$25/mo per seat", removed)
        self.assertIn("pricing", s.tag_change(added, removed))

    def test_no_change_is_quiet(self):
        a = self.lines("v1.html")
        self.assertEqual(s.diff_lines(a, a), ([], []))

    def test_moved_lines_ignored(self):
        self.assertEqual(s.diff_lines(["a", "b", "c"], ["c", "a", "b"]), ([], []))

    def test_disabled_pages_skipped(self):
        import tempfile, os
        cfg = "competitors:\n  - name: A\n    pages:\n      - { label: x, url: https://a.com }\n      - { label: y, url: https://a.com/y, enabled: false }\n"
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
            f.write(cfg)
        try:
            self.assertEqual([t["label"] for t in s.load_targets(f.name)], ["x"])
        finally:
            os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
