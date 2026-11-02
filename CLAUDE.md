# Stakeout: maintainer rules for the daily dev run

Stakeout is a public tool that watches competitor pages, diffs them nightly and shows changes on a GitHub Pages dashboard.
Code: `stakeout.py` (stdlib + pyyaml only), `docs/index.html` (single-file dashboard, no build step), `tests/`.

## Each daily run ships exactly ONE small, finished improvement

Pick the work in this order:
1. **Today's special request** from the prompt, if not empty.
2. **Broken scans.** Read `docs/data/status.json`. For any target with `ok: false`:
   - Wrong / moved URL → find the correct official page (WebFetch / curl) and fix `targets.yml`.
   - Bot-blocked or JS-only page → improve the fetcher (headers, retries, fallback) or, if that's
     not possible today, set `enabled: false` on that page with a comment saying why.
3. **Noise.** Read the last ~14 days in `docs/data/changes.json`. If a page reports the same
   meaningless churn (rotating testimonials, counters, dates), add a targeted `ignore` regex.
4. **Bugs** you find while reading the code.
5. Otherwise, the **top unchecked item in `ROADMAP.md`**.

## Definition of done
- Keep the change small enough to review in 5 minutes. Split big roadmap items and do part 1.
- Add or update a test in `tests/` for any logic change. `python -m unittest discover tests` must pass.
- `python -c "import stakeout, yaml; stakeout.load_targets('targets.yml')"` must succeed.
- Dashboard edits must keep working with empty data (`[]` / `{}`) and on phone widths.
- Never add a dependency that needs an API key to run. AI features stay optional.
- Never commit secrets. Don't edit `docs/data/` or `snapshots/` by hand (the scan owns them),
  except to remove data for a target you deleted.
- Update `ROADMAP.md`: tick the item (or split it) and add a dated line under **Changelog**.
  Add one new idea to the roadmap if you thought of a good one.
- Update `README.md` if usage changed.

## Commit and push
- One commit, message like `feat: price change detector` / `fix: teams page moved` / `chore: ignore rotating quotes on bloome`.
- Use the commit author given in the prompt: `git commit --author="<author>" -m "..."`.
- `git push origin HEAD:main`. If tests fail and you can't fix them, push nothing and explain why in your final message.
