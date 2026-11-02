#!/usr/bin/env python3
"""Stakeout: watch competitor pages, diff them daily, log what changed.

Run:  python stakeout.py               (scan every target in targets.yml)
      python stakeout.py --only Acme   (scan one target by name)

Outputs:
  snapshots/<slug>.txt      latest readable text of each page
  docs/data/changes.json    feed of change events (newest first)
  docs/data/status.json     last run + per-target health
"""
import argparse, datetime as dt, difflib, json, os, re, sys, urllib.request
from html.parser import HTMLParser
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
SNAP_DIR = ROOT / "snapshots"
DATA_DIR = ROOT / "docs" / "data"
MAX_EVENTS = 1000
MAX_LINES_STORED = 40  # per side (added / removed) in the feed

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 Stakeout/0.1")

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

    def handle_starttag(self, tag, attrs):
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
    for raw in "".join(p.parts).split("\n"):
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
        "model": os.environ.get("STAKEOUT_MODEL", "claude-haiku-4-5"),
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
            label = page.get("label", "page")
            targets.append({
                "competitor": comp["name"],
                "label": label,
                "url": page["url"],
                "slug": slugify(f"{comp['name']}-{label}"),
                "ignore": DEFAULT_IGNORE + cfg.get("ignore", []) + comp.get("ignore", []) + page.get("ignore", []),
                "min_lines": page.get("min_lines", cfg.get("min_lines", 1)),
            })
    return targets


# ---------------------------------------------------------------- main
def scan(targets, now):
    changes = load_json(DATA_DIR / "changes.json", [])
    status = load_json(DATA_DIR / "status.json", {})
    prev_targets = {t["slug"]: t for t in status.get("targets", [])}
    new_events, health = [], []

    for t in targets:
        print(f"→ {t['competitor']} / {t['label']}  {t['url']}")
        h = dict(prev_targets.get(t["slug"], {}))
        h.update({k: t[k] for k in ("slug", "competitor", "label", "url")})
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

        snap = SNAP_DIR / f"{t['slug']}.txt"
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
            ev.update(id=f"{now[:10]}-{t['slug']}", date=now, competitor=t["competitor"],
                      label=t["label"], url=t["url"], slug=t["slug"])
            new_events.append(ev)
            h["last_changed"] = now
            print(f"  ✓ {ev['type']}: {ev['summary']}")
        else:
            print("  · no change")
        SNAP_DIR.mkdir(exist_ok=True)
        snap.write_text("\n".join(lines) + "\n")
        health.append(h)

    # Re-running on the same day replaces that day's event for the page.
    ids = {e["id"] for e in new_events}
    changes = (new_events + [e for e in changes if e["id"] not in ids])[:MAX_EVENTS]
    save_json(DATA_DIR / "changes.json", changes)
    save_json(DATA_DIR / "status.json", {"last_run": now, "targets": health})
    real = [e for e in new_events if e["type"] == "change"]
    print(f"\nDone. {len(real)} change(s), {len(new_events) - len(real)} baseline(s), "
          f"{sum(not h['ok'] for h in health)} error(s).")
    return real


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "targets.yml"))
    ap.add_argument("--only", help="scan only this competitor name")
    args = ap.parse_args()
    targets = load_targets(args.config)
    if args.only:
        targets = [t for t in targets if t["competitor"].lower() == args.only.lower()]
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    real = scan(targets, now)
    if gh_out := os.environ.get("GITHUB_OUTPUT"):
        with open(gh_out, "a") as f:
            f.write(f"changes={len(real)}\n")


if __name__ == "__main__":
    main()
