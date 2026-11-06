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
  data/candidates.json      possible competitors seen but not added, with how often they show up
  reports/<date>.md         Markdown report of each scan (reports/latest.md = newest)

      python tripwire.py intel < items.json    (log web findings; duplicates are skipped)
      python tripwire.py check                 (what each competitor's own homepage says it is)
      python tripwire.py candidates [--file c.json]  (possible competitors not added yet, by sightings)
      python tripwire.py candidates --dismiss <name> [--reason R]  (reject one so it stops showing)
"""
import argparse, datetime as dt, difflib, json, os, re, sys, time, urllib.error, urllib.request
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
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 Tripwire")
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
RETRY_DELAY = 3  # seconds before the single retry of a transient failure

# Lines that change on every load and mean nothing.
DEFAULT_IGNORE = [
    r"^©.*$", r"^copyright\b.*$", r"\b\d{1,2}:\d{2}(:\d{2})?\s?(am|pm)?\b",
    r"^\d+\s+(seconds?|minutes?|hours?)\s+ago$", r"^loading\.*$",
    r"^.*\b(trace|request|correlation|session)[ -]?id\b.*$",  # "This is the Trace Id: 3f2a…"
    r"\b[0-9a-f]{32,}\b",                                      # per-request hashes
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
        self._in_title = self._title_done = False
        self.meta = []
        self.svg_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "svg":
            self.svg_depth += 1
        if tag == "meta":
            a = dict(attrs)
            key = (a.get("name") or a.get("property") or "").lower()
            if key in ("description", "og:title", "og:description", "twitter:description") and a.get("content"):
                self.meta.append(a["content"])
        if tag == "title" and not self._title_done and not self._in_svg():
            self._in_title = True
        if tag in self.SKIP:
            self.skip_depth += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def _in_svg(self):
        # <title> inside an inline <svg> icon is a tooltip, not the page title.
        return self.svg_depth > 0

    def handle_endtag(self, tag):
        if tag == "svg" and self.svg_depth:
            self.svg_depth -= 1
        if tag == "title" and self._in_title:
            self._in_title, self._title_done = False, True
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
    return re.sub(r"\s+", " ", p.title).strip(), lines


# Bot-protection and error pages that come back as 200 / 403 with HTML instead of the real page.
BLOCK_PAGE = re.compile(
    r"request has been blocked|access denied|attention required|just a moment|verify you are human"
    r"|are you a robot|enable javascript and cookies|captcha|pardon our interruption", re.I)


def blocked_reason(title, lines):
    """Return why this looks like a bot-protection page rather than the real one, else None."""
    head = " ".join([title] + lines[:5])
    m = BLOCK_PAGE.search(head)
    return f"Bot protection page instead of content (\"{m.group(0)}\")" if m else None


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Follow 308 Permanent Redirect too (urllib only learned it in Python 3.11)."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, 307 if code == 308 else code, msg, headers, newurl)

    http_error_308 = urllib.request.HTTPRedirectHandler.http_error_302


_OPENER = urllib.request.build_opener(_Redirects)


def _transient(err):
    if isinstance(err, urllib.error.HTTPError):
        return err.code == 429 or err.code >= 500
    return isinstance(err, (urllib.error.URLError, TimeoutError, ConnectionError))


def fetch(url, timeout=30):
    """GET a page as text. Retries once on timeouts, connection errors, 429 and 5xx."""
    return fetch_page(url, timeout)[0]


def fetch_page(url, timeout=30):
    """Like fetch, but returns (text, final URL after redirects)."""
    for attempt in (1, 2):
        try:
            with _OPENER.open(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as r:
                charset = r.headers.get_content_charset() or "utf-8"
                return r.read().decode(charset, errors="replace"), r.geturl()
        except Exception as e:
            if attempt == 2 or not _transient(e):
                raise
            time.sleep(RETRY_DELAY)


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


PRICE_RX = re.compile(r"[$€£¥]\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|GBP)\b")


def price_changes(added, removed):
    """Pair removed and added lines that are identical except for their prices.

    "$25/mo per seat" → "$29/mo per seat" becomes {"old": "$25/mo per seat", "new": "$29/mo per seat",
    "from": ["$25"], "to": ["$29"]}. A line that is only a price ("$45") is paired only when exactly
    one such line was removed and one added, so unrelated prices are never matched up."""
    def shape(line):
        return PRICE_RX.sub("{price}", line).strip()

    pool = {}
    for line in removed:
        if PRICE_RX.search(line):
            pool.setdefault(shape(line), []).append(line)
    added_by_shape = {}
    for line in added:
        if PRICE_RX.search(line):
            added_by_shape.setdefault(shape(line), []).append(line)

    out = []
    for key, news in added_by_shape.items():
        olds = pool.get(key, [])
        if not re.search(r"[A-Za-z]", PRICE_RX.sub("", key.replace("{price}", ""))) and \
                (len(olds) != 1 or len(news) != 1):
            continue  # bare prices: only an unambiguous one-for-one swap counts
        for old, new in zip(olds, news):
            before, after = PRICE_RX.findall(old), PRICE_RX.findall(new)
            if before != after:
                out.append({"old": old, "new": new, "from": before, "to": after})
    return out


def price_summary(changes):
    first = changes[0]
    moves = ", ".join(f"{a} → {b}" for a, b in zip(first["from"], first["to"]) if a != b)
    more = f" (+{len(changes) - 1} more price change{'s' * (len(changes) > 2)})" if len(changes) > 1 else ""
    line = first["new"] if len(first["new"]) <= 80 else first["new"][:77] + "…"
    return f"Price change: {moves} in “{line}”{more}"


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
                "added": str(comp["added"]) if comp.get("added") else None,
                "reason": comp.get("reason") or comp.get("fit"),
            })
    return targets


# ---------------------------------------------------------------- main
def scan(targets, now, workdir, only=None):
    """Scan `targets` (the whole watch list). With `only`, fetch just that competitor and keep the
    last known health of every other page, so a partial scan doesn't shrink the report."""
    snap_dir, data_dir = workdir / "snapshots", workdir / "data"
    changes = load_json(data_dir / "changes.json", [])
    status = load_json(data_dir / "status.json", {})
    prev_targets = {t["slug"]: t for t in status.get("targets", [])}
    new_events, health = [], []

    for t in targets:
        if only and t["competitor"].lower() != only.lower():
            if t["slug"] in prev_targets:
                health.append(prev_targets[t["slug"]])
            continue
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
        if reason := blocked_reason(title, lines):
            # Never diff a block page against the real snapshot: it would look like a rewrite.
            h.update(ok=False, error=reason)
            print(f"  ! {reason}")
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
                prices = price_changes(added, removed)
                tags = tag_change(added, removed)
                if prices and "pricing" not in tags:
                    tags.insert(0, "pricing")
                ev = {"type": "change", "tags": tags,
                      "summary": ai_summary(t["competitor"], t["url"], added, removed)
                                 or (price_summary(prices) if prices else heuristic_summary(added, removed)),
                      "added": added[:MAX_LINES_STORED], "removed": removed[:MAX_LINES_STORED],
                      "added_total": len(added), "removed_total": len(removed)}
                if prices:
                    ev["price_changes"] = prices
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
                                        intel=load_json(data_dir / "intel.json", []), targets=targets),
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


# ---------------------------------------------------------------- candidates
PROMOTE_AFTER = 3  # days a candidate must show up before it's suggested for the watch list


def _watched(config):
    """Lower-case names and hosts of every competitor in the watch list, paused ones included."""
    try:
        cfg = yaml.safe_load(Path(config).read_text()) or {}
    except FileNotFoundError:
        return set(), set()
    comps = cfg.get("competitors") or []
    names = {str(c.get("name", "")).strip().lower() for c in comps}
    hosts = {_host(p["url"]) for c in comps for p in c.get("pages") or [] if p.get("url")}
    return names, hosts - {""}


def _same_candidate(a, b):
    if a["name"].lower() == b["name"].lower():
        return True
    return bool(a.get("url") and b.get("url") and _host(a["url"]) == _host(b["url"]))


def add_candidates(workdir, items, now):
    """Record possible competitors seen during discovery but not added, in data/candidates.json.

    Each item: {name, url?, reason?, confidence?, source?}. A candidate counts at most one sighting
    per day, so repeated runs on one day don't inflate it. Returns the number of new candidates."""
    path = workdir / "data" / "candidates.json"
    known = load_json(path, [])
    today, new = now[:10], 0
    for raw in items:
        item = {k: (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}
        if not item.get("name"):
            raise ValueError(f"candidate needs a name: {raw}")
        match = next((c for c in known if _same_candidate(c, item)), None)
        if match is None:
            match = {"name": item["name"], "first_seen": today, "last_seen": today, "seen": 1}
            known.append(match)
            new += 1
        elif match.get("last_seen") != today:
            match["seen"] = int(match.get("seen") or 0) + 1
            match["last_seen"] = today
        for key in ("url", "reason", "confidence", "source"):
            if item.get(key):
                match[key] = item[key]
    save_json(path, known)
    return new


def dismiss_candidate(workdir, name, now, reason=None):
    """Mark a candidate as rejected so it stops showing; later sightings still count but stay hidden.

    Matched by name or domain (a URL works too). An unknown name is recorded as dismissed up front.
    Returns the candidate's stored name."""
    path = workdir / "data" / "candidates.json"
    known = load_json(path, [])
    name = name.strip()
    probe = {"name": name, "url": name if "://" in name else None}
    match = next((c for c in known if isinstance(c, dict) and c.get("name") and _same_candidate(c, probe)), None)
    if match is None:
        match = {"name": name, "first_seen": now[:10], "last_seen": now[:10], "seen": 0}
        known.append(match)
    match["dismissed"] = now[:10]
    if reason:
        match["dismiss_reason"] = reason.strip()
    save_json(path, known)
    return match["name"]


def list_candidates(workdir, config):
    """Candidates not yet on the watch list or dismissed, most often seen first."""
    names, hosts = _watched(config)
    rows = [c for c in load_json(workdir / "data" / "candidates.json", [])
            if isinstance(c, dict) and c.get("name") and not c.get("dismissed")
            and c["name"].strip().lower() not in names
            and not (c.get("url") and _host(c["url"]) in hosts)]
    rows.sort(key=lambda c: str(c.get("last_seen") or ""), reverse=True)
    return sorted(rows, key=lambda c: -int(c.get("seen") or 0))


def render_candidates(rows):
    if not rows:
        return "No candidates waiting. Log the ones you don't add with `candidates --file`.\n"
    out = ["| Candidate | Seen (days) | First / last seen | Confidence | Why | |",
           "|---|---|---|---|---|---|"]
    for c in rows:
        name = f"[{c['name']}]({c['url']})" if c.get("url") else c["name"]
        hint = "**consider adding**" if int(c.get("seen") or 0) >= PROMOTE_AFTER else ""
        out.append(f"| {_quote(name)} | {c.get('seen', 1)} | {c.get('first_seen', '?')} / "
                   f"{c.get('last_seen', '?')} | {c.get('confidence') or ''} | "
                   f"{_quote(c.get('reason') or '')} | {hint} |")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- reports
MAX_REPORT_LINES = 8  # per side, per change


def _quote(line):
    line = line.replace("|", "\\|")
    return line if len(line) <= 160 else line[:157] + "…"


def _ts(value):
    """Parse an ISO date or datetime; date-only and naive values count as UTC. None if unparseable."""
    try:
        d = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


MAX_TOP_MOVES = 5
# Lower is more important. Page changes rank by their tags, intel by its type.
MOVE_RANK = {"pricing": 0, "launch": 1, "product": 1, "funding": 2, "competitor_added": 3,
             "competitor_dropped": 3, "partnership": 3, "hiring": 4, "messaging": 5, "news": 5,
             "social": 6}


def top_moves(real, found, limit=MAX_TOP_MOVES):
    """The most important page changes and intel items, one Markdown bullet each."""
    moves = []
    for e in real:
        rank = min((MOVE_RANK.get(t, 5) for t in e.get("tags") or []), default=5)
        tag = min(e.get("tags") or ["messaging"], key=lambda t: MOVE_RANK.get(t, 5))
        what = _quote(e.get("summary") or "page changed")
        moves.append((rank, f"- **{e['competitor']}** `{tag}` [{e['label']}]({e['url']}) page: {what}"))
    for i in found:
        title = _quote(i.get("title") or "(untitled)")
        link = f"[{title}]({i['url']})" if i.get("url") else title
        moves.append((MOVE_RANK.get(i["type"], 5), f"- **{i['competitor']}** `{i['type']}` {link}"))
    moves.sort(key=lambda m: m[0])  # stable: keeps page changes before intel at equal rank
    return [line for _, line in moves[:limit]]


def watch_table(targets, health):
    """Watch-list table: one row per competitor in `targets` (from load_targets), with how many
    of its pages the last scan could read, from `health` (status.json targets)."""
    comps = {}
    for t in targets:
        comps.setdefault(t["competitor"], t)
    out = ["| Competitor | Group | Added | Why it's watched | Pages |", "|---|---|---|---|---|"]
    for name in sorted(comps, key=str.lower):
        t = comps[name]
        pages = [h for h in health if h.get("competitor") == name]
        ok = sum(bool(h.get("ok")) for h in pages)
        state = "not scanned yet" if not pages else \
            f"{ok} OK" + (f", **{len(pages) - ok} broken**" if len(pages) > ok else "")
        out.append(f"| {_quote(name)} | {_quote(t.get('group') or '')} | {t.get('added') or ''} | "
                   f"{_quote(t.get('reason') or '')} | {state} |")
    return out


def render_report(changes, status, now, days=1, intel=None, targets=None, candidates=None):
    """Markdown report of what was found in the `days` days up to `now`, plus scan health.
    With `targets` (the watch list from load_targets), it ends with a watch-list table.
    With `candidates` (from list_candidates), ones seen on PROMOTE_AFTER+ days are listed as
    "Consider adding"."""
    end = _ts(now)
    start = end - dt.timedelta(days=days)
    within = lambda d: (t := _ts(d)) is not None and start < t <= end
    recent = [e for e in changes if within(e.get("date"))]
    # Hand-edited items may lack `found`; fall back to the publish date. Skip malformed items.
    found = [i for i in (intel or []) if i.get("competitor") and i.get("type") in INTEL_TYPES
             and within(i.get("found") or i.get("date"))]
    watchlist = [i for i in found if i["type"] in WATCHLIST_TYPES]
    news = [i for i in found if i["type"] not in WATCHLIST_TYPES]
    real = [e for e in recent if e["type"] == "change"]
    baselines = [e for e in recent if e["type"] == "baseline"]
    health = status.get("targets", [])
    broken = [t for t in health if not t.get("ok")]

    title = f"Tripwire report: {now[:10]}" if days == 1 else \
        f"Tripwire digest: {start.date().isoformat()} to {now[:10]}"
    out = [f"# {title}", "",
           f"{len(health)} pages watched · **{len(real)} page change{'s' * (len(real) != 1)}** · "
           f"**{len(news)} launch / news / social item{'s' * (len(news) != 1)}** · "
           f"{len(health) - len(broken)} OK · {len(broken)} not readable", ""]

    moves = top_moves(real, found)
    if moves:
        out += ["## Top moves", ""] + moves + [""]

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
                title = _quote(i.get("title") or "(untitled)")
                link = f"[{title}]({i['url']})" if i.get("url") else title
                line = f"- `{i['type']}` {link} ({i.get('date') or '?'}{src})"
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
            for pc in e.get("price_changes") or []:
                out.append(f"- Price: `{_quote(pc['old'])}` → `{_quote(pc['new'])}`")
            if e.get("price_changes"):
                out.append("")
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
    promote = [c for c in candidates or [] if int(c.get("seen") or 0) >= PROMOTE_AFTER]
    if promote:
        out += ["## Consider adding", "",
                f"Seen on {PROMOTE_AFTER}+ days of discovery but not on the watch list yet:", ""]
        for c in promote:
            name = f"[{_quote(c['name'])}]({c['url']})" if c.get("url") else _quote(c["name"])
            why = f": {_quote(c['reason'])}" if c.get("reason") else ""
            out.append(f"- **{name}** ({c['seen']} days, last {c.get('last_seen') or '?'}){why}")
        out.append("")
    if targets:
        out += ["## Watch list", ""] + watch_table(targets, health) + [""]
    return "\n".join(out).rstrip() + "\n"


def write_report(workdir, text, name):
    rdir = workdir / "reports"
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / name).write_text(text)
    (rdir / "latest.md").write_text(text)
    return rdir / name


# ---------------------------------------------------------------- identity check
def _host(url):
    from urllib.parse import urlparse
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def check_competitors(config, only=None, lines=6):
    """Fetch each competitor's home page (its first page) and report what the site says it is.

    Discovery picks competitors from search results, where names collide ("Lio" the procurement
    AI vs. another Lio). This is the evidence for confirming identity and ICP fit."""
    cfg = yaml.safe_load(Path(config).read_text()) or {}
    out = []
    for comp in cfg.get("competitors") or []:
        if comp.get("enabled", True) is False or not comp.get("pages"):
            continue
        if only and comp["name"].lower() != only.lower():
            continue
        page = next((p for p in comp["pages"] if p.get("label") == "home"), comp["pages"][0])
        row = {"competitor": comp["name"], "group": comp.get("group"), "url": page["url"],
               "fit": comp.get("fit") or comp.get("reason")}
        try:
            html, final = fetch_page(page["url"])
            ex = TextExtractor()
            ex.feed(html)
            title, text = extract_lines(html, DEFAULT_IGNORE)
            if reason := blocked_reason(title, text):
                raise RuntimeError(reason)
            row.update(ok=True, title=title, description=next(iter(ex.meta), None),
                       opening=text[:lines], final_url=final,
                       redirected_to_other_site=_host(final) != _host(page["url"]))
        except Exception as e:
            row.update(ok=False, error=f"{type(e).__name__}: {e}"[:200])
        out.append(row)
    return out


def render_check(rows):
    out = []
    for r in rows:
        out.append(f"## {r['competitor']} ({r.get('group') or 'no group'})  {r['url']}")
        if r.get("fit"):
            out.append(f"- why it's on the list: {r['fit']}")
        if not r["ok"]:
            out += [f"- NOT REACHABLE: {r['error']}", ""]
            continue
        if r["redirected_to_other_site"]:
            out.append(f"- REDIRECTS TO ANOTHER SITE: {r['final_url']} (acquired? renamed? wrong domain?)")
        out.append(f"- title: {r['title'] or '(none)'}")
        if r.get("description"):
            out.append(f"- description: {r['description']}")
        if r["opening"]:
            out.append("- opening lines: " + " | ".join(r["opening"]))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def add_competitor(config, name, url, pricing=None, group=None, reason=None, fit=None):
    """Insert a competitor at the end of the `competitors:` list, keeping comments and the rest of
    the file. Returns False if already present. Never writes a file that doesn't parse."""
    config = Path(config)
    text = config.read_text() if config.exists() else ""
    cfg = yaml.safe_load(text) or {}
    comps = cfg.get("competitors") or []
    if any(str(c.get("name", "")).lower() == name.lower() for c in comps):
        return False

    lines = text.splitlines()
    head = next((i for i, l in enumerate(lines) if re.match(r"^competitors:\s*(\[\s*\])?\s*(#.*)?$", l)), None)
    if head is None:
        lines += ([""] if text.strip() else []) + ["competitors:"]
        head = len(lines) - 1
    lines[head] = "competitors:"
    # The list runs until the next top-level key; match the indent of its existing items.
    end, indent = head + 1, None
    for j in range(head + 1, len(lines)):
        line = lines[j]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t", "-")):
            break
        if indent is None and line.lstrip().startswith("- "):
            indent = line[:len(line) - len(line.lstrip())]
        end = j + 1
    pad = "  " if indent is None else indent

    q = lambda v: json.dumps(v, ensure_ascii=False)  # JSON strings are valid YAML
    block = [f"{pad}- name: {q(name)}"]
    if group:
        block.append(f"{pad}  group: {q(group)}")
    if reason:
        block.append(f"{pad}  reason: {q(reason)}")
    if fit:
        block.append(f"{pad}  fit: {q(fit)}")
    block.append(f"{pad}  added: {dt.date.today().isoformat()}")
    block.append(f"{pad}  pages:")
    block.append(f"{pad}    - {{ label: home, url: {q(url)} }}")
    if pricing:
        block.append(f"{pad}    - {{ label: pricing, url: {q(pricing)} }}")
    new_text = "\n".join(lines[:end] + block + lines[end:]) + "\n"

    try:
        names = [c.get("name") for c in (yaml.safe_load(new_text) or {}).get("competitors") or []]
    except yaml.YAMLError as e:
        raise ValueError(f"could not add {name} to {config} without breaking it: {e}")
    if name not in names:
        raise ValueError(f"could not add {name} to {config}; edit it by hand")
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(new_text)
    return True


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description="Watch competitor pages and report what changed.")
    ap.add_argument("command", nargs="?", default="scan", choices=["scan", "report", "init", "intel", "add", "check", "candidates"])
    ap.add_argument("--config", default=os.environ.get("TRIPWIRE_CONFIG", str(DEFAULT_CONFIG)),
                    help="watch list (default: watch/targets.yml); data is stored next to it")
    ap.add_argument("name", nargs="?", help="add: competitor name")
    ap.add_argument("--url", help="add: home page URL")
    ap.add_argument("--pricing", help="add: pricing page URL")
    ap.add_argument("--group", help="add: label such as direct / platform / indirect")
    ap.add_argument("--reason", help="add: why this competitor is on the list; candidates --dismiss: why rejected")
    ap.add_argument("--dismiss", metavar="NAME", help="candidates: reject this candidate (name or URL) so it stops showing")
    ap.add_argument("--fit", help="add: their own homepage words that show the ICP overlap")
    ap.add_argument("--only", help="scan / check: only this competitor name")
    ap.add_argument("--days", type=int, default=7, help="report: how many days to cover (default 7)")
    ap.add_argument("--out", help="report: file name inside reports/ (default: printed only)")
    ap.add_argument("--file", help="intel / candidates: JSON file with a list of items (intel default: stdin)")
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
        if add_competitor(config, args.name, args.url, args.pricing, args.group, args.reason, args.fit):
            print(f"Added {args.name} to {config}.")
        else:
            print(f"{args.name} is already in {config}; nothing changed.")
        return

    if args.command == "check":
        print(render_check(check_competitors(config, only=args.only)))
        return

    if args.command == "intel":
        raw = Path(args.file).read_text() if args.file else sys.stdin.read()
        items = json.loads(raw)
        added, skipped = add_intel(workdir, items if isinstance(items, list) else [items], now)
        print(f"Logged {added} new item(s), skipped {skipped} already known.")
        return

    if args.command == "candidates":
        if args.dismiss:
            print(f"Dismissed {dismiss_candidate(workdir, args.dismiss, now, args.reason)}; "
                  "it won't show in the candidates list or Consider adding.\n")
        if args.file:
            items = json.loads(Path(args.file).read_text())
            new = add_candidates(workdir, items if isinstance(items, list) else [items], now)
            print(f"Recorded {new} new candidate(s).\n")
        print(render_candidates(list_candidates(workdir, config)))
        return

    if args.command == "report":
        text = render_report(load_json(workdir / "data" / "changes.json", []),
                             load_json(workdir / "data" / "status.json", {}), now, days=args.days,
                             intel=load_json(workdir / "data" / "intel.json", []),
                             targets=load_targets(config) if config.exists() else None,
                             candidates=list_candidates(workdir, config))
        if args.out:
            print(f"Wrote {write_report(workdir, text, args.out)}")
        else:
            print(text)
        return

    targets = load_targets(config)
    if args.only and not any(t["competitor"].lower() == args.only.lower() for t in targets):
        ap.error(f"no enabled competitor named {args.only!r} in {config}")
    real = scan(targets, now, workdir, only=args.only)
    print(f"Report: {workdir / 'reports' / 'latest.md'}")
    if gh_out := os.environ.get("GITHUB_OUTPUT"):
        with open(gh_out, "a") as f:
            f.write(f"changes={len(real)}\n")


if __name__ == "__main__":
    main()
