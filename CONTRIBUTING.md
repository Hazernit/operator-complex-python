# Командная разработка: Issues → ветка → Pull Request → проверка

В проекте четыре направления: **backend**, **адаптеры/эмуляторы**, **dashboard**, **миссии/интеграция**. Их задачи отслеживаются в [GitHub Issues](https://github.com/Hazernit/operator-complex-python/issues), а код объединяется в защищённую ветку `main`.

## Права и ответственность

- **@Hazernit** — владелец и CODEOWNER. Право обновлять `main` и завершать Pull Request в неё зарезервировано за ним через активный Ruleset.
- Остальные получают **Write, не Admin**. Можно создавать/пушить `feature/*`, создавать Issues и Pull Requests; **нельзя напрямую обновлять `main`**.
- Уже существуют ветки направлений: `feature/backend`, `feature/adapters`, `feature/dashboard`, `feature/missions`. Наличие ветки не делает её закрытой для других: GitHub не выдаёт права «только своему разработчику» автоматически.
- Для отдельной задачи лучше создать короткоживущую ветку `feature/<issue>-<краткое-название>` от свежего `main`, чтобы PR был небольшим и легко проверялся.

## Первая настройка

```bash
git clone https://github.com/Hazernit/operator-complex-python.git
cd operator-complex-python
git switch main
git pull --ff-only origin main
git switch -c feature/4-mock-adapters
```

SSH-ссылка `git@github.com:Hazernit/operator-complex-python.git` тоже подходит, если в вашем GitHub-аккаунте уже настроен SSH-ключ. Для `push` требуется принятое приглашение в collaborators.

## Работа над задачей

1. Выберите Issue из своего направления, уточните входные/выходные данные и **Definition of Done**.
2. Создайте ветку от актуального `main`; реализуйте функцию и тесты, не смешивая чужие направления без согласования.
3. Запускайте локально: `python -m unittest discover -s tests -v`, для GUI — `python main.py --smoke-test` (с PySide6). Указывайте **пропуски тестов** отдельно.
4. Зафиксируйте и отправьте изменение:

```bash
git status
git add -A
git commit -m "feat: implement mock adapter (#4)"
git push -u origin feature/4-mock-adapters
```

5. Создайте PR: **base `main`**, head ваша ветка. Опишите проблему, изменённые файлы, тесты и ограничения; приложите скриншоты при изменении UI. Упомяните Issue (`Closes #4` только если задача действительно закрывается).
6. Дождитесь CI, ревью владельца; исправления отправляйте в **ту же** ветку — PR обновится автоматически.

## Если `main` изменилась

```bash
git fetch origin
git switch feature/4-mock-adapters
git merge origin/main
```

Разрешите конфликты, выполните тесты, затем `git add -A`, `git commit` и `git push`. Не применяйте `git push --force` к общим веткам. Нельзя использовать `main` или ветку сохранённой версии (`version/*`) для собственной разработки.

## Зависимости и интеграция

Перед независимой разработкой согласуйте `VehicleTelemetry`, `VehicleCommand`, `Mission`, `MissionEvent`: идентификаторы, единицы, таймстемпы, подтверждение команды и статусы. До готовности backend работайте через mock на своей границе. Не выдавайте симуляцию за работающий ROS 2/реальный робот.

Отдельная документация: [GitHub-правила](GITHUB_SETUP.md), [архитектура и roadmap](README.md#план-разработки), [стандарт аудита](docs/REPOSITORY_AUDIT_PLAYBOOK.md).

## Безопасность

Не публикуйте `.env`, пароли, ключи, `.venv`, настоящую телеметрию устройств, конфиденциальные логи или персональные данные. При работе с физическими платформами STOP из локального прототипа **не заменяет аппаратный safety-контур**. Не выдавайте участникам Admin.