"""Prepare a local Python 3.11+ environment, then run the app."""

import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
MINIMUM_PYTHON = (3, 11)


def supported_python(executable):
    try:
        result = subprocess.run(
            [str(executable), '-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def find_python():
    override = os.environ.get('OPERATOR_PYTHON')
    if override:
        candidate = shutil.which(override) or override
        if not supported_python(candidate):
            raise RuntimeError('OPERATOR_PYTHON должен указывать на работающий Python 3.11 или новее.')
        return candidate
    candidates = [sys.executable]
    names = ('python3.12', 'python3.13', 'python3.11', 'python3.14', 'python3', 'python')
    candidates.extend(shutil.which(name) for name in names)
    for directory in (Path('/opt/homebrew/bin'), Path('/usr/local/bin')):
        candidates.extend(directory / name for name in names)
    # Optional local runtime supplied by Codex; ordinary Python installations
    # above take priority. No download or global installation is performed here.
    candidates.append(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3')
    seen = set()
    for candidate in candidates:
        if candidate is None or str(candidate) in seen:
            continue
        seen.add(str(candidate))
        if supported_python(candidate):
            return str(candidate)
    raise RuntimeError('Не найден Python 3.11+. Установите Python 3.11 или новее и повторите запуск. Можно указать путь через OPERATOR_PYTHON.')


def supported_qt_version(python_version, qt_version):
    version = tuple(map(int, qt_version.split('.')))
    # This exact release aborts on CPython 3.11 when Qt returns None repeatedly:
    # https://github.com/Hazernit/operator-complex-python/actions/runs/40823655448
    return (6, 8) <= version < (7, 0) and not (
        tuple(python_version[:2]) < (3, 12) and version == (6, 12, 0)
    )


def dependencies_ready(executable):
    code = (
        'import sys; '
        f'sys.path.insert(0, {str(Path(__file__).resolve().parent)!r}); '
        'from bootstrap import supported_qt_version; '
        'import PySide6; from PySide6 import QtCore, QtGui, QtWidgets; '
        'assert supported_qt_version(sys.version_info, PySide6.__version__)'
    )
    try:
        return subprocess.run(
            [str(executable), '-c', code], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=30,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def prepare_environment():
    environment = ROOT / '.venv'
    executable = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if environment.exists():
        if not supported_python(executable):
            raise RuntimeError('Папка .venv уже существует, но её Python не работает или старее 3.11. Переименуйте её в .venv-old и повторите запуск; файлы проекта сохранятся.')
    else:
        python = find_python()
        print(f'Создаю окружение проекта с Python: {python}', flush=True)
        try:
            subprocess.run([python, '-m', 'venv', str(environment)], check=True, cwd=ROOT)
        except subprocess.CalledProcessError as error:
            raise RuntimeError(
                'Не удалось создать .venv. Проверьте модули venv и ensurepip выбранного Python. '
                'В Debian/Ubuntu может потребоваться пакет python3-venv (или python3.11-venv '
                'для соответствующей версии). Установите его через пакетный менеджер и повторите запуск.'
            ) from error
    if not dependencies_ready(executable):
        print('Устанавливаю зависимости проекта. Для первого запуска нужен интернет.', flush=True)
        try:
            subprocess.run(
                [str(executable), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt')],
                check=True, cwd=ROOT,
            )
        except subprocess.CalledProcessError as error:
            raise RuntimeError(
                'Не удалось установить зависимости. Проверьте подключение к интернету '
                f'и доступность pip командой: "{executable}" -m pip --version. '
                'Если pip отсутствует, восстановите его командой -m ensurepip --upgrade '
                'для Python этого окружения и повторите запуск.'
            ) from error
        if not dependencies_ready(executable):
            try:
                details = subprocess.run(
                    [str(executable), '-c', 'from PySide6 import QtCore, QtGui, QtWidgets'],
                    capture_output=True, text=True, timeout=30,
                )
                diagnostic = details.stderr.strip() or details.stdout.strip() or 'Не поддерживается версия PySide6.'
            except (OSError, subprocess.TimeoutExpired) as error:
                diagnostic = f'Не удалось проверить импорт Qt: {error}'
            raise RuntimeError(
                'Зависимости установлены, но Qt не загрузился. '
                'Проверьте системные библиотеки Qt и сообщения ниже:\n'
                + diagnostic
            )
    return executable


def main(argv=None, before_launch=None):
    args = list(sys.argv[1:] if argv is None else argv)
    setup_only = '--setup-only' in args
    if setup_only:
        args.remove('--setup-only')
    try:
        executable = prepare_environment()
        if setup_only:
            print(f'Окружение готово: {executable}', flush=True)
            return 0
        if before_launch is not None:
            before_launch(executable)
        return subprocess.call([str(executable), str(ROOT / 'main.py'), *args], cwd=ROOT)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f'Ошибка запуска: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
