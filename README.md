# Единый операторский комплекс — Python desktop 0.4

[![Python tests](https://github.com/Hazernit/operator-complex-python/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Hazernit/operator-complex-python/actions/workflows/tests.yml)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)
![Development](https://img.shields.io/badge/status-active%20development-informational)

**Учебный прототип единого рабочего места оператора БПЛА (UAV), наземных роботов/НРТК (UGV) и безэкипажных катеров (USV/БЭК)**. Написан на Python и PySide6. Нужен для разработки UI, команд, телеметрии, маршрутов и сценариев до подключения реальных платформ.

> **Сейчас:** локальное desktop-приложение с учебной симуляцией, демонстрационными датчиками и чтением записей. Реального управления оборудованием, FastAPI/backend, ROS 2, Gazebo, PostgreSQL и видеопровайдера **пока нет в `main`** — это следующие этапы командного проекта.
>
> **Безопасность:** кнопка **СТОП** останавливает локальную модель; это не аппаратная аварийная остановка физического робота.

![Скриншот нового рабочего пространства 0.4](docs/screenshots/overview-1440x900.png)

[Карта и датчики](docs/screenshots/sensors.png) · [Телеметрия](docs/screenshots/telemetry.png) · [Подробное руководство](docs/PROTOTYPE_GUIDE.md) · [Задачи проекта](https://github.com/Hazernit/operator-complex-python/issues)

## Скачать готовую бета-сборку

**[GitHub Releases — версии приложения для загрузки](https://github.com/Hazernit/operator-complex-python/releases).** Выберите опубликованный **Pre-release** с наиболее свежим номером; до выхода первого выпуска эта страница может быть пустой. Раздел *Assets* содержит архивы приложений, а автоматические *Source code (zip/tar.gz)* — **только исходный код**.

- **Windows 10/11 x64:** скачайте ZIP для Windows, распакуйте весь архив и откройте `OperatorComplexNewInterface.exe`. Диагностический `Start-OperatorComplexNewInterface.bat` запускает ту же программу с консолью. Python включён, папки `runtime/` и `app/` обязательны.
- **Mac Apple Silicon (M1–M4 и новее):** скачайте ZIP для macOS arm64, распакуйте `OperatorComplexNewInterface.app` и откройте его или перенесите в «Программы». Поддерживается macOS 14.4+; сборки для Intel Mac пока нет.

**Это предварительные сборки:** исходный Windows ZIP не проходил подтверждённого запуска на настоящем компьютере Windows, а macOS-приложение не имеет подтверждённых Developer ID/нотаризации и может потребовать разрешения в Gatekeeper. [Публикация, ограничения и обновления](docs/BETA_RELEASES.md). Встроенное автообновление пока не предусмотрено; новые беты публикуются отдельными выпусками с собственными тегами.

## Что реализовано, а что ещё нет

| Возможность | Состояние в `main` | Что важно знать |
| --- | --- | --- |
| Окно оператора на PySide6 | ✅ Прототип | Список платформ, поиск, карточки и общие органы управления |
| БПЛА, НРТК и БЭК | ✅ Локальные модели | Независимая симуляция, **на карте видна одна выбранная** платформа, не три сразу |
| Ручное управление / WASD / маршруты | ✅ В симуляции | Инерция моделей, запуск, пауза, продолжение и отмена маршрута |
| LiDAR, сонар, эхолот | ✅ Демонстрационные данные | Синтетические показания, не измерения реального оборудования |
| Импорт TXT/CSV | ✅ | Воспроизведение записи без отправки команд роботу |
| Предупреждения и offline/stale | ✅ Для локальной модели | Нет аппаратного подтверждения состояния |
| Windows/macOS-запускатели | ✅ Исходники | `.bat` добавлены из 0.3; реальные сценарии установки на Windows ещё требуют проверки |
| FastAPI, БД, WebSocket/live-флот | ⏳ В разработке | Отдельные направления команды, см. [Issues](https://github.com/Hazernit/operator-complex-python/issues) |
| ROS 2 / Gazebo / реальные платформы / видео | ⏳ Не подключены | Этапы интеграции, не готовые функции |

## Быстрый запуск

Исходники доступны в [публичном репозитории](https://github.com/Hazernit/operator-complex-python). **Это исходный код, а не готовый установщик или GitHub Release.** Нужен Python **3.11 или новее**; при первом запуске может понадобиться интернет для зависимостей. Локальное окружение `.venv` не хранится в Git.

Склонируйте репозиторий любым удобным способом (HTTPS не требует предварительной настройки SSH для публичного чтения):

```bash
git clone https://github.com/Hazernit/operator-complex-python.git
cd operator-complex-python
```

### macOS

В каталоге проекта запустите `run.command` двойным щелчком либо в терминале:

```bash
sh run.command
```

Скрипт вызывает `bootstrap.py`, создаёт `.venv` при отсутствии и устанавливает зависимости. Ручная альтернатива — `python3 bootstrap.py`. Для принудительного выбора установленного Python задайте `OPERATOR_PYTHON`.

### Windows 10/11 (64-bit)

В **распакованной** папке проекта запустите `run-windows.bat` (специализированный запуск этого приложения). При необходимости скрипт подбирает Python, создаёт `.venv`, устанавливает зависимости и запускает `main.py`; могут потребоваться интернет и время на установку.

Альтернатива: `run-python-project.bat` — универсальный запускатель Python-проектов с определением точки входа. Если предложено несколько вариантов, для этого приложения выбирайте `main.py`.

**Важно:** запускатели содержат исполняемый код и при необходимости скачивают Python с проверкой SHA-256; используйте только доверенную версию исходников. Реальные проверки GUI и установочных сценариев на Windows ещё нужно завершить. [Устройство и ограничения универсального запускателя](docs/universal-launcher.md).

### Linux / любой поддерживаемый Python (ручной запуск)

Из корня репозитория:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python main.py
```

На Windows ручное окружение активируется командой `.venv\Scripts\activate` (CMD) или `.venv\Scripts\Activate.ps1` (PowerShell). Если система не может загрузить Qt-плагин, проверьте установку PySide6 и системные библиотеки Qt для своей ОС.

Альтернативная точка входа — `python -m operator_stub`. ROS 2 для локального прототипа не требуется.

## Как пользоваться

1. Выберите платформу слева. **На карте отображается выбранная платформа**; её маршрут и состояние независимы от других.
2. Управляйте кнопками или клавишами **W/A/S/D** (доступны также Ц/Ф/Ы/В) — только в режиме учебной симуляции. **Пробел/Esc** — программный STOP.
3. Добавляйте точки на карте, запускайте, приостанавливайте и продолжайте маршрут в режиме миссии.
4. В разделе «Датчики» загружайте тестовые записи из [`examples/`](examples/): `lidar-room.txt`, `sonar-route.txt`, `mixed-route.txt`.
5. Используйте «Телеметрия»/«События» для просмотра текущих данных. Значения `0`, «нет данных», «offline» и «устарело» различаются.

**Подробности:** [динамика трёх платформ, карты, клавиатура, TXT, предупреждения, настройки](docs/PROTOTYPE_GUIDE.md) · [формат датчиков](docs/sensor-format.md) · [модели движения](docs/model-notes.md).

## Архитектура

**Реализовано в desktop 0.4:**

```text
Локальные Mock-платформы / TXT-записи
             │
             ▼
Сервис симуляции и модель состояния (operator_stub/)
             │
             ▼
PySide6 UI: список, карта, телеметрия, миссии, датчики
```

**Целевая архитектура (план, не текущая реализация `main`):**

```text
Mock-платформы / Gazebo / ROS 2 / реальные аппараты
                       │
                       ▼
               PlatformAdapter
                       │ единый контракт
                       ▼
             FastAPI / PostgreSQL
              REST + WebSocket
                       │
             ┌─────────┴───────────┐
             ▼                     ▼
      Карта / телеметрия      Команды / миссии
```

Для реальных аппаратов необходимо отдельно согласовать единицы команд, координаты, подтверждения, watchdog и safety. Нормированное управление локальным прототипом не является готовым протоколом физического контроллера.

## План разработки

Работа четырёх направлений ведётся параллельно по согласованным контрактам. Подробные задачи и критерии готовности — [GitHub Issues](https://github.com/Hazernit/operator-complex-python/issues).

| Направление | Ветка | Ближайшая цель |
| --- | --- | --- |
| Backend и контракты | [`feature/backend`](https://github.com/Hazernit/operator-complex-python/tree/feature/backend) | VehicleTelemetry/VehicleCommand/Mission/MissionEvent, FastAPI, WebSocket, БД |
| Адаптеры и симуляторы | [`feature/adapters`](https://github.com/Hazernit/operator-complex-python/tree/feature/adapters) | 3 mock-процесса, затем UGV+LiDAR/odometry/safety в Gazebo |
| Визуализация | [`feature/dashboard`](https://github.com/Hazernit/operator-complex-python/tree/feature/dashboard) | Все 3 платформы одновременно, REST/WebSocket/live-данные |
| Миссии и интеграция | [`feature/missions`](https://github.com/Hazernit/operator-complex-python/tree/feature/missions) | Waypoints, статусы, события, нормальные и аварийные сценарии |

Этапы: **контракты → независимая разработка → три источника на карте → обратный канал команд → сквозные миссии → реальные платформы**. Выполнение любого этапа нужно подтверждать тестами и демонстрацией, а не только наличием файла.

## Версии и история

| Ссылка | Содержание | Назначение |
| --- | --- | --- |
| [`main`](https://github.com/Hazernit/operator-complex-python/tree/main) | Новый UI 0.4 + запускатели из 0.3 | Актуальная разработка |
| [`version/v0.3`](https://github.com/Hazernit/operator-complex-python/tree/version/v0.3) · [`snapshot/v0.3`](https://github.com/Hazernit/operator-complex-python/tree/snapshot/v0.3) | Предыдущий прототип | Историческая версия |
| [`version/v0.4-new-interface`](https://github.com/Hazernit/operator-complex-python/tree/version/v0.4-new-interface) · [`snapshot/v0.4-new-interface`](https://github.com/Hazernit/operator-complex-python/tree/snapshot/v0.4-new-interface) | Новый UI до объединения запускателей | Зафиксированный снимок |

`version/*` предназначены для просмотра/сравнения. Их **не нужно сливать обратно в `main`**. `snapshot/*` — Git-теги, **не GitHub Releases**. Работа команды идёт через Pull Requests в защищённую `main`.

## Тестирование и качество

Из корня проекта, после установки зависимостей:

```bash
python -m unittest discover -s tests -v
python main.py --smoke-test
```

Проверка скриншотов на системе с работающим Qt: `python scripts/capture_workspace.py` (создаёт локальные файлы `output/screenshots/`, которые не коммитятся автоматически).

Автоматическая проверка GitHub Actions: [Python tests](https://github.com/Hazernit/operator-complex-python/actions/workflows/tests.yml). Её статус нужно читать вместе с **количеством пропущенных тестов**: первоначальный зелёный запуск после переноса запускателей имел **202 теста, 76 skipped**. Работа над строгими CI-проверками ведётся отдельно; подробности и текущая проверка — в [плане улучшений](docs/IMPROVEMENT_BACKLOG.md) и [отчёте проверок](docs/ui-validation.md).

## Документы и работа над проектом

- [CONTRIBUTING.md](CONTRIBUTING.md) — ветки, PR, правила безопасной командной работы.
- [GITHUB_SETUP.md](GITHUB_SETUP.md) — доступ участников и защита `main` (репозиторий **уже создан**).
- [docs/PROTOTYPE_GUIDE.md](docs/PROTOTYPE_GUIDE.md) — техническое руководство по интерфейсу, карте, датчикам и динамике.
- [docs/design-system.md](docs/design-system.md) · [docs/ui-audit.md](docs/ui-audit.md) · [docs/ui-validation.md](docs/ui-validation.md) — интерфейс и доказательства проверок.
- [docs/universal-launcher.md](docs/universal-launcher.md) — Windows-запускатели и ограничения.
- [docs/REPOSITORY_AUDIT_PLAYBOOK.md](docs/REPOSITORY_AUDIT_PLAYBOOK.md) — постоянный стандарт глубокого аудита.
- [docs/IMPROVEMENT_BACKLOG.md](docs/IMPROVEMENT_BACKLOG.md) — незавершённые и подтверждённые улучшения.

Не коммитьте виртуальные окружения, секреты, реальные идентификаторы/данные оборудования и приватные SSH-ключи. Для отчёта об ошибке указывайте шаги воспроизведения, ожидаемое/фактическое поведение и ОС/Python/Qt.