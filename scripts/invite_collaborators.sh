#!/usr/bin/env bash
# Пригласить участников с правом Write, но без Admin.
set -euo pipefail
fail() { echo "Ошибка: $*" >&2; exit 1; }
[[ $# -ge 1 ]] || fail 'Использование: ./scripts/invite_collaborators.sh username1 username2 ...'
command -v gh >/dev/null || fail 'Требуется GitHub CLI (gh)'
gh auth status >/dev/null 2>&1 || fail 'Сначала gh auth login'
owner="$(gh api user --jq '.login')"
[[ "$owner" == 'Hazernit' ]] || fail "Нужно войти в @Hazernit; сейчас: $owner"
repo="${GITHUB_REPO_NAME:-operator-complex-python}"
# Не приглашать, если active main не защищена.
rules="$(gh api "repos/$owner/$repo/rules/branches/main" --jq '[.[].type] | join(",")')" || fail 'Правила main недоступны'
[[ "$rules" == *update* && "$rules" == *pull_request* ]] || fail 'main недостаточно защищена. Участники пока не приглашены.'
for username in "$@"; do
  [[ "$username" =~ ^[a-zA-Z0-9-]+$ ]] || fail "Некорректный логин: $username"
  [[ "$(printf "%s" "$username" | tr "[:upper:]" "[:lower:]")" != "$(printf "%s" "$owner" | tr "[:upper:]" "[:lower:]")" ]] || fail 'Владелец уже имеет доступ'
  echo "Приглашаю @$username с правом write..."
  gh api -X PUT "repos/$owner/$repo/collaborators/$username" -f permission=push --silent
  echo "Отправлено приглашение @$username (пользователь должен принять его на GitHub)."
done
