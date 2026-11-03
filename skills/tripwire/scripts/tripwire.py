#!/usr/bin/env python3
"""Tripwire: watch competitor pages, diff them, report what changed.

Run:  python tripwire.py scan                  (scan every page in watch/targets.yml)
      python tripwire.py scan --only Acme      (scan one competitor)
      python tripwire.py report --days 7       (Markdown digest of the last 7 days)
      python tripwire.py init                  (create watch/targets.yml from the example)

Everything lives next to the config file (default watch/targets.yml):
  snapshots/<slug>.txt      latest readable text of each page
  data/changes.json         feed of change events (newest first)
  data/status.json          last run + per-page health
  data/intel.json           launches, news, social posts and watch-list changes found on the web
  reports/<date>.md         Markdown report of each scan (reports/latest.md = newest)

      python tripwire.py intel < items.json    (log web findings; duplicates are skipped)
"""
import argparse, datetime as dt, difflib, json, os, re, sys, urllib.request
from html.parser import HTMLParser
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path("watch") / "targets.yml"
MAX_EVENTS = 1000
MAX_INTEL = 2000
INTEL_TYPES = ["competitor_added", "competitor_dropped", "launch", "pricing", "funding",
               "partnership", "hiring", "social", "news"]
WATCHLIST_TYPES = {"competitor_added", "competitor_dropped"}
MAX_LINES_STORED = 40  # per side (added / removed) in the feed

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 Tripwire/0.2")

# Lines that change on every load and mean nothing.
DEFAULT_IGNORE = [
    r"^©.*$", r"^copyright\b.*$", r"\b\d{1,2}:\d{2}(:\d{2})?\s?(am|pm)?\b",
    r"^\d+\s+(seconds?|minutes?|hours?)\s+ago$", r"^loading\.*$",
]

TAG_RULES = [
    ("pricing", r"[$€£¥]\s?\d|/\s?(mo|month|yr|year|seat|user)\b|per (month|year|seat|user)|\bfree trial\b|\bpricing\b|\benterprise\b|\bplan\b"),
    ("hiring", r"\b(hiring|careers?|job|open roles?|engineer|designer|manager|head of|remote)\b"),
    ("product", r"\b(new|introducing|launch(ed|ing)?|now available|beta|release[ds]?|changelog|v\d+(\.\d+)*|integration|feature)\b"),
]


# ---------------------------------------------------------------- extraction
class TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "head"}
    BLOCK = {"p", "div", "section", "article", "header", "footer", "li", "ul", "ol",
             "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "td", "th", "table",
             "nav", "main", "aside", "button", "dt", "dd", "blockquote", "summary", "figcaption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip_depth, self.title = [], 0, ""
        self._in_title = False
        self.meta = []

    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            a = dict(attrs)
            key = (a.get("name") or a.get("property") or "").lower()
            if key in ("description", "og:title", "og:description", "twitter:description") and a.get("content"):
                self.meta.append(a["content"])
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP:
            self.skip_depth += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if not self.skip_depth:
            self.parts.append(data)


def extract_lines(html, ignore_patterns):
    p = TextExtractor()
    p.feed(html)
    ignore = [re.compile(x, re.I) for x in ignore_patterns]
    lines, seen_prev = [], None
    body = "".join(p.parts)
    if not body.strip():
        # JS-only page: fall back to the meta title/description tags.
        body = "\n".join(dict.fromkeys(p.meta))
    for raw in body.split("\n"):
        line = re.sub(r"\s+", " ", raw).strip()
        for rx in ignore:
            line = rx.sub("", line).strip()
        if len(line) < 2 or line == seen_prev:
            continue
        lines.append(line)
        seen_prev = line
    return p.title.strip(), lines


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        charset = r.headers.get_content_charset() or "utf-8"
        return r.read().decode(charset, errors="replace")


# ---------------------------------------------------------------- diffing
def diff_lines(old, new):
    added, removed = [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if op in ("replace", "delete"):
            removed += old[i1:i2]
        if op in ("replace", "insert"):
            added += new[j1:j2]
    # A line that only moved is not a change.
    a, r = set(added), set(removed)
    return [x for x in added if x not in r], [x for x in removed if x not in a]


def tag_change(added, removed):
    text = "\n".join(added + removed)
    tags = [name for name, rx in TAG_RULES if re.search(rx, text, re.I)]
    return tags or ["messaging"]


def heuristic_summary(added, removed):
    bits = []
    if added:
        bits.append(f"+{len(added)} line{'s' * (len(added) != 1)}")
    if removed:
        bits.append(f"−{len(removed)} line{'s' * (len(removed) != 1)}")
    lead = (added or removed)[0]
    lead = lead if len(lead) <= 120 else lead[:117] + "…"
    verb = "New" if added else "Removed"
    return f"{', '.join(bits)}. {verb}: “{lead}”"


def ai_summary(name, url, added, removed):
    """One-sentence GTM read of the change. Only runs if ANTHROPIC_API_KEY is set."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    prompt = (
        f"You track competitors for a startup GTM team. The page {url} ({name}) changed.\n"
        f"ADDED lines:\n" + "\n".join(added[:60]) + "\n\nREMOVED lines:\n" + "\n".join(removed[:60]) +
        "\n\nIn ONE short sentence (max 30 words), say what changed and why a GTM person might care. "
        "If it's trivial noise, start with 'Minor:'. No preamble."
    )
    body = json.dumps({
        "model": os.environ.get("TRIPWIRE_MODEL", "claude-haiku-4-5"),
        "max_tokens": 120,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)["content"][0]["text"].strip()
    except Exception as e:  # never let the summary break the scan
        print(f"  ! AI summary failed: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------- io helpers
def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "page"


def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def load_targets(path):
    cfg = yaml.safe_load(Path(path).read_text()) or {}
    targets = []
    for comp in cfg.get("competitors", []):
        for page in comp.get("pages", []):
            if page.get("enabled", True) is False or comp.get("enabled", True) is False:
                continue
            label = page.get("label", "page")
            targets.append({
                "competitor": comp["name"],
                "group": comp.get("group", "other"),
                "label": label,
                "url": page["url"],
                "slug": slugify(f"{comp['name']}-{label}"),
                "ignore": DEFAULT_IGNORE + cfg.get("ignore", []) + comp.get("ignore", []) + page.get("ignore", []),
                "min_lines": page.get("min_lines", cfg.get("min_lines", 1)),
            })
    return targets


# ---------------------------------------------------------------- main
def scan(targets, now, workdir):
    snap_dir, data_dir = workdir / "snapshots", workdir / "data"
    changes = load_json(data_dir / "changes.json", [])
    status = load_json(data_dir / "status.json", {})
    prev_targets = {t["slug"]: t for t in status.get("targets", [])}
    new_events, health = [], []

    for t in targets:
        print(f"→ {t['competitor']} / {t['label']}  {t['url']}")
        h = dict(prev_targets.get(t["slug"], {}))
        h.update({k: t[k] for k in ("slug", "competitor", "group", "label", "url")})
        h["last_checked"] = now
        try:
            title, lines = extract_lines(fetch(t["url"]), t["ignore"])
        except Exception as e:
            h.update(ok=False, error=f"{type(e).__name__}: {e}"[:200])
            print(f"  ! {h['error']}")
            health.append(h)
            continue
        if not lines:
            h.update(ok=False, error="Page returned no readable text (JS-only page?)")
            health.append(h)
            continue
        h.update(ok=True, error=None, title=title, lines=len(lines))

        snap = snap_dir / f"{t['slug']}.txt"
        if not snap.exists():
            ev = {"type": "baseline", "summary": f"Started watching. {len(lines)} lines captured.",
                  "tags": ["baseline"], "added": [], "removed": []}
        else:
            added, removed = diff_lines(snap.read_text().splitlines(), lines)
            if len(added) + len(removed) < t["min_lines"]:
                ev = None
            else:
                ev = {"type": "change", "tags": tag_change(added, removed),
                      "summary": ai_summary(t["competitor"], t["url"], added, removed) or heuristic_summary(added, removed),
                      "added": added[:MAX_LINES_STORED], "removed": removed[:MAX_LINES_STORED],
                      "added_total": len(added), "removed_total": len(removed)}
        if ev:
            ev.update(id=f"{now[:10]}-{t['slug']}", date=now, competitor=t["competitor"], group=t["group"],
                      label=t["label"], url=t["url"], slug=t["slug"])
            new_events.append(ev)
            h["last_changed"] = now
            print(f"  ✓ {ev['type']}: {ev['summary']}")
        else:
            print("  · no change")
        snap_dir.mkdir(parents=True, exist_ok=True)
        snap.write_text("\n".join(lines) + "\n")
        health.append(h)

    # Re-running on the same day replaces that day's event for the page.
    ids = {e["id"] for e in new_events}
    changes = (new_events + [e for e in changes if e["id"] not in ids])[:MAX_EVENTS]
    save_json(data_dir / "changes.json", changes)
    save_json(data_dir / "status.json", {"last_run": now, "targets": health})
    write_report(workdir, render_report(changes, {"last_run": now, "targets": health}, now, days=1,
                                        intel=load_json(data_dir / "intel.json", [])),
                 f"{now[:10]}.md")
    real = [e for e in new_events if e["type"] == "change"]
    print(f"\nDone. {len(real)} change(s), {len(new_events) - len(real)} baseline(s), "
          f"{sum(not h['ok'] for h in health)} error(s).")
    return real


# ---------------------------------------------------------------- intel
def _intel_key(item):
    url = (item.get("url") or "").strip().lower().rstrip("/")
    if url and item["type"] not in WATCHLIST_TYPES:
        return url
    return f"{item['type']}|{item['competitor'].lower()}|{item.get('title', '').strip().lower()}"


def add_intel(workdir, items, now):
    """Append web findings to data/intel.json, newest first. Returns (added, skipped) counts.

    Each item: {competitor, type, title, url, summary?, source?, date?}. `date` is when it was
    published (defaults to today); `found` is set to `now` and decides which report shows it.
    """
    path = workdir / "data" / "intel.json"
    existing = load_json(path, [])
    seen = {_intel_key(e) for e in existing}
    fresh, skipped = [], 0
    for raw in items:
        item = {k: (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}
        if not item.get("competitor") or not item.get("title"):
            raise ValueError(f"intel item needs competitor and title: {raw}")
        if item.get("type") not in INTEL_TYPES:
            raise ValueError(f"intel type must be one of {INTEL_TYPES}: {raw}")
        if item["type"] not in WATCHLIST_TYPES and not item.get("url"):
            raise ValueError(f"intel item needs a source url: {raw}")
        key = _intel_key(item)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        item.setdefault("date", now[:10])
        item["found"] = now
        fresh.append(item)
    save_json(path, (fresh + existing)[:MAX_INTEL])
    return len(fresh), skipped


# ---------------------------------------------------------------- reports
MAX_REPORT_LINES = 8  # per side, per change


def _quote(line):
    line = line.replace("|", "\\|")
    return line if len(line) <= 160 else line[:157] + "…"


def render_report(changes, status, now, days=1, intel=None):
    """Markdown report of what was found in the `days` days up to `now`, plus scan health."""
    end = dt.datetime.fromisoformat(now)
    start = end - dt.timedelta(days=days)
    within = lambda d: start < dt.datetime.fromisoformat(d) <= end
    recent = [e for e in changes if within(e["date"])]
    found = [i for i in (intel or []) if within(i["found"])]
    watchlist = [i for i in found if i["type"] in WATCHLIST_TYPES]
    news = [i for i in found if i["type"] not in WATCHLIST_TYPES]
    real = [e for e in recent if e["type"] == "change"]
    baselines = [e for e in recent if e["type"] == "baseline"]
    targets = status.get("targets", [])
    broken = [t for t in targets if not t.get("ok")]

    title = f"Tripwire report: {now[:10]}" if days == 1 else \
        f"Tripwire digest: {start.date().isoformat()} to {now[:10]}"
    out = [f"# {title}", "",
           f"{len(targets)} pages watched · **{len(real)} page change{'s' * (len(real) != 1)}** · "
           f"**{len(news)} launch / news / social item{'s' * (len(news) != 1)}** · "
           f"{len(targets) - len(broken)} OK · {len(broken)} not readable", ""]

    if watchlist:
        out += ["## Watch list changes", ""]
        for i in watchlist:
            verb = "New competitor" if i["type"] == "competitor_added" else "Dropped"
            src = f" ([source]({i['url']}))" if i.get("url") else ""
            out.append(f"- **{verb}: {i['competitor']}**: {_quote(i.get('summary') or i['title'])}{src}")
        out.append("")

    if news:
        out += ["## Launches, news & social", ""]
        by_comp = {}
        for i in news:
            by_comp.setdefault(i["competitor"], []).append(i)
        for comp in sorted(by_comp, key=str.lower):
            out += [f"### {comp}", ""]
            for i in sorted(by_comp[comp], key=lambda i: INTEL_TYPES.index(i["type"])):
                src = f", {i['source']}" if i.get("source") else ""
                line = f"- `{i['type']}` [{_quote(i['title'])}]({i['url']}) ({i['date']}{src})"
                if i.get("summary"):
                    line += f": {_quote(i['summary'])}"
                out.append(line)
            out.append("")

    out += ["## Website changes", ""]
    if not real:
        out += ["No changes." + (" New pages get a baseline first; changes show from the next scan."
                                 if baselines else ""), ""]
    by_comp = {}
    for e in real:
        by_comp.setdefault(e["competitor"], []).append(e)
    # Pricing moves first, then the rest, each group by competitor name.
    order = sorted(by_comp, key=lambda c: (not any("pricing" in e["tags"] for e in by_comp[c]), c.lower()))
    for comp in order:
        out += [f"### {comp}", ""]
        for e in by_comp[comp]:
            tags = " ".join(f"`{t}`" for t in e["tags"])
            day = "" if days == 1 else f" ({e['date'][:10]})"
            out += [f"**[{e['label']}]({e['url']})**{day} {tags}", "", e["summary"], ""]
            for sign, key in (("+", "added"), ("-", "removed")):
                lines = e.get(key, [])
                if not lines:
                    continue
                out.append("```diff")
                out += [f"{sign} {_quote(l)}" for l in lines[:MAX_REPORT_LINES]]
                more = e.get(f"{key}_total", len(lines)) - min(len(lines), MAX_REPORT_LINES)
                if more > 0:
                    out.append(f"{sign} … {more} more")
                out += ["```", ""]

    if broken:
        out += ["## Not readable", "", "| Competitor | Page | Problem |", "|---|---|---|"]
        out += [f"| {t['competitor']} | [{t['label']}]({t['url']}) | {_quote(t.get('error') or 'unknown')} |"
                for t in broken]
        out.append("")
    if baselines:
        out += ["## Started watching", ""]
        out += [f"- {e['competitor']} · [{e['label']}]({e['url']})" for e in baselines]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def write_report(workdir, text, name):
    rdir = workdir / "reports"
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / name).write_text(text)
    (rdir / "latest.md").write_text(text)
    return rdir / name


def add_competitor(config, name, url, pricing=None, group=None, reason=None):
    """Append a competitor to the watch list text, keeping comments. Returns False if already present."""
    config = Path(config)
    text = config.read_text() if config.exists() else ""
    cfg = yaml.safe_load(text) or {}
    comps = cfg.get("competitors") or []
    if any(str(c.get("name", "")).lower() == name.lower() for c in comps):
        return False
    q = lambda v: json.dumps(v, ensure_ascii=False)  # JSON strings are valid YAML
    block = [f"  - name: {q(name)}"]
    if group:
        block.append(f"    group: {q(group)}")
    if reason:
        block.append(f"    reason: {q(reason)}")
    block.append(f"    added: {dt.date.today().isoformat()}")
    block.append("    pages:")
    block.append(f"      - {{ label: home, url: {q(url)} }}")
    if pricing:
        block.append(f"      - {{ label: pricing, url: {q(pricing)} }}")
    if "competitors" not in cfg or not comps and re.search(r"^competitors:\s*\[\s*\]", text, re.M):
        text = re.sub(r"^competitors:\s*\[\s*\]\s*$", "", text, flags=re.M)
        text = text.rstrip("\n") + ("\n\n" if text.strip() else "") + "competitors:\n"
    elif not text.endswith("\n"):
        text += "\n"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(text + "\n".join(block) + "\n")
    return True


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description="Watch competitor pages and report what changed.")
    ap.add_argument("command", nargs="?", default="scan", choices=["scan", "report", "init", "intel", "add"])
    ap.add_argument("--config", default=os.environ.get("TRIPWIRE_CONFIG", str(DEFAULT_CONFIG)),
                    help="watch list (default: watch/targets.yml); data is stored next to it")
    ap.add_argument("name", nargs="?", help="add: competitor name")
    ap.add_argument("--url", help="add: home page URL")
    ap.add_argument("--pricing", help="add: pricing page URL")
    ap.add_argument("--group", help="add: label such as direct / platform / indirect")
    ap.add_argument("--reason", help="add: why this competitor is on the list")
    ap.add_argument("--only", help="scan: only this competitor name")
    ap.add_argument("--days", type=int, default=7, help="report: how many days to cover (default 7)")
    ap.add_argument("--out", help="report: file name inside reports/ (default: printed only)")
    ap.add_argument("--file", help="intel: JSON file with a list of items (default: stdin)")
    args = ap.parse_args(argv)
    config = Path(args.config)
    workdir = config.parent
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()

    if args.command == "init":
        if config.exists():
            print(f"{config} already exists; edit it to change what you watch.")
            return
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text((SKILL_DIR / "targets.example.yml").read_text())
        print(f"Created {config}. Add your competitors, then run: python {Path(__file__).name} scan")
        return

    if args.command == "add":
        if not args.name or not args.url:
            ap.error("add needs a name and --url")
        if add_competitor(config, args.name, args.url, args.pricing, args.group, args.reason):
            print(f"Added {args.name} to {config}.")
        else:
            print(f"{args.name} is already in {config}; nothing changed.")
        return

    if args.command == "intel":
        raw = Path(args.file).read_text() if args.file else sys.stdin.read()
        items = json.loads(raw)
        added, skipped = add_intel(workdir, items if isinstance(items, list) else [items], now)
        print(f"Logged {added} new item(s), skipped {skipped} already known.")
        return

    if args.command == "report":
        text = render_report(load_json(workdir / "data" / "changes.json", []),
                             load_json(workdir / "data" / "status.json", {}), now, days=args.days,
                             intel=load_json(workdir / "data" / "intel.json", []))
        if args.out:
            print(f"Wrote {write_report(workdir, text, args.out)}")
        else:
            print(text)
        return

    targets = load_targets(config)
    if args.only:
        targets = [t for t in targets if t["competitor"].lower() == args.only.lower()]
    real = scan(targets, now, workdir)
    print(f"Report: {workdir / 'reports' / 'latest.md'}")
    if gh_out := os.environ.get("GITHUB_OUTPUT"):
        with open(gh_out, "a") as f:
            f.write(f"changes={len(real)}\n")


if __name__ == "__main__":
    main()
