# Tripwire

**A skill that finds your competitors, tracks what they change, launch and post, and tells you what to do about it.**

Tell AI your company. Tripwire works out your ICP, finds the companies selling to the same
buyers, and tracks them every time you ask:

- **Website changes**: snapshots of home, pricing, changelog pages, diffed against the last scan.
- **Launches, news, social**: Claude searches the web for each competitor's new features, funding,
  pricing moves and posts (X, LinkedIn, Product Hunt, Hacker News, press).
- **The competitor list itself**: new entrants with your ICP are added; companies that shut down,
  pivot or get acquired are dropped, each with a reason.

Then Claude turns it into a short GTM readout: top moves, why they matter, what to do next.
It runs in your own Claude Code, on your machine. No dashboard, no API key, no per-seat pricing.

## Install

In Claude Code:

```
/plugin marketplace add thisisconnielin/tripwire
/plugin install tripwire@tripwire
```

Or copy the skill folder by hand:

```bash
git clone https://github.com/thisisconnielin/tripwire
cp -R tripwire/skills/tripwire ~/.claude/skills/
```

Tripwire needs Python 3.9+ with `pyyaml` (`pip install pyyaml`).

## Use

Make a folder for your intel and open Claude Code there:

```bash
mkdir ~/acme-intel && cd ~/acme-intel && claude
```

Then just ask:

- *"Set up tripwire for acme.com"*: writes `watch/company.yml` (your ICP), finds competitors,
  and after you approve the list, creates `watch/targets.yml` and takes a baseline.
- *"What did our competitors change / launch today?"*: scans their pages, searches the web for
  launches, news and posts, updates the competitor list, and gives you the readout.
- *"Weekly competitor digest"*, *"did Globex change pricing?"*, *"stop watching Initech"*.

Everything stays in `watch/` in that folder:

```
watch/company.yml         who you are + your ICP
watch/targets.yml         competitors and the pages to watch
watch/snapshots/          last readable text of each page
watch/data/               changes.json, intel.json (launches/news/social), status.json
watch/reports/latest.md   the newest report
```

```
company.yml ──► Claude + web search ──► new / dropped competitors ──► targets.yml
                       │                                                  │
                       └─► launches, news, social ──► data/intel.json     │
                                                            │             ▼
   Claude GTM readout ◄── reports/latest.md ◄──────── tripwire.py scan (page diffs)
```

### The scanner by itself

The page diffing is a plain Python script you can also run without Claude:

```bash
S=~/.claude/skills/tripwire/scripts/tripwire.py
python $S init                 # create watch/targets.yml
python $S add "Acme" --url https://acme.com --pricing https://acme.com/pricing --group direct --reason "same ICP"
python $S scan                 # scan everything → watch/reports/latest.md
python $S scan --only Acme     # one competitor
python $S report --days 7      # 7-day digest
python $S intel --file x.json  # log launches / news / social items
```

The first scan of a page saves a baseline; changes show from the next scan.

Any level of `watch/targets.yml` (global, competitor, page) accepts:

```yaml
ignore: ["^Join \\d+ teams", "cookie"]   # regexes stripped before diffing
min_lines: 2                              # skip changes smaller than this
enabled: false                            # pause a page or competitor
```

## How this repo is maintained

Connie develops Tripwire with Claude, via [claude-code-action](https://github.com/anthropics/claude-code-action)
(this only touches the skill's code; it never scans anyone's competitors):

| Workflow | When (PST) | What |
|---|---|---|
| Weekly release | Friday 10am | one bigger feature in 3–6 commits, version bump, git tag |

It follows [CLAUDE.md](CLAUDE.md) and works through [ROADMAP.md](ROADMAP.md).
Run tests with `python -m unittest discover tests`.

## Credits

Built by [Connie](https://github.com/thisisconnielin) and Claude, sometime Codex.

## License

MIT
