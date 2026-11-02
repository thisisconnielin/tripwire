# 🔭 Stakeout

**Know what your competitors changed — every day, for free.**

Stakeout watches competitor pages (homepage, pricing, changelog, careers…), takes a snapshot every night, diffs it against yesterday, and logs what changed: price moves, new features, rewritten headlines, new roles. It runs entirely on GitHub Actions and publishes a dashboard on GitHub Pages. No server, no subscription.

Built for startup GTM teams who'd rather not pay $$$/seat for Klue or Visualping just to find out a competitor raised prices.

## How it works

```
targets.yml ──► GitHub Action (nightly) ──► fetch page ──► readable text ──► diff vs. yesterday
                                                                                  │
                     docs/ dashboard (GitHub Pages) ◄── docs/data/changes.json ◄──┘
```

- Strips scripts, styles, timestamps and © lines so you only see real changes.
- Ignores lines that merely moved around.
- Tags each change: `pricing` · `product` · `hiring` · `messaging`.
- Optional: add an `ANTHROPIC_API_KEY` repo secret and each change gets a one-sentence GTM read ("Raised Pro from $25 to $29/seat and added an Enterprise tier with SSO").

## Use it

1. **Fork** this repo (or use it as a template).
2. Edit **`targets.yml`**:
   ```yaml
   competitors:
     - name: Acme
       pages:
         - { label: pricing,   url: https://acme.com/pricing }
         - { label: changelog, url: https://acme.com/changelog }
   ```
3. **Settings → Pages** → Deploy from branch → `main` / `docs`.
4. **Actions** → *Stakeout scan* → **Run workflow**. The first run saves a baseline; changes show up from the next run.

Scans run nightly at 05:00 UTC. Change the cron in `.github/workflows/stakeout.yml`.

### Run locally

```bash
pip install pyyaml
python stakeout.py                 # scan everything
python stakeout.py --only Acme     # one competitor
python -m unittest discover tests
```

## Tuning noise

Any level of `targets.yml` (global, competitor, page) accepts:

```yaml
ignore: ["^Join \\d+ teams", "cookie"]   # regexes stripped before diffing
min_lines: 2                              # skip changes smaller than this
```

## It maintains itself

Every night `.github/workflows/daily-dev.yml` runs Claude (via [claude-code-action](https://github.com/anthropics/claude-code-action)) on this repo.
It fixes broken scans and noisy pages first, then ships the next item from [ROADMAP.md](ROADMAP.md), with tests, following the rules in [CLAUDE.md](CLAUDE.md).
Want something specific? Actions → *Daily dev (Claude)* → Run workflow → type the task.

Needs a `CLAUDE_CODE_OAUTH_TOKEN` secret (`claude setup-token`). `setup.sh` does the whole one-time setup.

## License

MIT
