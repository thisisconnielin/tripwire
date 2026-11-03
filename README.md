# Tripwire

**A Claude skill that finds your competitors, tracks what they change, launch and post, and tells you what to do about it.**

Tell Claude your company. Tripwire works out your ICP, finds the companies selling to the same
buyers, and tracks them every day:

- **Website changes**: snapshots of home, pricing, changelog pages, diffed against the last scan.
- **Launches, news, social**: Claude searches the web for each competitor's new features, funding,
  pricing moves and posts (X, LinkedIn, Product Hunt, Hacker News, press).
- **The competitor list itself**: new entrants with your ICP are added; companies that shut down,
  pivot or get acquired are dropped, each with a reason.

Then Claude turns it into a short GTM readout: top moves, why they matter, what to do next.

No dashboard, no API key, no per-seat pricing. Just Markdown reports in your repo.

```
watch/company.yml ──► Claude + web search ──► new / dropped competitors ──► watch/targets.yml
                              │                                                │
                              └─► launches, news, social ──► data/intel.json   │
                                                                   │           ▼
          Claude GTM readout ◄── watch/reports/latest.md ◄── tripwire.py scan (page diffs)
```

- Strips scripts, styles, timestamps and © lines so you only see real changes.
- Ignores lines that merely moved around.
- Tags each change: `pricing` · `product` · `hiring` · `messaging`, and lists pricing moves first.
- Optional: set `ANTHROPIC_API_KEY` and each change gets a one-sentence summary in the report.

## Install the skill

Copy `skills/tripwire/` into your Claude skills folder:

```bash
git clone https://github.com/thisisconnielin/tripwire tripwire-src
cp -R tripwire-src/skills/tripwire ~/.claude/skills/          # for you, every project
# or: cp -R tripwire-src/skills/tripwire .claude/skills/       # for one project
pip install pyyaml
```

Then in Claude Code: *"set up tripwire for acme.com"* → it writes `watch/company.yml`, finds your
competitors, and (after you approve the list) creates `watch/targets.yml`.
After that: *"what did competitors launch this week?"*, *"weekly competitor digest"*, *"did Globex change pricing?"*

## Run it by hand

```bash
python skills/tripwire/scripts/tripwire.py init               # create watch/targets.yml
python skills/tripwire/scripts/tripwire.py scan               # scan everything → watch/reports/latest.md
python skills/tripwire/scripts/tripwire.py scan --only Acme   # one competitor
python skills/tripwire/scripts/tripwire.py report --days 7    # 7-day digest
python skills/tripwire/scripts/tripwire.py intel < items.json # log launches / news / social found on the web
python -m unittest discover tests
```

The first scan of a page saves a baseline; changes show from the next scan.

### Watch list

```yaml
competitors:
  - name: Acme
    group: direct
    pages:
      - { label: pricing,   url: https://acme.com/pricing }
      - { label: changelog, url: https://acme.com/changelog }
```

Any level (global, competitor, page) accepts:

```yaml
ignore: ["^Join \\d+ teams", "cookie"]   # regexes stripped before diffing
min_lines: 2                              # skip changes smaller than this
enabled: false                            # pause a page or competitor
```

## Automatic scans on GitHub

`.github/workflows/scan.yml` scans `watch/targets.yml` nightly at 05:00 UTC (9pm PST / 10pm PDT the
previous day), commits `watch/reports/<date>.md`, and on Friday nights adds a 7-day digest
`watch/reports/week-<date>.md`. It also rescans whenever `watch/targets.yml` changes on `main`.

The scan runs after the daily intel run, so each report includes both. This repo watches Teamily's competitors: see [`watch/reports/latest.md`](watch/reports/latest.md).

## It maintains itself

With the repository variable `ENABLE_DAILY_DEV=true` and a `CLAUDE_CODE_OAUTH_TOKEN` secret, Claude
(via [claude-code-action](https://github.com/anthropics/claude-code-action)) works on this repo:

| Workflow | When (PST) | What |
|---|---|---|
| Daily intel | 7:30pm | web search: new / dropped competitors, launches, news, social |
| Daily dev | 8:30am, 2:30pm, 8:30pm | one small tested fix or feature per run |
| Weekly release | Friday 10am | one bigger feature in 3–6 commits, `VERSION` bump, git tag |

It fixes broken scans and noisy pages first, then works through [ROADMAP.md](ROADMAP.md), following
[CLAUDE.md](CLAUDE.md). Want something specific? Actions → *Daily dev (Claude)* → Run workflow → type the task.

One-time setup from a local checkout: `bash setup.sh` (see `bash setup.sh --help`).

## Credits

Built by [Connie](https://github.com/thisisconnielin) and Claude. Every commit is co-authored by
Claude, from the first version to the daily runs.

## License

MIT
