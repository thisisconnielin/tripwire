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

    def test_add_competitor_keeps_comments(self):
        import tempfile
        d = Path(tempfile.mkdtemp()) / "watch" / "targets.yml"
        d.parent.mkdir()
        d.write_text("# my list\ncompetitors:\n  - name: A\n    pages:\n      - { label: home, url: https://a.com }\n")
        self.assertTrue(s.add_competitor(d, "Beta: Co", "https://b.com", pricing="https://b.com/p", group="direct", reason="same ICP"))
        self.assertFalse(s.add_competitor(d, "beta: co", "https://b.com"))
        self.assertIn("# my list", d.read_text())
        t = s.load_targets(d)
        self.assertEqual([x["slug"] for x in t], ["a-home", "beta-co-home", "beta-co-pricing"])
        e = d.parent / "new.yml"
        s.add_competitor(e, "C", "https://c.com")
        self.assertEqual(len(s.load_targets(e)), 1)
        f = d.parent / "empty.yml"
        f.write_text("# x\ncompetitors: []\n")
        s.add_competitor(f, "D", "https://d.com")
        self.assertEqual(len(s.load_targets(f)), 1)

    def test_request_ids_are_noise(self):
        html = "<p>Plans</p><p>This is the Trace Id: b365d2b2606f17ec4096ea94267a5f26</p><p>ref d1cc886fca5d8043f2759b80b6a411d8</p>"
        self.assertEqual(s.extract_lines(html, s.DEFAULT_IGNORE)[1], ["Plans", "ref"])

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


class TestFetch(unittest.TestCase):
    def test_308_is_followed(self):
        import urllib.request
        req = urllib.request.Request("https://a.example/old")
        new = s._Redirects().redirect_request(req, None, 308, "Permanent Redirect", {}, "https://a.example/new")
        self.assertEqual(new.full_url, "https://a.example/new")

    def test_retries_transient_errors_once(self):
        import io, urllib.error
        from unittest import mock

        class Resp(io.BytesIO):
            headers = mock.Mock(get_content_charset=lambda: "utf-8")

        calls = [urllib.error.URLError("timed out"), Resp(b"<p>ok</p>")]
        def open_(req, timeout):
            r = calls.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        with mock.patch.object(s._OPENER, "open", side_effect=open_), mock.patch.object(s, "RETRY_DELAY", 0):
            self.assertEqual(s.fetch("https://a.example"), "<p>ok</p>")

    def test_403_is_not_retried(self):
        import urllib.error
        from unittest import mock
        err = urllib.error.HTTPError("https://a.example", 403, "Forbidden", {}, None)
        with mock.patch.object(s._OPENER, "open", side_effect=err) as o, mock.patch.object(s, "RETRY_DELAY", 0):
            with self.assertRaises(urllib.error.HTTPError):
                s.fetch("https://a.example")
            self.assertEqual(o.call_count, 1)


class TestScan(unittest.TestCase):
    def test_only_keeps_other_pages_health(self):
        import tempfile
        from unittest import mock
        targets = [{"competitor": c, "group": "direct", "label": "home", "url": f"https://{c}.example",
                    "slug": f"{c}-home", "ignore": s.DEFAULT_IGNORE, "min_lines": 1} for c in ("a", "b")]
        html = (FX / "v1.html").read_text()
        with tempfile.TemporaryDirectory() as d, mock.patch.object(s, "fetch", return_value=html) as f:
            wd = Path(d)
            s.scan(targets, "2026-11-03T05:00:00+00:00", wd)
            s.scan(targets, "2026-11-04T05:00:00+00:00", wd, only="A")
            self.assertEqual(f.call_count, 3)                       # 2 pages, then only a
            status = s.load_json(wd / "data" / "status.json", {})
            self.assertEqual([t["slug"] for t in status["targets"]], ["a-home", "b-home"])
            self.assertEqual(status["targets"][1]["last_checked"], "2026-11-03T05:00:00+00:00")


class TestAddCompetitor(unittest.TestCase):
    def add(self, text, **kw):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "targets.yml"
            cfg.write_text(text)
            s.add_competitor(cfg, "B", "https://b.com", **kw)
            out = cfg.read_text()
            return out, [c["name"] for c in s.yaml.safe_load(out)["competitors"]]

    def test_keys_after_the_list_stay_put(self):
        out, names = self.add("competitors:\n  - name: A\n    pages:\n      - { label: home, url: https://a.com }\n"
                              "\nignore: [cookie]  # keep\n")
        self.assertEqual(names, ["A", "B"])
        self.assertTrue(out.rstrip().endswith("ignore: [cookie]  # keep"))

    def test_indentless_list(self):
        _, names = self.add("competitors:\n- name: A\n  pages:\n  - { label: home, url: https://a.com }\n")
        self.assertEqual(names, ["A", "B"])

    def test_empty_flow_list_and_missing_key(self):
        self.assertEqual(self.add("min_lines: 1\ncompetitors: []\n")[1], ["B"])
        self.assertEqual(self.add("min_lines: 1\n")[1], ["B"])


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
        self.assertIn("**2 page changes**", text)
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


class TestIntel(unittest.TestCase):
    NOW = "2026-11-03T04:00:00+00:00"

    def test_add_dedupes_and_validates(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            wd = Path(d)
            items = [{"competitor": "Acme", "type": "launch", "title": "Acme Agents", "url": "https://acme.com/blog/agents/"},
                     {"competitor": "Newco", "type": "competitor_added", "title": "Newco", "summary": "Same ICP"}]
            self.assertEqual(s.add_intel(wd, items, self.NOW), (2, 0))
            again = [{"competitor": "Acme", "type": "social", "title": "Repost", "url": "https://ACME.com/blog/agents"}]
            self.assertEqual(s.add_intel(wd, items + again, self.NOW), (0, 3))
            with self.assertRaises(ValueError):
                s.add_intel(wd, [{"competitor": "A", "type": "rumor", "title": "x", "url": "u"}], self.NOW)
            with self.assertRaises(ValueError):
                s.add_intel(wd, [{"competitor": "A", "type": "news", "title": "no url"}], self.NOW)

    def test_report_sections(self):
        intel = [{"competitor": "Acme", "type": "launch", "title": "Acme Agents", "url": "https://a", "date": "2026-11-02",
                  "source": "X", "summary": "Agents in group chat", "found": self.NOW},
                 {"competitor": "Newco", "type": "competitor_added", "title": "Newco", "summary": "Same ICP",
                  "found": self.NOW},
                 {"competitor": "Old", "type": "news", "title": "Old news", "url": "https://o", "date": "2026-10-01",
                  "found": "2026-10-01T04:00:00+00:00"}]
        text = s.render_report([], {}, self.NOW, days=1, intel=intel)
        self.assertIn("**1 launch / news / social item**", text)
        self.assertIn("**New competitor: Newco**: Same ICP", text)
        self.assertIn("- `launch` [Acme Agents](https://a) (2026-11-02, X): Agents in group chat", text)
        self.assertNotIn("Old news", text)
        self.assertLess(text.index("## Launches"), text.index("## Website changes"))

    def test_report_tolerates_hand_edited_items(self):
        intel = [{"competitor": "Acme", "type": "news", "title": "Date only", "url": "https://a", "date": "2026-11-03"},
                 {"competitor": "Acme", "type": "social", "title": "No url", "found": self.NOW},
                 {"competitor": "Acme", "type": "rumor", "title": "Bad type", "found": self.NOW},
                 {"competitor": "Acme", "type": "news", "title": "Bad date", "url": "https://b", "found": "yesterday"}]
        text = s.render_report([{"type": "change", "date": "garbage"}], {}, self.NOW, days=1, intel=intel)
        self.assertIn("[Date only](https://a)", text)
        self.assertIn("`social` No url", text)
        self.assertNotIn("Bad type", text)
        self.assertNotIn("Bad date", text)


class TestRepo(unittest.TestCase):
    def test_plugin_version_matches_version_file(self):
        import json
        root = Path(__file__).resolve().parents[1]
        plugin = json.loads((root / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(plugin["version"], (root / "VERSION").read_text().strip())


if __name__ == "__main__":
    unittest.main()
