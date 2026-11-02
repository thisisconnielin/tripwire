# Roadmap

Daily runs ship the top unchecked `[small]` item (after broken scans, noise and bugs).
Friday releases ship the top unchecked `[big]` item in several commits.
Tick an item when it ships and add a line to the changelog.

## Broken scans (fix first)
- [ ] [small] ChatGPT pricing (`chatgpt.com/pricing`) returns 403: find a readable official alternative or disable with a reason
- [ ] [small] OpenAI news (`openai.com/news/`) returns 403: try the RSS feed or another official source
- [x] [small] Agnes AI home returns no readable text (JS-only): fixed by meta-tag fallback
- [x] [small] Cue home returns no readable text (JS-only): fixed by meta-tag fallback
- [ ] [small] Microsoft Copilot / Teams pages: huge diffs from "Trace Id" lines and nav variants; ignore them

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
- **2026-11-02**: JS-only pages (Agnes, Cue) now fall back to meta title/description so they can be watched.
- **2026-11-02**: v0.1. Nightly scan, readable-text diff, noise filters, change tags, optional AI summary, Pages dashboard, unit tests.
- **2026-11-02**: Teamily watch list (13 competitors, 17 pages) + `group` filter (direct / platform / indirect).
- **2026-11-02**: Self-maintaining. Nightly Claude dev run (`daily-dev.yml` + `CLAUDE.md`), `enabled: false` per page, `setup.sh`.
- **2026-11-02**: v0.2. Renamed to Tripwire and turned into a Claude skill (`skills/tripwire/`). Dashboard removed; each scan writes a Markdown report to `watch/reports/`, Friday nights add a 7-day digest. `scan` / `report` / `init` commands. Claude runs 3× a day plus a Friday release.
