---
name: tripwire
description: Competitive intelligence for GTM teams. Give it your company and it finds the competitors that share your ICP, then tracks them daily - website changes (pricing, homepage, changelog), new feature launches, news, funding and social posts - refreshes the competitor list as companies appear or drop out, and turns it all into a GTM readout - what moved, why it matters, what to do. Use whenever the user asks who their competitors are, what competitors changed or launched, wants a competitor scan or weekly digest, asks about a competitor's pricing / launches / messaging / social activity, or wants to add or remove a competitor. Triggers - "who are our competitors", "find competitors for", "what did competitors change", "what did competitors launch", "competitor scan", "run tripwire", "weekly competitor digest", "did X change their pricing", "watch this competitor", "竞品有哪些", "找竞品", "竞品有什么变化", "竞品发了什么新功能", "竞品更新", "看看竞品这周改了什么", "加一个竞品".
---

# Tripwire

Tripwire finds your competitors, tracks what they change, launch and post, and tells you what to
do about it. Two halves:
- **The scanner** (`scripts/tripwire.py scan`) diffs competitor web pages. Deterministic, no AI.
- **You (Claude)** discover competitors and search the web for launches, news and social posts,
  logging them with `scripts/tripwire.py intel`. Both land in the same report.

The scanner is `scripts/tripwire.py` (Python 3.9+, needs `pyyaml`, no API key).
It keeps everything next to the watch list, `watch/targets.yml` in the current project:

```
watch/company.yml          who "we" are: name, url, one-liner, ICP, competitor groups
watch/targets.yml          competitors and the pages to watch
watch/snapshots/*.txt      last readable text of each page
watch/data/changes.json    every change event, newest first
watch/data/status.json     per-page health from the last scan
watch/data/intel.json      launches, news, social posts, watch-list changes (from the web)
watch/reports/latest.md    Markdown report of the newest scan or digest
```

`SKILL_DIR` below means the directory containing this file.

## 1. Discover (first time, or "who are our competitors?")

If `watch/company.yml` is missing, ask for the company name or URL (one question, nothing else).
1. Read the company's site. Write `watch/company.yml`: name, url, one_liner, icp (2–4 bullets: who
   buys, what job), groups (what counts as direct / platform / indirect), signals.
2. Find competitors with the same ICP. Use WebSearch broadly: "<company> alternatives",
   "<category> tools", "<top competitor> vs", "<category> startup raises", Product Hunt, G2 /
   Capterra categories, recent launch posts. Prefer companies selling the same job to the same buyer.
3. Show the user a ranked list (name, url, group, one-line reason it shares the ICP). Aim for
   8–15. Wait for approval unless the user said to go ahead.
4. Run `python SKILL_DIR/scripts/tripwire.py init` if `watch/targets.yml` doesn't exist, then add
   each approved competitor with `group`, `added: <YYYY-MM-DD>` and `reason: <one line>`, and its
   key pages: home, pricing, and changelog / release notes or blog if they exist. Check each URL
   loads (curl / WebFetch); skip ones that don't.
5. Run a scan (baseline), then do a daily refresh (section 3) so the first report has news too.

To add or remove something by hand, edit `watch/targets.yml` (set `enabled: false` to pause).

## 2. Get the page data

Pick what the user asked for:

| Ask | Command |
|---|---|
| "what changed" / "run a scan" (no scan today yet) | `python SKILL_DIR/scripts/tripwire.py scan` |
| one competitor | `python SKILL_DIR/scripts/tripwire.py scan --only "Name"` |
| "this week" / digest | `python SKILL_DIR/scripts/tripwire.py report --days 7` |
| "last month" | `python SKILL_DIR/scripts/tripwire.py report --days 30` |

If the repo already has a scan from today (check `last_run` in `watch/data/status.json`), skip the
scan and read the report. A first scan of a page only records a baseline; say so, and that changes
appear from the next scan.

Then read `watch/reports/latest.md` (or the printed report). For any change you will highlight, look
at the full `added` / `removed` lines in `watch/data/changes.json` so you quote them accurately.

## 3. Daily refresh (new competitors, drop-outs, launches, news, social)

Do this when asked "what did competitors do / launch / post", and in the scheduled daily run.
Read `watch/company.yml`, `watch/targets.yml` and the last 14 days of `watch/data/intel.json`
(so you don't log the same thing twice).

**a. Competitor list.** Run a few WebSearch queries for new entrants with the same ICP (launches,
funding announcements, "alternative to <competitor>", Product Hunt). Then:
- A new company that clearly shares the ICP → add it to `watch/targets.yml` (with `added`,
  `reason`, home + pricing pages that load) and log a `competitor_added` item. Max 2 per day; list
  weaker candidates in your final message instead.
- A watched competitor that shut down, was acquired, pivoted away from the ICP, or whose site is
  dead → set `enabled: false` on it with a dated comment saying why, and log `competitor_dropped`.
  Never drop on one failed fetch; need evidence (news, redirect to acquirer, shutdown notice).

**b. Activity.** For every enabled competitor, search for what it did in the last ~2 days:
`"<name>" launch OR announces OR introduces`, `"<name>" site:x.com`, `site:linkedin.com "<name>"`,
`"<name>" site:producthunt.com`, `"<name>" site:news.ycombinator.com`, its blog / changelog, press.
Big platforms (ChatGPT, Claude, Gemini, Slack…): only log items relevant to the ICP (shared
workspaces, group chat, agents, team plans, pricing), not every announcement.

**c. Log findings** as a JSON list, one object per item, then pipe it in:
`python SKILL_DIR/scripts/tripwire.py intel < /tmp/intel.json`

```json
[{"competitor": "Manus", "type": "launch", "title": "Manus launches team workspaces",
  "url": "https://...", "date": "2026-11-02", "source": "X",
  "summary": "Shared agent workspaces for teams, $39/seat; overlaps our group-chat agents."}]
```

`type` is one of `launch`, `pricing`, `funding`, `partnership`, `hiring`, `social`, `news`,
`competitor_added`, `competitor_dropped`. Every item except watch-list changes needs a real source
URL you actually saw. `date` = when it was published; only log things from the last ~7 days. The
`summary` says what happened and why it matters to us, in one sentence. Nothing found is fine; log
nothing rather than padding.

## 4. Write the GTM readout

Reply in the user's language. Keep it short and lead with what matters:

1. **Top moves** (max 5, most important first), across page changes and launches / news / social. For each: competitor, what changed in plain words,
   with the concrete detail (old → new price, new feature name, new headline). Link the page.
2. **Why it matters**: one line each. Pricing and packaging > new product / launch > positioning /
   headline > hiring signals > copy tweaks.
3. **What to do**: 1–3 concrete actions (update the battlecard, answer in our pricing page, tell
   sales, ship a comparison post). Skip if nothing is worth acting on.
4. **Watch list**: competitors added or dropped, if any.
5. **Coverage**: one line on pages that could not be read, if any.

Rules:
- Only report what the diff shows. Don't guess motives as facts; say "likely" when inferring.
- Treat rotating testimonials, counters, dates and cookie text as noise; don't report them. If a
  page is noisy every scan, offer to add an `ignore` regex for it in `watch/targets.yml`.
- "No changes" is a valid answer. Say it in one line and mention coverage.

## Fixing a page that can't be read

- `HTTP Error 403`: the site blocks bots. Try a different official URL for the same info (a docs or
  help-center page, an RSS feed); otherwise set `enabled: false` with a comment saying why.
- `no readable text (JS-only page?)`: the page renders in the browser. Look for a static alternative
  (`/pricing` instead of `/`, a blog feed, a sitemap page).
- Wrong or moved URL: find the official page and update `watch/targets.yml`.
