# Tripwire: maintainer rules for the scheduled Claude dev runs

This repo is the source of **Tripwire**, a Claude skill (and plugin) for competitive intelligence:
from a company profile it finds competitors with the same ICP, tracks their website changes,
launches, news and social posts, and writes a GTM readout. Users install it and run it in their own
Claude Code; nothing in this repo scans competitors on GitHub.

- Skill: `skills/tripwire/SKILL.md` (what Claude does when a user asks) and
  `skills/tripwire/scripts/tripwire.py` (scanner, intel log, reports; stdlib + pyyaml only).
- Plugin manifests: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`.
- Tests: `tests/`. Version: `VERSION` (keep `plugin.json` "version" in sync). Plans: `ROADMAP.md`.
- Never commit a real watch list or scan data (`watch/` is gitignored). Use temp dirs and fixtures.

## Daily run (3× a day): ship exactly ONE small, finished improvement

Pick the work in this order:
1. **Special request** from the prompt, if not empty.
2. **Bugs** you find while reading the code or SKILL.md (wrong instructions count as bugs).
3. The **top unchecked `[small]` item in `ROADMAP.md`**. Never start a `[big]` item.
   For fetcher items (403, JS-only pages, noise), reproduce with a temporary watch list:
   write `/tmp/smoke/watch/targets.yml`, run
   `python skills/tripwire/scripts/tripwire.py scan --config /tmp/smoke/watch/targets.yml`,
   fix the fetcher or extraction, and add a fixture-based test.

Check `git log --since=24.hours` first so you don't redo or conflict with today's earlier runs.

## Weekly release (Fridays): ship ONE bigger feature

1. Special request if not empty, otherwise the **top unchecked `[big]` item in `ROADMAP.md`**.
2. Build it in **3–6 commits**, each one working and tested on its own (e.g. core logic → tests →
   wiring into the CLI/report → SKILL.md/README docs). Push after each commit.
3. Finish with a release commit: bump `VERSION` and `plugin.json` (minor: 0.3.0 → 0.4.0), add a
   changelog line, then `git tag v<version>` and `git push origin v<version>`.
4. If the feature can't be finished today, ship a complete, useful first part, split the rest into
   new roadmap items, and still release.

## Definition of done (every run)
- Every logic change has a test in `tests/`. `python -m unittest discover tests` must pass.
- `python -c "import sys; sys.path.insert(0,'skills/tripwire/scripts'); import tripwire; tripwire.load_targets('skills/tripwire/targets.example.yml')"` must succeed.
- Reports must still render with empty data (`[]` / `{}`).
- If you change what the skill can do, update `skills/tripwire/SKILL.md` so Claude knows to use it.
- Never add a dependency that needs an API key to run. AI features stay optional.
- Never commit secrets or a real watch list.
- Update `ROADMAP.md`: tick the item (or split it), add a dated line under **Changelog**, and add
  one new idea if you have a good one (mark it `[small]` or `[big]`).
- Update `README.md` if usage changed.

## Commit and push
- Message like `feat: price change detector` / `fix: openai news blocked` / `chore: ignore trace ids on microsoft`.
- Use the commit author given in the prompt, and credit Claude as co-author with a trailer:
  `git commit --author="<author>" -m "feat: ..." -m "Co-Authored-By: Claude <noreply@anthropic.com>"`.
- `git pull --rebase origin main` then `git push origin HEAD:main`.
- If tests fail and you can't fix them, push nothing and explain why in your final message.
