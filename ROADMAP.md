# Roadmap

Stakeout ships one small improvement a day. Each entry is sized so it fits in one day.
Pick the top unchecked item unless there's a bug or a user request. Move it to the changelog once it ships.

## Next up
- [ ] Price detector: pair a removed line with an added line that differ only in a price → "Pro: $25 → $29/mo"
- [ ] Headline watcher: flag when the H1 / hero line changes (the clearest messaging signal)
- [ ] JS-rendered pages: optional `render: true` per page using Playwright, for SPAs that return empty HTML
- [ ] Weekly digest: Monday markdown summary committed to `digests/` + shown on the dashboard
- [ ] Slack / Discord webhook alert when a `pricing` change lands
- [ ] Email alert via a repo secret (Resend)
- [ ] Per-competitor page on the dashboard with a change timeline
- [ ] Dashboard: "copy as Slack message" button on each change
- [ ] Sitemap watcher: alert on new URLs (new landing pages, new docs, new /vs pages)
- [ ] Changelog/RSS mode: parse a blog or changelog feed and list new posts
- [ ] Careers counter: track number of open roles over time + chart
- [ ] Pricing table extractor → structured plans/prices comparison across competitors
- [ ] Battlecard generator: one page per competitor from its last 30 days of changes
- [ ] Product Hunt launch watcher for competitor names
- [ ] Screenshot of each page on change (Playwright), shown next to the diff
- [ ] `stakeout add <url>` CLI helper that appends to targets.yml
- [ ] Noise auto-learning: suggest ignore rules for lines that flip every day
- [ ] Dark/light toggle + RSS feed of changes for the dashboard

## Changelog
- **2026-11-02**: v0.1. Nightly scan, readable-text diff, noise filters, change tags, optional AI summary, Pages dashboard, unit tests.
