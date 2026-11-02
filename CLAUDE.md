# Tripwire: maintainer rules for the scheduled Claude runs

Tripwire is a Claude skill that watches competitor pages, diffs them nightly and writes a GTM report.
- Skill: `skills/tripwire/SKILL.md` (what Claude does when a user asks) and
  `skills/tripwire/scripts/tripwire.py` (scanner + reports; stdlib + pyyaml only).
- This repo's own watch list and data: `watch/` (`targets.yml`, `snapshots/`, `data/`, `reports/`).
- Tests: `tests/`. Version: `VERSION`. Plans: `ROADMAP.md`.

There is no website. Output is Markdown in `watch/reports/`.

## Daily run (3× a day): ship exactly ONE small, finished improvement

Pick the work in this order:
1. **Special request** from the prompt, if not empty.
2. **Broken scans.** Read `watch/data/status.json`. For any page with `ok: false`:
   - Wrong / moved URL → find the correct official page (WebFetch / curl) and fix `watch/targets.yml`.
   - Bot-blocked or JS-only page → improve the fetcher (headers, retries, fallback, a static
     alternative URL) or, if that's not possible, set `enabled: false` with a comment saying why.
   - Fix one page (or one root cause) per run.
3. **Noise.** Read the last ~14 days in `watch/data/changes.json` / `watch/reports/`. If a page
   reports meaningless churn (rotating testimonials, counters, trace ids, nav reordering), add a
   targeted `ignore` regex or improve extraction.
4. **Bugs** you find while reading the code.
5. Otherwise, the **top unchecked `[small]` item in `ROADMAP.md`**. Never start a `[big]` item.

Check `git log --since=24.hours` first so you don't redo or conflict with today's earlier runs.

## Weekly release (Fridays): ship ONE bigger feature

1. Special request if not empty, otherwise the **top unchecked `[big]` item in `ROADMAP.md`**.
2. Build it in **3–6 commits**, each one working and tested on its own (e.g. core logic → tests →
   wiring into the CLI/report → SKILL.md/README docs). Push after each commit.
3. Finish with a release commit: bump `VERSION` (minor: 0.2.0 → 0.3.0), add a changelog line,
   then `git tag v<version>` and `git push origin v<version>`.
4. If the feature can't be finished today, ship a complete, useful first part, split the rest into
   new roadmap items, and still release.

## Definition of done (every run)
- Every logic change has a test in `tests/`. `python -m unittest discover tests` must pass.
- `python -c "import sys; sys.path.insert(0,'skills/tripwire/scripts'); import tripwire; tripwire.load_targets('watch/targets.yml')"` must succeed.
- Reports must still render with empty data (`[]` / `{}`).
- If you change what the skill can do, update `skills/tripwire/SKILL.md` so Claude knows to use it.
- Never add a dependency that needs an API key to run. AI features stay optional.
- Never commit secrets. Don't hand-edit `watch/data/`, `watch/snapshots/` or `watch/reports/`
  (the scan owns them), except to remove data for a page you deleted.
- Update `ROADMAP.md`: tick the item (or split it), add a dated line under **Changelog**, and add
  one new idea if you have a good one (mark it `[small]` or `[big]`).
- Update `README.md` if usage changed.

## Commit and push
- Message like `feat: price change detector` / `fix: openai news blocked` / `chore: ignore trace ids on microsoft`.
- Use the commit author given in the prompt, and credit Claude as co-author with a trailer:
  `git commit --author="<author>" -m "feat: ..." -m "Co-Authored-By: Claude <noreply@anthropic.com>"`.
- `git pull --rebase origin main` then `git push origin HEAD:main`.
- If tests fail and you can't fix them, push nothing and explain why in your final message.
