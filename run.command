#!/bin/sh
# No login shell: unrelated .zshrc completion settings do not affect startup.
TASK_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
cd "$TASK_DIR" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
    echo 'Не найден python3. Установите Python 3.11 или новее.' >&2
    exit 1
fi
python3 "$TASK_DIR/bootstrap.py" "$@"
TASK_STATUS=$?
if [ "$TASK_STATUS" -ne 0 ] && [ -t 0 ]; then
    printf '\nЗапуск не выполнен. Нажмите Enter, чтобы закрыть окно.'
    read -r TASK_REPLY
fi
exit "$TASK_STATUS"
