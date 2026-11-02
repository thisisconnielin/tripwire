---
name: tripwire
description: Competitor change tracker for GTM teams. Snapshots competitor pages (homepage, pricing, changelog, careers), diffs them against the last scan, and turns the changes into a GTM readout - what moved, why it matters, what to do. Use whenever the user asks what competitors changed, wants a competitor scan or weekly digest, asks about a competitor's pricing / launches / messaging / hiring changes, or wants to add or remove a competitor or page from the watch list. Triggers - "what did competitors change", "competitor scan", "run tripwire", "weekly competitor digest", "did X change their pricing", "watch this competitor", "竞品有什么变化", "竞品更新", "看看竞品这周改了什么", "加一个竞品".
---

# Tripwire

Tripwire tells you when a competitor changes a page that matters, and what to do about it.
The scanner is `scripts/tripwire.py` (Python 3.9+, needs `pyyaml`, no API key).
It keeps everything next to the watch list, `watch/targets.yml` in the current project:

```
watch/targets.yml          what to watch
watch/snapshots/*.txt      last readable text of each page
watch/data/changes.json    every change event, newest first
watch/data/status.json     per-page health from the last scan
watch/reports/latest.md    Markdown report of the newest scan or digest
```

`SKILL_DIR` below means the directory containing this file.

## 1. Make sure there is a watch list

If `watch/targets.yml` does not exist, run `python SKILL_DIR/scripts/tripwire.py init`, then ask the
user which competitors and pages to watch and write them into the file. Good pages: home, pricing,
changelog / release notes, careers, the "vs" or comparison page. Use the official URL; check it loads.

To add or remove something, edit `watch/targets.yml` (set `enabled: false` to pause a page).

## 2. Get the data

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

## 3. Write the GTM readout

Reply in the user's language. Keep it short and lead with what matters:

1. **Top moves** (max 5, most important first). For each: competitor, what changed in plain words,
   with the concrete detail (old → new price, new feature name, new headline). Link the page.
2. **Why it matters**: one line each. Pricing and packaging > new product / launch > positioning /
   headline > hiring signals > copy tweaks.
3. **What to do**: 1–3 concrete actions (update the battlecard, answer in our pricing page, tell
   sales, ship a comparison post). Skip if nothing is worth acting on.
4. **Coverage**: one line on pages that could not be read, if any.

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
