# Публикация проекта и работа командой на GitHub

GitHub-владелец: **@Hazernit**. Название по умолчанию: **operator-complex-python**.

## Что уже подготовлено

- `.gitignore` защищает от случайной публикации типовых секретов, виртуальных окружений и генерируемых файлов.
- `.github/CODEOWNERS` назначает **@Hazernit** владельцем всего кода (но сам по себе не запрещает push).
- `.github/workflows/tests.yml` запускает unittest при push в `main` и на PR.
- Шаблон Pull Request и `CONTRIBUTING.md` описывают рабочий процесс.
- `scripts/publish_github.sh` публикует проект и вызывает REST API GitHub, чтобы настроить **активный ruleset** для `main`.
- `scripts/invite_collaborators.sh` приглашает людей **без прав администратора**.

## Один раз на Mac

Установить GitHub CLI, если его нет:

```bash
brew install gh
```

Выполнить вход **под @Hazernit** и настроить авторство Git-коммитов:

```bash
gh auth login
git config --global user.name "Твоё имя или ник для Git"
git config --global user.email "Твой email из GitHub (можно noreply)"
```

Зайди в папку этого проекта (где лежит `pyproject.toml`) и выбери режим публикации:

```bash
./scripts/publish_github.sh public
```

Для **приватного** репозитория **понадобится GitHub Pro или подходящий план организации**, иначе GitHub Free не гарантирует защиту `main` через rulesets. Если GitHub Pro уже есть:

```bash
./scripts/publish_github.sh private
```

Публичный репозиторий виден всем, даже тем, кого не приглашали; незнакомые люди не могут в него пушить. Приватный доступен только приглашённым пользователям.

**Важно:** если скрипт напишет, что ruleset НЕ установлен, **никого не приглашай**, пока не исправишь ошибку. Скрипт не удаляет опубликованный репозиторий при такой ошибке, чтобы не потерять данные.

## Добавить участников

После успешного подтверждения защиты `main`:

```bash
./scripts/invite_collaborators.sh githubUser1 githubUser2
```

Они получат приглашения с правом **Write** (не Admin), должны принять их в GitHub. Владелец остаётся единственным, кто может обновлять `main` и сливать PR.

## Как должна работать защита

`Settings` → `Rules` → `Rulesets` → **main - only Hazernit may update**.

- Enforcement = `Active`.
- Target branches = `main`.
- `Restrict updates` = включено.
- `Bypass` = только пользователь `@Hazernit`, `Always allow`.
- `Restrict deletions` и `Block force pushes` = включено.
- `Require a pull request before merging` + 1 approval + `Require review from Code Owners` = включено.

Это означает, что участники могут писать в `feature/*` и присылать PR, **но никто кроме владельца не может ни напрямую пушить в `main`, ни завершить слияние PR**. Владелец сможет обновлять `main` напрямую или через Merge pull request по своему выбору (у него есть исключение из правил).

Защита применяется на стороне GitHub, а не на компьютерах участников. Если выдашь кому-то **Admin**, человек сможет изменять сами правила, поэтому приглашай с **Write**.

## Работа участников

См. [CONTRIBUTING.md](CONTRIBUTING.md). Git-последовательность:

```bash
git clone https://github.com/Hazernit/operator-complex-python.git
cd operator-complex-python
git switch -c feature/my-part
git add .
git commit -m "feat: implement my part"
git push -u origin feature/my-part
```

Потом на GitHub: создать Pull Request в `main`. Владелец проверяет и сам нажимает Merge.

## Проверить ограничения вручную

```bash
gh api repos/Hazernit/operator-complex-python/rules/branches/main --jq '.[].type'
```

Ожидается наличие `update`, `deletion`, `non_fast_forward`, `pull_request`.

Тесты GitHub Actions автоматически запускаются на PR. **Они пока не являются обязательной блокирующей проверкой**: её можно включить в ruleset после первого успешного запуска, чтобы не заблокировать слияния ошибкой в свежем CI.
