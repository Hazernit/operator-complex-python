#!/bin/sh
# Environment preparation stays in bootstrap.py; this wrapper only finds an entry Python.
TASK_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
cd "$TASK_DIR" || exit 1
if [ -n "${OPERATOR_PYTHON:-}" ]; then
    TASK_PYTHON=$OPERATOR_PYTHON
    if ! command -v "$TASK_PYTHON" >/dev/null 2>&1; then
        printf '%s\n' 'Ошибка запуска: OPERATOR_PYTHON должен указывать на работающий Python 3.11 или новее.' >&2
        exit 1
    fi
else
    TASK_PYTHON=
    for TASK_CANDIDATE in python3 python3.12 python3.13 python3.11 python3.14 python; do
        if command -v "$TASK_CANDIDATE" >/dev/null 2>&1; then
            TASK_PYTHON=$TASK_CANDIDATE
            break
        fi
    done
    if [ -z "$TASK_PYTHON" ]; then
        printf '%s\n' 'Ошибка запуска: не найден python3. Установите Python 3.11 или новее; можно указать путь через OPERATOR_PYTHON.' >&2
        exit 1
    fi
fi
exec "$TASK_PYTHON" "$TASK_DIR/scripts/linux_launcher.py" "$@"
