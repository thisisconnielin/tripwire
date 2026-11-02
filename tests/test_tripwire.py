"""Run: python -m unittest discover tests"""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "tripwire" / "scripts"))
import tripwire as s

FX = Path(__file__).parent / "fixtures"


class TestTripwire(unittest.TestCase):
    def lines(self, name):
        return s.extract_lines((FX / name).read_text(), s.DEFAULT_IGNORE)[1]

    def test_extract_drops_scripts_and_noise(self):
        lines = self.lines("v1.html")
        self.assertIn("Starting at $10/mo per seat", lines)   # inline tags stay on one line
        self.assertFalse(any("var x" in l for l in lines))     # scripts stripped
        self.assertFalse(any("©" in l for l in lines))         # footer noise stripped

    def test_js_only_page_falls_back_to_meta(self):
        html = ('<html><head><title>T</title><meta name="description" content="Agents with email">'
                '<meta property="og:title" content="Cue"></head><body><div id="root"></div>'
                '<script>x</script></body></html>')
        self.assertEqual(s.extract_lines(html, [])[1], ["Agents with email", "Cue"])
        self.assertEqual(s.extract_lines("<html><body></body></html>", [])[1], [])

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


class TestReport(unittest.TestCase):
    NOW = "2026-11-03T05:00:00+00:00"

    def event(self, competitor, label, date, type_="change", tags=("pricing",), added=("$29/mo",), removed=("$25/mo",)):
        return {"type": type_, "competitor": competitor, "label": label, "url": f"https://{label}.example",
                "date": date, "tags": list(tags), "summary": f"{competitor} {label} summary",
                "added": list(added), "removed": list(removed)}

    def test_empty_data(self):
        text = s.render_report([], {}, self.NOW)
        self.assertIn("0 pages watched", text)
        self.assertIn("No changes.", text)

    def test_daily_report_window_order_and_health(self):
        changes = [
            self.event("Zed", "home", "2026-11-03T05:00:00+00:00", tags=["messaging"], added=["New headline"], removed=[]),
            self.event("Acme", "pricing", "2026-11-03T05:00:00+00:00"),
            self.event("Old", "pricing", "2026-10-30T05:00:00+00:00"),
            self.event("Newbie", "home", "2026-11-03T05:00:00+00:00", type_="baseline", tags=["baseline"], added=[], removed=[]),
        ]
        status = {"targets": [{"competitor": "Acme", "label": "pricing", "url": "u", "ok": True},
                              {"competitor": "Blocked", "label": "news", "url": "u", "ok": False, "error": "HTTP Error 403"}]}
        text = s.render_report(changes, status, self.NOW, days=1)
        self.assertIn("**2 changes**", text)
        self.assertNotIn("Old", text)                                  # outside the window
        self.assertLess(text.index("### Acme"), text.index("### Zed"))  # pricing first
        self.assertIn("+ $29/mo", text)
        self.assertIn("- $25/mo", text)
        self.assertIn("| Blocked |", text)
        self.assertIn("Newbie", text)

    def test_digest_covers_more_days(self):
        changes = [self.event("Old", "pricing", "2026-10-30T05:00:00+00:00")]
        text = s.render_report(changes, {}, self.NOW, days=7)
        self.assertIn("Tripwire digest: 2026-10-27 to 2026-11-03", text)
        self.assertIn("### Old", text)

    def test_scan_and_report_commands_use_config_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "watch" / "targets.yml"
            s.main(["init", "--config", str(cfg)])
            self.assertTrue(cfg.exists())
            s.main(["report", "--config", str(cfg), "--days", "7", "--out", "week.md"])
            self.assertTrue((cfg.parent / "reports" / "week.md").exists())
            self.assertTrue((cfg.parent / "reports" / "latest.md").exists())


if __name__ == "__main__":
    unittest.main()
