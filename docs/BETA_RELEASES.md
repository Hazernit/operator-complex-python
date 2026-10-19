# Бета-сборки: Windows `.exe`/`.bat` и macOS `.app`

## Что, где и почему

**GitHub Releases** содержит готовые архивы приложения. **Git** содержит исходный код, инструкции, проверку упаковки и историю версий. Не добавлять `*.exe`, `*.app`, `runtime/` и большие `.zip` в историю Git или `main`: крупные файлы затрудняют клонирование, живут в каждом коммите и быстро дублируются.

- **Windows 10/11 x64:** один ZIP с `OperatorComplexNewInterface.exe` и `Start-OperatorComplexNewInterface.bat` плюс обязательные `runtime/` и `app/`. EXE — основной способ запуска; BAT — диагностический с консолью. Это **не** корневой `run-windows.bat` из исходного репозитория, которому может понадобиться установка Python.
- **Mac Apple Silicon (M1–M4 и новее):** один ZIP с `OperatorComplexNewInterface.app`. Распаковать и открыть/перетащить в «Программы»; отдельный Python не требуется. Для Intel Mac сборки пока нет.
- **Linux:** готового пакета нет; запуск из исходников по README.

**Уже опубликованы две независимые линии:** [Technical `v0.3.0-beta.1`](https://github.com/Hazernit/operator-complex-python/releases/tag/v0.3.0-beta.1) и [New Interface `v0.4.0-beta.1`](https://github.com/Hazernit/operator-complex-python/releases/tag/v0.4.0-beta.1). Исходники развиваются отдельно в `develop/technical` и `main`. Следующие выпуски — `v0.3.0-beta.2` и `v0.4.0-beta.2`; каждый выпуск получает **новый тег и новый Pre-release**, а не замену старого ZIP. Теги `snapshot/*` — исторические и остаются нетронутыми.

## Первоначальная публикация Beta 1 — уже выполнена

Первые две беты уже созданы и доступны в GitHub Releases. Приведённый ниже прежний сценарий с локальными ZIP оставлен только как историческая справка — **не запускайте его повторно** для занятых тегов.

При первой публикации потребовались GitHub CLI (`gh auth login` под `@Hazernit`), Python 3.11+ и два исходных архива. Скрипт не загружает бинарные файлы в Git и не отправляет дубликаты:

```bash
cd ~/Downloads/operator-complex-python
git switch main
git pull --ff-only origin main
./scripts/publish_beta_release.sh v0.4.0-beta.1 \
  "$HOME/Downloads/OperatorComplex-NewInterface-Windows-x64.zip" \
  "$HOME/Downloads/OperatorComplex-NewInterface-macOS-AppleSilicon.zip"
```

**Важное условие:** пути к ZIP должны существовать на Mac, запускающем команду. ZIP, вложенные в чат ChatGPT, **не** появляются автоматически в локальной папке `Downloads`.

Что проверяет `prepare_beta_release.py`: архивы целостные и без опасных путей; внутри соответствующие PE x64/arm64 Mach-O и входные точки EXE/BAT/APP; обе версии соответствуют выбранному тегу; содержимое Windows полностью совпадает с SHA-256 манифеста; пакетные `.py` совпадают с текущим удалённым `main` (через GitHub tree); два ZIP не идентичны. Затем копирует каждый ровно один раз с именем, включающим тег, делает `SHA256SUMS.txt` и release notes. Скрипт публикации прекращает работу, если Release или Git tag уже существует.

**Без публикации:** проверить собственные ZIP локально:

```bash
python3 scripts/prepare_beta_release.py v0.4.0-beta.1 \
  /path/to/Windows-x64.zip /path/to/macOS-arm64.zip
```

Вариант без команды: открыть https://github.com/Hazernit/operator-complex-python/releases → **Draft a new release**, установить тег `v0.4.0-beta.1`, выставить **Set as a pre-release**, загрузить **только два** новых архива (Windows + macOS) и `SHA256SUMS.txt`, вставить примечания из сгенерированного `RELEASE_NOTES.md`, нажать **Publish release**. При ручной публикации проверять, к какому коммиту привязан тег.

## Для пользователей

1. Открыть [Releases](https://github.com/Hazernit/operator-complex-python/releases), выбрать самый новый релиз с пометкой **Pre-release**.
2. Скачать ZIP **под свою ОС**; не скачивать **Source code (zip)**, так как там исходники, а не готовое приложение.
3. Полностью распаковать ZIP. На Windows открыть `.exe` **внутри** папки рядом с `runtime` и `app`. При ошибке — `.bat` и журнал `%LOCALAPPDATA%\OperatorComplexNewInterface\logs\application.log`. На Mac открыть `.app` и при необходимости разрешить запуск согласно [справке Apple](https://support.apple.com/en-us/102445) только если доверяете источнику.

Windows-пакет **статически проверен**, но исходный манифест указывает `windows_execution_tested: false`; требуется реальный smoke-test на Windows перед обещанием полной совместимости. Mac `.app` не имеет подтверждённых Developer ID и нотариального заверения Apple. Приложение предназначено для учебной симуляции, не для управления настоящими роботами.

## Выпуск обновлений

**Текущий рекомендуемый путь — [Actions → Desktop beta packages](https://github.com/Hazernit/operator-complex-python/actions/workflows/desktop-betas.yml)**. В меню **Run workflow** выбрать ветку workflow `main`, `edition=technical` или `edition=new-interface`, затем новый тег (`v0.3.0-beta.2` / `v0.4.0-beta.2`). Две нативные сборки и smoke-test проходят до автоматической публикации Pre-release. Подробная инструкция — [docs/RELEASES.md](RELEASES.md#последующие-обновления--github-actions).

Старый способ с локальными ZIP, приведённый ниже, нужен лишь для ручного режима и не должен использовать уже занятые теги.


1. Для New Interface внести изменения через PR в `main`; для Technical — в `develop/technical`.
2. Собрать **новые** Windows/macOS ZIP со свежим кодом и увеличенным `application_version`/`CFBundleShortVersionString`, если версия приложения меняется. Без обновления встроенного номера скрипт отклонит следующий minor/patch, а при устаревших `.py` в Windows — отклонит сборку.
3. Протестировать каждую собранную программу на целевой ОС, включая запуск после распаковки, импорт TXT, управление, журнал ошибок. CI-тесты Python не заменяют запуск упакованной программы.
4. Запустить ту же команду с новым beta-тегом и путями к **новым** ZIP. Следующая версия не перезаписывает предыдущую; можно откатиться через Releases.
5. Пользователь скачивает новую сборку и **заменяет приложение целиком**. Автоматического обновления внутри приложения пока **нет**; его разработка — отдельная задача с проверкой подписей/хешей и безопасным откатом.

## Ограничения доступа

Через подключённый GitHub можно управлять исходниками и Pull Requests, но для **ручной загрузки больших Release Assets** использовался `gh` владельца. Первые два выпуска **уже опубликованы**. Для дальнейших бет рекомендуется автоматизированная нативная сборка и публикация через GitHub Actions (`Desktop beta packages`) — она уже находится в `main`.