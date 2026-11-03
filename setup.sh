#!/usr/bin/env bash
# One-time setup. Defaults to a private repo, without Claude credential setup.
set -euo pipefail
trap 'echo "Setup failed at line $LINENO; review the error above. Setup is incomplete." >&2' ERR
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
REPO="${REPO:-thisisconnielin/tripwire}"
REPO_VISIBILITY="${REPO_VISIBILITY:-private}"
ENABLE_DAILY_DEV="${ENABLE_DAILY_DEV:-false}"
PROVISION_CLAUDE_SECRET="${PROVISION_CLAUDE_SECRET:-false}"

fail() { echo "$*" >&2; exit 1; }
if [ "${1:-}" = --help ]; then
  cat <<'HELP'
Run: bash setup.sh
Options (environment variables):
  REPO=owner/name                  Repository to create or update
  REPO_VISIBILITY=private|public   Default: private; never changes existing visibility
  PROVISION_CLAUDE_SECRET=true|false  Default: false; explicit, interactive credential step
  ENABLE_DAILY_DEV=true|false      Default: false; requires an existing Claude OAuth secret
Scan reports are committed to watch/reports/ in the repository.
HELP
  exit 0
fi
[ "$#" -eq 0 ] || fail "Unknown argument. Run bash setup.sh --help."
case "$REPO_VISIBILITY" in private|public) ;; *) fail "REPO_VISIBILITY must be private or public." ;; esac
for value in "$ENABLE_DAILY_DEV" "$PROVISION_CLAUDE_SECRET"; do
  case "$value" in true|false) ;; *) fail "Setup flags must be true or false." ;; esac
done
command -v gh >/dev/null || fail "Install GitHub CLI, then run gh auth login before setup."
gh auth status >/dev/null 2>&1 || fail "Run gh auth login, then retry setup."

echo "1/4  Preparing $REPO ($REPO_VISIBILITY)…"
if remote="$(git remote get-url origin 2>/dev/null)"; then
  case "$remote" in
    "https://github.com/$REPO.git"|"https://github.com/$REPO"|"git@github.com:$REPO.git") ;;
    *) fail "origin points to a different repository. Fix it before retrying setup." ;;
  esac
else
  git remote add origin "https://github.com/$REPO.git"
fi
if visibility="$(gh repo view "$REPO" --json visibility --jq .visibility 2>/dev/null)"; then
  [ "$(printf '%s' "$visibility" | tr '[:upper:]' '[:lower:]')" = "$REPO_VISIBILITY" ] \
    || fail "Existing repository visibility differs. Set REPO_VISIBILITY explicitly; setup will not change it."
else
  gh repo create "$REPO" "--$REPO_VISIBILITY" \
    --description "A Claude skill that tells you what your competitors changed, and what to do about it."
fi
# Optional Claude maintenance stays gated during setup.
gh variable set ENABLE_DAILY_DEV -R "$REPO" --body false
git push -u origin main

echo "2/4  Setting your commit author (so daily commits count on your profile)…"
EMAIL="$(gh api user --jq '"\(.id)+\(.login)@users.noreply.github.com"')"
NAME="$(gh api user --jq '.name // .login')"
gh variable set COMMIT_AUTHOR -R "$REPO" --body "$NAME <$EMAIL>"
echo "     → $NAME <$EMAIL>"

echo "3/4  Claude credential setup…"
CLAUDE_CLI=claude
if command -v claude-work >/dev/null; then CLAUDE_CLI=claude-work; fi
if [ "$PROVISION_CLAUDE_SECRET" = true ]; then
  command -v "$CLAUDE_CLI" >/dev/null || fail "Install Claude Code before provisioning its secret."
  echo "     Using $CLAUDE_CLI. Select the authorized company account in your browser."
  echo "     This explicit step creates a long-lived token for GitHub Actions."
  "$CLAUDE_CLI" setup-token
  echo "     Paste that token below (input hidden). It will be stored as a GitHub Actions secret."
  gh secret set CLAUDE_CODE_OAUTH_TOKEN -R "$REPO"
else
  echo "     Skipped. No Claude credentials were generated or copied."
  echo "     After company approval, rerun with PROVISION_CLAUDE_SECRET=true."
fi
if [ "$ENABLE_DAILY_DEV" = true ]; then
  has_claude_secret="$(gh secret list -R "$REPO" --json name --jq 'any(.[]; .name == "CLAUDE_CODE_OAUTH_TOKEN")')"
  [ "$has_claude_secret" = true ] \
    || fail "Daily dev requires CLAUDE_CODE_OAUTH_TOKEN. Provision it after company approval first."
fi

echo "4/4  Running the first scan…"
gh workflow run scan.yml -R "$REPO"
gh variable set ENABLE_DAILY_DEV -R "$REPO" --body "$ENABLE_DAILY_DEV"

echo
echo "Setup complete; the first scan was dispatched. Check Actions for its result."
echo "  Repo:       https://github.com/$REPO"
echo "  Reports:    https://github.com/$REPO/blob/main/watch/reports/latest.md"
echo "  Daily dev enabled: $ENABLE_DAILY_DEV"
echo "  Schedule (PST): Claude dev 8:30am, 2:30pm, 8:30pm; intel 7:30pm; scan 9pm; release Friday 10am."
