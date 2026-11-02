#!/usr/bin/env bash
# One-time setup. Run from inside this folder on your Mac:  bash setup.sh
set -euo pipefail
REPO="${REPO:-thisisconnielin/stakeout}"

command -v gh >/dev/null || { echo "Install GitHub CLI first:  brew install gh"; exit 1; }
gh auth status >/dev/null 2>&1 || gh auth login -w

echo "1/5  Creating public repo $REPO and pushing…"
if gh repo view "$REPO" >/dev/null 2>&1; then
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$REPO.git"
  git push -u origin main
else
  git remote remove origin 2>/dev/null || true
  gh repo create "$REPO" --public --source=. --push \
    --description "Know what your competitors changed — every day, for free."
fi

echo "2/5  Setting your commit author (so daily commits count on your profile)…"
EMAIL="$(gh api user/emails --jq '[.[] | select(.primary)][0].email' 2>/dev/null || true)"
[ -n "$EMAIL" ] || EMAIL="$(gh api user --jq '"\(.id)+\(.login)@users.noreply.github.com"')"
NAME="$(gh api user --jq '.name // .login')"
gh variable set COMMIT_AUTHOR -R "$REPO" --body "$NAME <$EMAIL>"
echo "     → $NAME <$EMAIL>"

echo "3/5  Connecting Claude (uses your Claude subscription)…"
if command -v claude >/dev/null; then
  echo "     A browser window will open. Approve, then copy the token it prints (sk-ant-oat…)."
  claude setup-token
else
  echo "     Claude Code isn't installed. Install it (npm i -g @anthropic-ai/claude-code), run 'claude setup-token' in another tab,"
  echo "     or paste an Anthropic API key and rename the secret to ANTHROPIC_API_KEY later."
fi
echo "     Paste the token now (input hidden):"
gh secret set CLAUDE_CODE_OAUTH_TOKEN -R "$REPO"

echo "4/5  Turning on GitHub Pages (main /docs)…"
gh api -X POST "repos/$REPO/pages" -f "source[branch]=main" -f "source[path]=/docs" >/dev/null 2>&1 \
  || gh api -X PUT "repos/$REPO/pages" -f "source[branch]=main" -f "source[path]=/docs" >/dev/null 2>&1 || true

echo "5/5  Running the first scan…"
gh workflow run stakeout.yml -R "$REPO" || true

OWNER="${REPO%%/*}"; NAME_ONLY="${REPO##*/}"
echo
echo "Done ✅"
echo "  Repo:       https://github.com/$REPO"
echo "  Dashboard:  https://$OWNER.github.io/$NAME_ONLY/   (live in ~1–2 min)"
echo "  Daily dev:  Claude ships one improvement every night ~8:30pm PT, then the scan runs at ~9pm PT."
echo "  Try it now: gh workflow run daily-dev.yml -R $REPO"
