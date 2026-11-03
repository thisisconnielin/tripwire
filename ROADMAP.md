# Roadmap

Daily runs ship the top unchecked `[small]` item (after broken scans, noise and bugs).
Friday releases ship the top unchecked `[big]` item in several commits.
Tick an item when it ships and add a line to the changelog.

## Core: find and track competitors (highest priority after broken scans)
- [x] [small] `tripwire.py add <name> --url <home> [--pricing URL] [--group G] [--reason R]` appends a competitor to `watch/targets.yml` without losing comments, so discovery doesn't hand-edit YAML
- [ ] [small] Report: "Top moves" line at the very top, mixing page changes and intel by importance (pricing > launch > funding > social)
- [ ] [small] Report: watch-list table (competitor, group, added date, reason, pages OK / broken)
- [ ] [small] `tripwire.py candidates`: keep a `data/candidates.json` of possible competitors seen but not added, with how often they show up, so strong ones get promoted
- [ ] [big] Free feeds without AI: for each competitor, auto-detect blog / changelog RSS and log new posts as `launch` / `news` intel
- [ ] [big] Hacker News (Algolia API) + Product Hunt + GitHub releases: log competitor mentions and launches as intel, no API key
- [ ] [big] Competitor profile pages: `watch/competitors/<slug>.md` with positioning, pricing, latest launches, 30-day timeline

## Fetcher fixes (reproduce with a temporary watch list, see CLAUDE.md)
- [ ] [small] ChatGPT pricing (`chatgpt.com/pricing`) returns 403: find a readable official alternative or disable with a reason
- [x] [small] OpenAI news (`openai.com/news/`) returns 403: `openai.com/news/rss.xml` is readable; use that
- [x] [small] Agnes AI home returns no readable text (JS-only): fixed by meta-tag fallback
- [x] [small] Cue home returns no readable text (JS-only): fixed by meta-tag fallback
- [x] [small] Microsoft Copilot / Teams pages: fake diffs from "Trace Id" lines; ignored by default
- [x] [small] 308 redirects (e.g. asklio.ai) failed on Python < 3.11; transient errors weren't retried
- [ ] [small] Footnote markers glued to words ("plan6" → "plan7" on gemini.google) cause fake diffs; detect and normalise them safely
- [ ] [small] Sitemap / feed hint: when a page is 403 or JS-only, look for `<link rel=alternate>` RSS or `/rss.xml` and suggest it in the report

## Next up
- [ ] [small] Price detector: pair a removed and an added line that differ only in a price → "Pro: $25 → $29/mo" in the report
- [ ] [small] Headline watcher: flag when the H1 / hero line changes (the clearest messaging signal)
- [ ] [small] Report: put a one-line "Top moves" summary at the very top of each report
- [ ] [small] `tripwire.py add <name> <url> [--label]` appends a page to `watch/targets.yml`
- [ ] [small] Report: show "first seen / last changed" per page in a coverage table
- [ ] [small] Noise auto-learning: list lines that flip every scan and suggest `ignore` rules
- [ ] [big] Battlecard generator: `tripwire.py battlecard <name>` builds a Markdown battlecard from 30 days of changes + current pricing snapshot
- [ ] [big] Pricing table extractor → structured plans/prices per competitor, compared side by side in the report
- [ ] [big] JS-rendered pages: optional `render: true` per page using Playwright, for SPAs that return empty HTML
- [ ] [small] Watch `<link rel=alternate>` feeds / sitemap hints for JS-only pages
- [ ] [big] Changelog/RSS mode: parse a blog or changelog feed and report new posts
- [ ] [big] Sitemap watcher: report new URLs (new landing pages, docs, /vs pages)
- [ ] [big] Careers counter: track number of open roles over time
- [ ] [big] Slack / Discord webhook alert when a `pricing` change lands (optional secret)

## Changelog
- **2026-11-03**: Accurate competitors. SKILL.md gets a 4-part competitor test (right company, same buyer, same job, live product) judged from each company's own site, with a `fit` quote and confidence; the daily refresh audits the existing list with the new `tripwire.py check`. Block pages ("request has been blocked") are errors, not changes. Page titles ignore SVG tooltips.
- **2026-11-03**: Bug fixes. `scan --only` no longer wipes other pages from the report; fetcher follows 308 redirects and retries timeouts / 5xx; report tolerates hand-edited intel and bad dates; `add` inserts into the competitor list instead of breaking files where other keys follow it; trace / request ids and hashes are ignored by default.
- **2026-11-03**: `tripwire.py add "Name" --url ... [--pricing --group --reason]` appends a competitor to the watch list without losing comments.
- **2026-11-03**: v0.3. Skill-only: installable as a Claude Code plugin (`.claude-plugin/`), runs locally in the user's folder. Removed the GitHub scan and intel workflows and the committed Teamily data; GitHub only runs Claude's dev and release work.
- **2026-11-02**: Competitive intelligence. `watch/company.yml` (who we are + ICP), Claude web-search refresh that adds new competitors with the same ICP, drops dead ones, and logs launches / news / social via `tripwire.py intel`. Reports get "Watch list changes" and "Launches, news & social" sections. SKILL.md gains Discover and Daily refresh.
- **2026-11-02**: JS-only pages (Agnes, Cue) now fall back to meta title/description so they can be watched.
- **2026-11-02**: v0.1. Nightly scan, readable-text diff, noise filters, change tags, optional AI summary, Pages dashboard, unit tests.
- **2026-11-02**: Teamily watch list (13 competitors, 17 pages) + `group` filter (direct / platform / indirect).
- **2026-11-02**: Self-maintaining. Nightly Claude dev run (`daily-dev.yml` + `CLAUDE.md`), `enabled: false` per page, `setup.sh`.
- **2026-11-02**: v0.2. Renamed to Tripwire and turned into a Claude skill (`skills/tripwire/`). Dashboard removed; each scan writes a Markdown report to `watch/reports/`, Friday nights add a 7-day digest. `scan` / `report` / `init` commands. Claude runs 3× a day plus a Friday release.
