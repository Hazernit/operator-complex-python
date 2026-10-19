#!/usr/bin/env bash
# Одноразовая публикация этого проекта в GitHub с защитой main.
# Требует Git, Python 3 и GitHub CLI (gh), авторизованный под будущим владельцем.
set -euo pipefail

fail() { printf 'Ошибка: %s\n' "$*" >&2; exit 1; }
info() { printf '\n>>> %s\n' "$*"; }

if [[ $# -ne 1 || ( "$1" != "public" && "$1" != "private" ) ]]; then
  echo 'Использование: ./scripts/publish_github.sh public|private' >&2
  exit 2
fi
visibility="$1"
for exe in git gh python3; do
  command -v "$exe" >/dev/null || fail "Установи $exe"
done

gh auth status >/dev/null 2>&1 || fail 'Сначала выполни gh auth login'
OWNER="$(gh api user --jq '.login')"
OWNER_ID="$(gh api user --jq '.id')"
REPO="${GITHUB_REPO_NAME:-operator-complex-python}"
[[ "$OWNER" == 'Hazernit' ]] || fail "Текущий GitHub-аккаунт: $OWNER. Этот пакет настроен для Hazernit. Сначала переключи аккаунт и проверь CODEOWNERS."
[[ "$REPO" =~ ^[a-zA-Z0-9_.-]+$ ]] || fail 'Недопустимое имя репозитория'

if [[ "$visibility" == private ]]; then
  echo 'ВАЖНО: правила защиты main для приватного личного репозитория требуют GitHub Pro (или подходящий платный план).'
  echo 'На GitHub Free они могут НЕ примениться. Без правил приглашать команду опасно.'
  read -r -p 'У аккаунта есть GitHub Pro и продолжать? [yes/NO]: ' confirmation
  [[ "$confirmation" == 'yes' ]] || fail 'Остановлено до создания репозитория; выбери public либо настрой GitHub Pro.'
fi

if gh repo view "$OWNER/$REPO" --json name >/dev/null 2>&1; then
  fail "Репозиторий $OWNER/$REPO уже существует: автоматический скрипт не перезаписывает его."
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
if git rev-parse --show-toplevel >/dev/null 2>&1; then
  current_root="$(git rev-parse --show-toplevel)"
  [[ "$current_root" == "$root" ]] || fail "Проект вложен в другой Git-репозиторий: $current_root"
  [[ "$(git branch --show-current)" == main ]] || fail 'Переключись на ветку main'
  if git remote get-url origin >/dev/null 2>&1; then
    fail 'Уже есть remote origin; не буду перезаписывать его.'
  fi
else
  git init -b main
fi

# Не отправлять сгенерированные каталоги и файлы, даже если они лежат в папке.
git add -A
if [[ -n "$(git ls-files | grep -E '(^|/)(\.env|id_rsa|id_ed25519|.*\.(pem|p12|pfx))$' || true)" ]]; then
  fail 'Найдены потенциальные секреты в git index. Удали их из индекса до публикации.'
fi
if ! git diff --cached --quiet; then
  git commit -m 'Initial commit: operator complex Python'
fi

git rev-parse --verify HEAD >/dev/null 2>&1 || fail 'Нет начального коммита'
info "Создаю $visibility репозиторий $OWNER/$REPO и публикую main"
gh repo create "$OWNER/$REPO" --"$visibility" --source=. --remote=origin --push

RULE_TMP="$(mktemp)"
trap 'rm -f "$RULE_TMP"' EXIT
python3 - "$OWNER_ID" "$RULE_TMP" <<'PY_RULE'
import json
import sys

owner_id = int(sys.argv[1])
path = sys.argv[2]
ruleset = {
    "name": "main - only Hazernit may update",
    "target": "branch",
    "enforcement": "active",
    "bypass_actors": [{"actor_id": owner_id, "actor_type": "User", "bypass_mode": "always"}],
    "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
    "rules": [
        {"type": "update", "parameters": {"update_allows_fetch_and_merge": False}},
        {"type": "deletion"},
        {"type": "non_fast_forward"},
        {"type": "pull_request", "parameters": {
            "allowed_merge_methods": ["squash", "merge", "rebase"],
            "dismiss_stale_reviews_on_push": True,
            "require_code_owner_review": True,
            "require_last_push_approval": False,
            "required_approving_review_count": 1,
            "required_review_thread_resolution": True,
        }},
    ],
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(ruleset, f, indent=2)
PY_RULE

info 'Устанавливаю защиту main (только @Hazernit может обновлять эту ветку)'
if ! gh api -X POST "repos/$OWNER/$REPO/rulesets" --input "$RULE_TMP" >/dev/null; then
  cat >&2 <<'EOT'

ВНИМАНИЕ: репозиторий создан и отправлен, но правила защиты MAIN НЕ УСТАНОВЛЕНЫ.
НЕ ПРИГЛАШАЙ УЧАСТНИКОВ, пока не включишь Ruleset вручную!
GitHub: Settings -> Rules -> Rulesets -> New branch ruleset
Target main; Restrict updates; Bypass: User @Hazernit only; Restrict deletions;
Block force pushes; Require a pull request; Require review from Code Owners.
Для приватных личных репозиториев нужен GitHub Pro.
EOT
  exit 1
fi

info 'Проверяю активные ограничения ветки main'
ACTUAL_RULES="$(gh api "repos/$OWNER/$REPO/rules/branches/main" --jq '[.[].type] | join(",")')"
printf 'Активные правила: %s\n' "$ACTUAL_RULES"
[[ "$ACTUAL_RULES" == *update* && "$ACTUAL_RULES" == *pull_request* ]] || fail 'Не обнаружены все необходимые ограничения; не приглашай участников.'

info 'Успех! Защищённый репозиторий опубликован.'
printf 'https://github.com/%s/%s\n' "$OWNER" "$REPO"
printf 'Для приглашения команды: ./scripts/invite_collaborators.sh username1 username2\n'
