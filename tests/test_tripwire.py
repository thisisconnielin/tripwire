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

    def test_title_ignores_svg_titles_and_whitespace(self):
        html = ("<html><head><title>Slack Pricing\n   Plans</title></head><body>"
                "<svg><title>Included</title></svg><p>Pro</p><svg><title>Included</title></svg></body></html>")
        self.assertEqual(s.extract_lines(html, [])[0], "Slack Pricing Plans")

    def test_block_pages_are_detected(self):
        self.assertIn("blocked", s.blocked_reason("Your request has been blocked. This could be", ["Skip"]))
        self.assertIsNotNone(s.blocked_reason("Just a moment...", []))
        self.assertIsNone(s.blocked_reason("Slack Pricing Plans", ["Pro", "Business+"]))

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
            geturl = lambda self: "https://a.example"

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

    def test_block_page_is_an_error_not_a_change(self):
        import tempfile
        from unittest import mock
        t = [{"competitor": "M", "group": "platform", "label": "home", "url": "https://m.example",
              "slug": "m-home", "ignore": s.DEFAULT_IGNORE, "min_lines": 1}]
        blocked = "<title>Your request has been blocked</title><p>Skip</p>"
        with tempfile.TemporaryDirectory() as d:
            wd = Path(d)
            with mock.patch.object(s, "fetch", return_value=(FX / "v1.html").read_text()):
                s.scan(t, "2026-11-03T05:00:00+00:00", wd)
            snap = (wd / "snapshots" / "m-home.txt").read_text()
            with mock.patch.object(s, "fetch", return_value=blocked):
                self.assertEqual(s.scan(t, "2026-11-04T05:00:00+00:00", wd), [])
            self.assertEqual((wd / "snapshots" / "m-home.txt").read_text(), snap)   # snapshot kept
            self.assertFalse(s.load_json(wd / "data" / "status.json", {})["targets"][0]["ok"])


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


class TestCheck(unittest.TestCase):
    def test_reports_identity_and_redirects(self):
        import tempfile
        from unittest import mock
        cfg_text = ("competitors:\n"
                    "  - name: Lio\n    fit: AI teammates in group chat\n    pages:\n"
                    "      - { label: pricing, url: https://lio.example/pricing }\n"
                    "      - { label: home, url: https://lio.example }\n"
                    "  - name: Gone\n    pages:\n      - { label: home, url: https://gone.example }\n"
                    "  - name: Off\n    enabled: false\n    pages:\n      - { label: home, url: https://off.example }\n")
        html = ('<html><head><title>Lio | AI Procurement</title>'
                '<meta name="description" content="Procurement agents for enterprises"></head>'
                '<body><h1>Buy smarter</h1><p>Spend less</p></body></html>')
        pages = {"https://lio.example": (html, "https://lio.example/"),
                 "https://gone.example": (html, "https://acquirer.example/welcome")}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(s, "fetch_page", side_effect=lambda u: pages[u]):
            cfg = Path(d) / "targets.yml"
            cfg.write_text(cfg_text)
            rows = s.check_competitors(cfg)
        self.assertEqual([r["competitor"] for r in rows], ["Lio", "Gone"])      # disabled skipped
        lio, gone = rows
        self.assertEqual(lio["url"], "https://lio.example")                     # home page preferred
        self.assertEqual(lio["description"], "Procurement agents for enterprises")
        self.assertEqual(lio["opening"][:2], ["Buy smarter", "Spend less"])
        self.assertFalse(lio["redirected_to_other_site"])
        self.assertTrue(gone["redirected_to_other_site"])
        text = s.render_check(rows)
        self.assertIn("why it's on the list: AI teammates in group chat", text)
        self.assertIn("REDIRECTS TO ANOTHER SITE: https://acquirer.example/welcome", text)


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

    def test_watch_list_table(self):
        import tempfile
        cfg_text = ("competitors:\n"
                    "  - name: Acme\n    group: direct\n    added: 2026-10-01\n    reason: same ICP\n    pages:\n"
                    "      - { label: home, url: https://acme.example }\n"
                    "      - { label: pricing, url: https://acme.example/pricing }\n"
                    "  - name: Beta\n    fit: AI for sales teams\n    pages:\n      - { label: home, url: https://b.example }\n"
                    "  - name: New\n    pages:\n      - { label: home, url: https://n.example }\n")
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "targets.yml"
            cfg.write_text(cfg_text)
            targets = s.load_targets(cfg)
        status = {"targets": [{"competitor": "Acme", "label": "home", "ok": True},
                              {"competitor": "Acme", "label": "pricing", "url": "u", "ok": False, "error": "403"},
                              {"competitor": "Beta", "label": "home", "ok": True}]}
        text = s.render_report([], status, self.NOW, targets=targets)
        self.assertIn("## Watch list", text)
        self.assertIn("| Acme | direct | 2026-10-01 | same ICP | 1 OK, **1 broken** |", text)
        self.assertIn("| Beta | other |  | AI for sales teams | 1 OK |", text)
        self.assertIn("| New | other |  |  | not scanned yet |", text)
        self.assertNotIn("## Watch list\n", s.render_report([], {}, self.NOW))       # no targets, no table
        self.assertIn("not scanned yet", s.render_report([], {}, self.NOW, targets=targets))

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

    def test_top_moves_ranked_by_importance(self):
        changes = [{"type": "change", "competitor": "Zed", "label": "home", "url": "https://z", "date": self.NOW,
                    "tags": ["messaging"], "summary": "New headline"},
                   {"type": "change", "competitor": "Acme", "label": "pricing", "url": "https://p", "date": self.NOW,
                    "tags": ["product", "pricing"], "summary": "Pro: $25 → $29/mo"}]
        intel = [{"competitor": "Bee", "type": "social", "title": "A post", "url": "https://s", "found": self.NOW},
                 {"competitor": "Cee", "type": "funding", "title": "Series B", "url": "https://f", "found": self.NOW},
                 {"competitor": "Dee", "type": "launch", "title": "Dee Agents", "url": "https://l", "found": self.NOW}]
        text = s.render_report(changes, {}, self.NOW, days=1, intel=intel)
        top = text[text.index("## Top moves"):text.index("## Launches")]
        order = [top.index(x) for x in ("**Acme** `pricing`", "**Dee** `launch`", "**Cee** `funding`",
                                         "**Zed** `messaging`", "**Bee** `social`")]
        self.assertEqual(order, sorted(order))
        self.assertLess(text.index("## Top moves"), text.index("## Launches"))
        self.assertEqual(len(s.top_moves(changes * 4, intel)), s.MAX_TOP_MOVES)
        self.assertNotIn("Top moves", s.render_report([], {}, self.NOW))

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


class TestCandidates(unittest.TestCase):
    def test_counts_days_skips_watched_and_ranks(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            wd = Path(d)
            cfg = wd / "targets.yml"
            cfg.write_text("competitors:\n  - name: Acme\n    enabled: false\n    pages:\n"
                           "      - { label: home, url: https://www.acme.com }\n")
            day = lambda n: f"2026-11-0{n}T04:00:00+00:00"
            strong = {"name": "Strongco", "url": "https://strong.co", "reason": "same ICP", "confidence": "medium"}
            self.assertEqual(s.add_candidates(wd, [strong, {"name": "Weak"}, {"name": "Acme Inc", "url": "https://acme.com/x"}], day(1)), 3)
            self.assertEqual(s.add_candidates(wd, [strong], day(1)), 0)      # same day: no extra sighting
            s.add_candidates(wd, [{"name": "StrongCo AI", "url": "https://www.strong.co/"}], day(2))  # same host
            s.add_candidates(wd, [{"name": "strongco"}], day(3))
            with self.assertRaises(ValueError):
                s.add_candidates(wd, [{"url": "https://x.com"}], day(3))
            rows = s.list_candidates(wd, cfg)
            self.assertEqual([r["name"] for r in rows], ["Strongco", "Weak"])  # Acme is watched (paused)
            self.assertEqual((rows[0]["seen"], rows[0]["first_seen"], rows[0]["last_seen"]), (3, "2026-11-01", "2026-11-03"))
            text = s.render_candidates(rows)
            self.assertIn("[Strongco](https://www.strong.co/)", text)
            self.assertEqual(text.count("consider adding"), 1)
            self.assertIn("No candidates", s.render_candidates([]))
            self.assertEqual(s.list_candidates(wd / "none", wd / "none.yml"), [])

    def test_report_lists_candidates_to_consider(self):
        now = "2026-11-05T12:00:00+00:00"
        rows = [{"name": "Strongco", "url": "https://strong.co", "seen": 3, "last_seen": "2026-11-05",
                 "reason": "same ICP | SMB"}, {"name": "Weak", "seen": 1}]
        text = s.render_report([], {}, now, days=7, candidates=rows)
        self.assertIn("## Consider adding", text)
        self.assertIn("**[Strongco](https://strong.co)** (3 days, last 2026-11-05): same ICP \\| SMB", text)
        self.assertNotIn("Weak", text)
        for empty in (None, [], rows[1:]):
            self.assertNotIn("Consider adding", s.render_report([], {}, now, days=7, candidates=empty))


class TestRepo(unittest.TestCase):
    def test_plugin_version_matches_version_file(self):
        import json
        root = Path(__file__).resolve().parents[1]
        plugin = json.loads((root / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(plugin["version"], (root / "VERSION").read_text().strip())


if __name__ == "__main__":
    unittest.main()
