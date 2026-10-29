"""Linux display and native Qt checks around the shared bootstrap."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bootstrap


def configure_display(args, environ=None):
    """Respect explicit Qt settings; select a desktop only when one is available."""
    environment = os.environ if environ is None else environ
    platform = environment.get('QT_QPA_PLATFORM', '')
    if any(argument in ('--setup-only', '--help', '-h') for argument in args):
        return platform
    if not platform:
        if '--smoke-test' in args or any(argument == '--screenshot' or argument.startswith('--screenshot=') for argument in args):
            platform = 'offscreen'
        elif environment.get('WAYLAND_DISPLAY') or (
            environment.get('XDG_SESSION_TYPE') == 'wayland' and environment.get('XDG_RUNTIME_DIR')
        ):
            platform = 'wayland'
        elif environment.get('DISPLAY'):
            platform = 'xcb'
        else:
            raise RuntimeError(
                'Не найден графический сеанс Wayland/X11 (WAYLAND_DISPLAY/DISPLAY). '
                'Для проверки без GUI выполните: QT_QPA_PLATFORM=offscreen sh run-linux.sh --smoke-test.'
            )
        environment['QT_QPA_PLATFORM'] = platform
    if platform.split(':', 1)[0] in ('offscreen', 'minimal'):
        print('Headless: Qt работает без видимого GUI.', flush=True)
    return platform


def missing_qt_libraries(executable):
    """Report missing ELF dependencies of the installed wheel, without guessing."""
    if shutil.which('ldd') is None:
        return []
    locate = subprocess.run(
        [str(executable), '-c',
         'import importlib.util,json; s=importlib.util.find_spec("PySide6"); '
         'print(json.dumps(list(s.submodule_search_locations) if s else []))'],
        capture_output=True, text=True, timeout=15,
    )
    if locate.returncode:
        return []
    try:
        directories = json.loads(locate.stdout)
    except ValueError:
        return []
    platform = os.environ.get('QT_QPA_PLATFORM', '').split(';', 1)[0].split(':', 1)[0]
    plugins = {
        'xcb': ('libqxcb.so',),
        'wayland': ('libqwayland.so', 'libqwayland-generic.so', 'libqwayland-egl.so'),
        'offscreen': ('libqoffscreen.so',),
        'minimal': ('libqminimal.so',),
    }.get(platform, ())
    missing = set()
    for directory in directories:
        qt = Path(directory) / 'Qt'
        paths = [qt / 'lib' / name for name in ('libQt6Gui.so.6', 'libQt6Widgets.so.6')]
        paths.extend(qt / 'plugins' / 'platforms' / name for name in plugins)
        for path in paths:
            if not path.is_file():
                continue
            result = subprocess.run(['ldd', str(path)], capture_output=True, text=True, timeout=15)
            missing.update(re.findall(r'^\s*(\S+)\s+=>\s+not found', result.stdout, re.MULTILINE))
    return sorted(missing)


def qt_error_message(executable, details):
    try:
        missing = missing_qt_libraries(executable)
    except (OSError, subprocess.TimeoutExpired):
        missing = []
    message = 'Не удалось запустить Qt/PySide6. '
    if missing:
        message += 'Отсутствуют системные библиотеки: ' + ', '.join(missing) + '. '
        packages = {
            'libxcb-cursor.so.0': 'libxcb-cursor0',
            'libxkbcommon.so.0': 'libxkbcommon0',
            'libxkbcommon-x11.so.0': 'libxkbcommon-x11-0',
            'libEGL.so.1': 'libegl1',
            'libOpenGL.so.0': 'libopengl0',
        }
        hints = sorted({packages[name] for name in missing if name in packages})
        if hints:
            message += 'Пакеты Debian/Ubuntu: ' + ' '.join(hints) + '. '
        message += 'Установите соответствующие пакеты через пакетный менеджер дистрибутива. '
    else:
        message += 'Проверьте доступ к графическому сеансу, QT_QPA_PLATFORM и системные библиотеки Qt. '
    return message + '\n' + details


def check_native_imports(executable):
    """Diagnose installed Qt blocked by system libraries before pip is involved."""
    if not Path(executable).is_file():
        return
    try:
        result = subprocess.run(
            [str(executable), '-c', 'from PySide6 import QtCore, QtGui, QtWidgets'],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        # Bootstrap owns validation of a missing/broken environment.
        return
    details = result.stderr.strip()
    if result.returncode and ('cannot open shared object file' in details or 'undefined symbol' in details):
        raise RuntimeError(qt_error_message(executable, details))


def check_qt(executable):
    """Catch Qt plugin aborts in a child instead of crashing the launcher."""
    code = (
        'import resource; resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); '
        'from pathlib import Path; import PySide6; '
        'from PySide6.QtCore import QCoreApplication; '
        'from PySide6.QtWidgets import QApplication; '
        'QCoreApplication.addLibraryPath(str(Path(PySide6.__file__).parent / "Qt" / "plugins")); '
        'app=QApplication([]); app.processEvents(); '
        'print("Qt platform:", app.platformName())'
    )
    try:
        result = subprocess.run(
            [str(executable), '-c', code], cwd=ROOT,
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError('Qt не ответил за 30 секунд. Проверьте DISPLAY/Wayland и настройки QT_QPA_PLATFORM.') from error
    if result.returncode == 0:
        print(result.stdout.strip(), flush=True)
        return
    raise RuntimeError(qt_error_message(executable, result.stderr.strip() or result.stdout.strip()))


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        selected = bootstrap.find_python()
        if sys.version_info < bootstrap.MINIMUM_PYTHON:
            os.execv(selected, [selected, str(Path(__file__).resolve()), *args])
        configure_display(args)
        executable = ROOT / '.venv' / 'bin' / 'python'
        check_native_imports(executable)
        probe = None if any(argument in ('--setup-only', '--help', '-h') for argument in args) else check_qt
        result = bootstrap.main(args, before_launch=probe)
        if result:
            check_native_imports(executable)
        return result
    except (RuntimeError, OSError) as error:
        print('Ошибка запуска: ' + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
