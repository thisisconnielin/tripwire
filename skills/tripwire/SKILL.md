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
It runs locally in the user's current folder and keeps everything in `watch/` there
(suggest a dedicated folder such as `~/<company>-intel` if they're inside an unrelated code repo):

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
2. Find candidates. Use WebSearch broadly: "<company> alternatives", "<category> tools",
   "<top competitor> vs", "<category> startup raises", Product Hunt, G2 / Capterra categories,
   recent launch posts. Search results only *nominate* candidates; they never qualify one.
3. **Qualify every candidate** with the competitor test below. Most candidates should fail it.
4. Show the user a ranked list: name, url, group, confidence, and the `fit` quote. Aim for the
   8–15 strongest, not the most. Wait for approval unless the user said to go ahead.
5. Run `python SKILL_DIR/scripts/tripwire.py init` if `watch/targets.yml` doesn't exist, then add
   each approved competitor with
   `python SKILL_DIR/scripts/tripwire.py add "Name" --url <home> --pricing <url> --group <g> --reason "<why>" --fit "<their words>"`
   (keeps comments, skips duplicates, records the added date). Add changelog / blog pages by
   editing `watch/targets.yml`.
6. Run `python SKILL_DIR/scripts/tripwire.py check` and re-read every row; fix anything that
   doesn't match. Then scan (baseline) and do a daily refresh (section 3) so the first report
   has news too.

### The competitor test

A company is a competitor only if **all** of these hold, judged from **its own website**:

1. **Right company.** The domain is the product you mean. Names collide constantly (a "Lio" that
   is AI procurement software is not a "Lio" group-chat app). Open the homepage; if the title,
   description or hero describe a different product, find the right domain or reject it.
   Cross-domain redirects (`check` flags them) mean renamed, acquired or wrong.
2. **Same buyer.** It sells to the people in `company.yml` → `icp` (company size, role, consumer
   vs. business), not just "people who use AI".
3. **Same job, or a real substitute.** A buyer would compare the two when choosing. Sharing a
   technology (LLMs, agents, an API) is not enough.
4. **Live product.** The site works and the product is available (waitlist is OK; dead, parked or
   "we're shutting down" is not).

Record the evidence: `fit` = a short quote from their own title / description / hero that shows
the overlap. Confidence: **high** = all four clearly hold from their site; **medium** = buyer or
job overlaps only partly (e.g. an AI bot *inside* Slack vs. a messenger with agents) → group it
as `indirect` or leave it as a candidate; **low** → reject. Put platforms (huge companies where
the overlap is one feature) in `platform` and only watch the pages about that feature.

To add or remove something by hand, edit `watch/targets.yml` (set `enabled: false` to pause).

## 2. Get the page data

Pick what the user asked for:

| Ask | Command |
|---|---|
| "what changed" / "run a scan" (no scan today yet) | `python SKILL_DIR/scripts/tripwire.py scan` |
| one competitor | `python SKILL_DIR/scripts/tripwire.py scan --only "Name"` |
| "this week" / digest | `python SKILL_DIR/scripts/tripwire.py report --days 7` |
| "last month" | `python SKILL_DIR/scripts/tripwire.py report --days 30` |

If there is already a scan from today (check `last_run` in `watch/data/status.json`), skip the
scan and read the report. A first scan of a page only records a baseline; say so, and that changes
appear from the next scan.

Then read `watch/reports/latest.md` (or the printed report). Its **Top moves** section lists the
most important items first (pricing > launch > funding > watch list > hiring > messaging / news >
social); lead your readout with those. It ends with a **Watch list** table (group, date added,
why each competitor is watched, pages readable / broken); use it for the coverage line. For any change you will highlight, look
at the full `added` / `removed` lines in `watch/data/changes.json` so you quote them accurately.

## 3. Daily refresh (new competitors, drop-outs, launches, news, social)

Do this when asked "what did competitors do / launch / post / change today", together with a scan.
Read `watch/company.yml`, `watch/targets.yml` and the last 14 days of `watch/data/intel.json`
(so you don't log the same thing twice).

**a. Competitor list.** First run `python SKILL_DIR/scripts/tripwire.py check` and audit the
current list against the competitor test: wrong company, redirects to another site, pivoted away
from the ICP, or `fit` no longer true → fix the URL or drop it (below). Then run a few WebSearch
queries for new entrants with the same ICP (launches, funding announcements, "alternative to
<competitor>", Product Hunt). Then:
- A new company that passes the competitor test with **high** confidence → add it with `add`
  (`--reason`, `--fit`, home + pricing pages that load) and log a `competitor_added` item. Max 2
  per day. Medium-confidence candidates go in your final message, not the list.
- A watched competitor that fails the test (wrong company, shut down, acquired, pivoted away from
  the ICP, dead site) → set `enabled: false` on it with a dated comment saying why, and log
  `competitor_dropped`. Never drop on one failed fetch or a bot-protection page; need evidence
  (its own homepage, news, redirect to acquirer, shutdown notice).

**b. Activity.** Cover **every** enabled competitor: at least one WebSearch each, more for direct
competitors (news + X / LinkedIn + their blog or changelog). Partial coverage is a failed run.
Look back 7 days (30 days if `watch/data/intel.json` doesn't exist yet: first run backfill). Queries:
`"<name>" launch OR announces OR introduces`, `"<name>" site:x.com`, `site:linkedin.com "<name>"`,
`"<name>" site:producthunt.com`, `"<name>" site:news.ycombinator.com`, its blog / changelog, press.
Big platforms (ChatGPT, Claude, Gemini, Slack…): only log items relevant to the ICP (shared
workspaces, group chat, agents, team plans, pricing), not every announcement.

**c. Log findings.** Write them as a JSON list (one object per item) to `watch/intel-inbox.json`
with the Write tool, then run `python SKILL_DIR/scripts/tripwire.py intel --file watch/intel-inbox.json`
and delete the inbox file:

```json
[{"competitor": "Manus", "type": "launch", "title": "Manus launches team workspaces",
  "url": "https://...", "date": "2026-11-02", "source": "X",
  "summary": "Shared agent workspaces for teams, $39/seat; overlaps our group-chat agents."}]
```

`type` is one of `launch`, `pricing`, `funding`, `partnership`, `hiring`, `social`, `news`,
`competitor_added`, `competitor_dropped`. Every item except watch-list changes needs a real source
URL you actually saw. `date` = when it was published; only log things inside the look-back window above. If you only
know the month, use the 1st of that month and say so in the summary. The
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
