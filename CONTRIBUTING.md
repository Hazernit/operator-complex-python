# Как работать в команде

## Роли

- Владелец репозитория — **@Hazernit**. Только он обновляет `main` и сливает PR.
- Участники получают доступ **Write**, но **не Admin**. Их изменения — только в отдельных ветках.
- Изменения в `main` защищает **GitHub Ruleset**. `CODEOWNERS` сам по себе не блокирует пуш.

## Начало работы

```bash
git clone https://github.com/Hazernit/operator-complex-python.git
cd operator-complex-python
git switch -c feature/your-task
```

Для уже клонированного репозитория перед новой задачей:

```bash
git switch main
git pull --ff-only origin main
git switch -c feature/your-next-task
```

Не работать непосредственно в `main`, не использовать `git push --force`.

## Фиксация и Pull Request

```bash
git status
git add .
git commit -m "feat: add platform adapter"
git push -u origin feature/your-task
```

Затем на GitHub: **Compare & pull request** → `base: main` → заполнить шаблон → дождаться тестов и решения @Hazernit. Право на изменение `main` должно оставаться только у владельца.

Если нужно исправить Pull Request, коммитить в **ту же** ветку и делать `git push` — PR обновится автоматически.

## При конфликтах с main

```bash
git fetch origin
git switch feature/your-task
git merge origin/main
# исправить конфликты, прогнать тесты
git add .
git commit
git push
```

## Проверки

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

GUI-тесты используют Qt offscreen; при запуске на сервере понадобится `QT_QPA_PLATFORM=offscreen`.

## Важно

В репозиторий нельзя отправлять токены, пароли, приватные SSH-ключи, реальные данные оборудования или персональные файлы. Создавать и изменять ruleset могут только администраторы; **не выдавать участникам Admin**.
