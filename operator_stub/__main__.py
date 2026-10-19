from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


def main(argv=None):
    parser=argparse.ArgumentParser(description='Python-заглушка единого операторского комплекса. Только локальные тестовые данные.')
    parser.add_argument('--config',type=Path,help='JSON-профили демонстрационных источников')
    parser.add_argument('--screenshot',type=Path,help='Сохранить снимок окна без дисплея и завершить работу')
    parser.add_argument('--smoke-test',action='store_true',help='Проверить интерфейс без дисплея и завершить работу')
    args=parser.parse_args(argv)
    if args.screenshot or args.smoke_test:
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    try:
        import PySide6
        from PySide6.QtCore import QCoreApplication, QTimer
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print('Не найден PySide6. Установите зависимости: python -m pip install -r requirements.txt',file=sys.stderr)
        return 1
    # Resolve wheel plugins directly. Some Qt builds misread a relocated prefix
    # when a project directory contains commas (as this workspace does).
    plugins = Path(PySide6.__file__).parent / 'Qt' / 'plugins'
    if plugins.is_dir():
        QCoreApplication.addLibraryPath(str(plugins))
    from .ui import OperatorWindow
    app=QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName('Operator Stub')
    app.setOrganizationName('Operator Complex')
    try:
        window=OperatorWindow(args.config)
    except (OSError,ValueError,KeyError,TypeError) as error:
        print(f'Ошибка конфигурации: {error}',file=sys.stderr)
        return 2
    window.show()
    result=[0]
    if args.smoke_test or args.screenshot:
        def inspect():
            try:
                from .models import Point
                from PySide6.QtCore import Qt
                from PySide6.QtTest import QTest
                window.timer.stop()
                source_id=window.selected_id
                state=window.state
                x,y=state.pose.x,state.pose.y
                window.service.set_route(source_id,[Point(min(90,x+12),y),Point(min(90,x+12),min(60,y+15)),Point(min(90,x+27),min(60,y+15))])
                window._refresh()
                window.control_tabs.setCurrentIndex(1)
                QTest.mouseClick(window.start_button,Qt.MouseButton.LeftButton)
                assert state.mission_status=='RUNNING'
                window.service.tick(0.2)
                QTest.mouseClick(window.pause_button,Qt.MouseButton.LeftButton)
                assert state.mission_status=='PAUSED'
                QTest.mouseClick(window.pause_button,Qt.MouseButton.LeftButton)
                assert state.mission_status=='RUNNING'
                QTest.mouseClick(window.connection_button,Qt.MouseButton.LeftButton)
                assert not state.connected and state.mission_status=='PAUSED'
                frozen=(state.pose.x,state.pose.y)
                window.service.tick(0.2)
                assert (state.pose.x,state.pose.y)==frozen
                QTest.mouseClick(window.connection_button,Qt.MouseButton.LeftButton)
                assert state.connected and state.mission_status!='RUNNING'
                QTest.mouseClick(window.pause_button,Qt.MouseButton.LeftButton)
                assert state.mission_status=='RUNNING'
                for _ in range(20):
                    window.service.tick(0.1)
                QTest.mouseClick(window.cancel_button,Qt.MouseButton.LeftButton)
                assert state.mission_status=='CANCELLED'
                window.control_tabs.setCurrentIndex(0)
                app.processEvents()
                previous_x=state.pose.x
                QTest.mousePress(window.direction_buttons[0],Qt.MouseButton.LeftButton)
                window.service.tick(0.1)
                assert state.pose.x!=previous_x
                QTest.mouseRelease(window.direction_buttons[0],Qt.MouseButton.LeftButton)
                assert state.desired_forward==0
                window.keyboard_checkbox.setChecked(True)
                QTest.keyPress(window.telemetry,Qt.Key.Key_W)
                assert state.desired_forward>0
                QTest.keyRelease(window.telemetry,Qt.Key.Key_W)
                assert state.desired_forward==0
                window.keyboard_checkbox.setChecked(False)
                window.control_tabs.setCurrentIndex(1)
                window.service.start_mission(source_id)
                for _ in range(20):
                    window.service.tick(0.1)
                window._refresh()
                app.processEvents()
                if args.screenshot:
                    args.screenshot.parent.mkdir(parents=True,exist_ok=True)
                    assert window.grab().save(str(args.screenshot))
                print('UI smoke test passed: route, pause/resume, disconnect/reconnect, held controls and focused-widget keyboard; no hardware access.')
            except Exception as error:
                import traceback
                traceback.print_exc()
                result[0]=1
            finally:
                window.close()
                app.quit()
        QTimer.singleShot(350,inspect)
    app.exec()
    return result[0]


if __name__=='__main__':
    raise SystemExit(main())
