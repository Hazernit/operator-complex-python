# GitHub: доступ, защита `main`, приглашения и работа команды

**Действующий публичный репозиторий:** [Hazernit/operator-complex-python](https://github.com/Hazernit/operator-complex-python) — **уже создан и содержит код**. Повторно запускать `./scripts/publish_github.sh public` **не нужно**: этот скрипт предназначен для первичной публикации и останавливается, если репозиторий уже существует.

## Актуальная схема доступа

- Владелец: **@Hazernit**; только он может обновлять `main` и завершать слияние в неё при действующих правилах.
- GitHub Ruleset: [**Protect main - Hazernit only**](https://github.com/Hazernit/operator-complex-python/settings/rules) (active, target `main`, bypass `@Hazernit`).
- Для остальных: `Write` (не `Admin`), рабочие ветки и Pull Requests с ревью владельца. `CODEOWNERS` = `@Hazernit` назначает ревьюера; фактические ограничения устанавливает Ruleset на сервере GitHub.
- Публичный репозиторий можно читать без приглашения; приглашение даёт доступ **на запись**. Не путать возможность читать с правом пушить.

Для проверки текущих правил под учётной записью владельца:

```bash
gh auth status
gh api repos/Hazernit/operator-complex-python/rules/branches/main --jq '.[].type'
```

Ожидаются типы `update`, `deletion`, `non_fast_forward`, `pull_request`. Но итоговую настройку и исключение для владельца проверять также в [Rulesets](https://github.com/Hazernit/operator-complex-python/settings/rules). Не выдавать другим `Admin` и не отключать правила ради удобства.

### Приглашение нового участника

В папке репозитория, где существует скрипт:

```bash
./scripts/invite_collaborators.sh github_username
```

Скрипт проверяет главные ограничения `main` и отправляет приглашение с правом `Write`. Пользователь должен его **принять**. Проверить статус: [Settings → Collaborators](https://github.com/Hazernit/operator-complex-python/settings/access). Участников без подтверждения GitHub-логина не назначать на Issues.

## Четыре направления подкоманды

| Направление | Ветка направления | GitHub Issues |
| --- | --- | --- |
| Backend и единый контракт | `feature/backend` | [#1–3](https://github.com/Hazernit/operator-complex-python/issues) |
| Адаптеры / mock / Gazebo | `feature/adapters` | [#4–5](https://github.com/Hazernit/operator-complex-python/issues) |
| Карта / dashboard / live-данные | `feature/dashboard` | [#6–7](https://github.com/Hazernit/operator-complex-python/issues) |
| Миссии / сквозные сценарии | `feature/missions` | [#8–9](https://github.com/Hazernit/operator-complex-python/issues) |

Направления закреплены в плане подкоманды; для отдельного изменения рекомендуется создавать короткоживущую ветку `feature/<номер-issue>-<задача>` от актуального `main`. Ветка Git не ограничивает доступ конкретному человеку: соблюдение ответственности обеспечивается договорённостью, Issues, PR и review.

Порядок работы: [CONTRIBUTING.md](CONTRIBUTING.md).

## Снимки версий (не релизы)

- `version/v0.3` + `snapshot/v0.3` — предыдущая версия.
- `version/v0.4-new-interface` + `snapshot/v0.4-new-interface` — новый UI до переноса запускателей.
- `main` — UI 0.4 + запускатели из 0.3.

Старые ветки нужны для сравнения, **не сливать их целиком обратно в `main`**. Git-тег сам по себе не является GitHub Release. История описана в [README](README.md#версии-и-история).

## CI и ревью

GitHub Actions запускается при PR в `main` и после пуша в неё: [Python tests](https://github.com/Hazernit/operator-complex-python/actions/workflows/tests.yml). Проверять лог целиком: зеленая отметка **не доказательство**, если часть GUI-тестов пропущена. Актуальная политика и незакрытые проверки описаны в [плане улучшений](docs/IMPROVEMENT_BACKLOG.md).

Прохождение Actions само по себе не даёт другим участникам права сливать в `main`. Обязательные status checks в Ruleset — отдельная настройка, которую нужно согласованно включить после стабилизации CI.

## Для справки: первоначальная публикация другого репозитория

Только если **создаётся новый репозиторий**, можно использовать `scripts/publish_github.sh`, предварительно установив `gh`, выполнив `gh auth login` и настроив Git-авторство. Для нашего существующего `Hazernit/operator-complex-python` этот шаг **не повторять**. При прерванном SSH/push нельзя считать всё опубликованным до проверки remote и Ruleset. GitHub Free поддерживает защиту веток публичных репозиториев; приватные возможности зависят от плана GitHub.