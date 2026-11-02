# 🔭 Stakeout

**Know what your competitors changed — every day, for free.**

Stakeout watches competitor pages (homepage, pricing, changelog, careers…), takes a snapshot every night, diffs it against yesterday, and logs what changed: price moves, new features, rewritten headlines, new roles. It runs on GitHub Actions and can publish a dashboard on GitHub Pages. Scanning needs no AI subscription; optional Claude maintenance uses your authorized Claude plan.

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
3. For a public dashboard, choose **Settings → Pages → GitHub Actions** and add the repository variable **`ENABLE_PUBLIC_DASHBOARD=true`**. Private repositories default to no dashboard deployment; Pages support for private repositories depends on your GitHub plan. Publishing a dashboard exposes its `docs/` content, including the watch list and scan results.
4. **Actions** → *Stakeout scan* → **Run workflow**. The first run saves a baseline; changes show up from the next run.

Scans run nightly at 05:00 UTC: 9pm PST / 10pm PDT on the previous calendar day. Change the cron in `.github/workflows/stakeout.yml`.

### One-time setup from a local checkout

Commit your local changes, sign in with `gh auth login`, then run:

```bash
bash setup.sh                         # private repo, scans only
REPO_VISIBILITY=public bash setup.sh  # public repo and public dashboard
```

`REPO=owner/name` selects another repository. Setup never changes an existing repository's visibility. `ENABLE_PUBLIC_DASHBOARD=true|false` explicitly controls dashboard deployment; it defaults to false for private repositories and true for public repositories. The scanner uploads and deploys the dashboard in the same workflow, so new scan data publishes even though its commit uses `GITHUB_TOKEN`.

Setup defaults to no Claude credential provisioning and leaves daily development disabled. It reports a failure if pushing, Pages configuration, or the initial scan dispatch fails. Successful setup means the scan was dispatched; check Actions to confirm the scan and any Pages deployment succeeded.

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

After explicit enablement, `.github/workflows/daily-dev.yml` runs Claude (via [claude-code-action](https://github.com/anthropics/claude-code-action)) on this repo at 04:30 UTC: 8:30pm PST / 9:30pm PDT on the previous calendar day.
It fixes broken scans and noisy pages first, then ships the next item from [ROADMAP.md](ROADMAP.md), with tests, following the rules in [CLAUDE.md](CLAUDE.md).
Want something specific? Actions → *Daily dev (Claude)* → Run workflow → type the task.

This requires a `CLAUDE_CODE_OAUTH_TOKEN` secret and the repository variable `ENABLE_DAILY_DEV=true`. Both scheduled and manual Claude jobs stay disabled until that variable is true. Company Terminal sign-in alone does not authorize copying the company credential to GitHub.

After company approval, run the separate, interactive credential step:

```bash
PROVISION_CLAUDE_SECRET=true ENABLE_DAILY_DEV=true bash setup.sh
```

Use the same `REPO_VISIBILITY` and dashboard flags as your initial setup. The script prefers `claude-work` when available, otherwise uses `claude`; it runs `setup-token`, then asks you to paste the resulting token into a GitHub Actions secret. It never copies saved Terminal credentials automatically. Claude maintenance consumes the authorized account's usage. To stop it, set `ENABLE_DAILY_DEV=false` in repository variables. The optional scanner API key is separate and is not needed for scans or subscription-based maintenance.

## License

MIT
