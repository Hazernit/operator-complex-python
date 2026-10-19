"""Operator scenarios for the redesigned native workspace, without hardware."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

try:
    import PySide6
    from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QPoint, QRect, Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QDialogButtonBox, QListWidget
except ImportError:
    QT_AVAILABLE = False
else:
    QT_AVAILABLE = True
    from operator_stub.models import Point
    from operator_stub.ui import OperatorWindow


@unittest.skipUnless(QT_AVAILABLE, 'Для проверок GUI нужен PySide6-Essentials')
class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plugins = Path(PySide6.__file__).parent / 'Qt' / 'plugins'
        if plugins.is_dir():
            QCoreApplication.addLibraryPath(str(plugins))
        cls.app = QApplication.instance() or QApplication(['operator-workspace-tests'])

    def setUp(self):
        self.window = OperatorWindow()
        self.window.timer.stop()
        self.window.set_reduced_motion(True)
        self.window.resize(1280, 800)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def visible_ids(self, window=None):
        window = window or self.window
        return [window.platform_list.item(row).data(Qt.ItemDataRole.UserRole)
                for row in range(window.platform_list.count())
                if not window.platform_list.item(row).isHidden()]

    def wait_for_import(self):
        deadline = time.monotonic() + 10
        while self.window.recording_loader.is_loading and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(1)
        self.app.processEvents()
        self.assertFalse(self.window.recording_loader.is_loading, 'Импорт не завершился вовремя')

    def test_search_preserves_selected_context_and_each_route(self):
        window = self.window
        selected = window.selected_id
        routes = {}
        for index, platform_id in enumerate(window.service.platforms):
            routes[platform_id] = [Point(12 + index, 14), Point(18 + index, 15)]
            window.service.set_route(platform_id, routes[platform_id])
        window._refresh()
        other = next(pid for pid in routes if pid != selected)
        window.platform_search.setText(other.upper())
        self.app.processEvents()
        self.assertEqual(self.visible_ids(), [other])
        self.assertEqual(window.selected_id, selected)
        self.assertEqual(window.map.selected_id, selected)
        self.assertIn(window.state.info.name.replace(' — заглушка', ''), window.context_title.text())
        window.platform_search.setText('no such platform / не существует')
        self.assertEqual(self.visible_ids(), [])
        self.assertTrue(window.search_empty.isVisible())
        self.assertEqual(window.selected_id, selected)
        window.platform_search.clear()
        self.assertFalse(window.search_empty.isVisible())
        self.assertEqual(set(self.visible_ids()), set(routes))
        for platform_id, route in routes.items():
            self.assertEqual(window.service.platforms[platform_id].route, route)

    def test_typing_search_never_drives_and_releases_previous_hold(self):
        window = self.window
        window.platform_search.clearFocus()
        window.telemetry.setFocus()
        QTest.keyPress(window.telemetry, Qt.Key.Key_W)
        self.assertGreater(window.state.desired_forward, 0)
        window.platform_search.setFocus()
        self.app.processEvents()
        self.assertEqual(window.state.desired_forward, 0)
        QTest.keyClicks(window.platform_search, 'wasd')
        self.assertEqual(window.platform_search.text(), 'wasd')
        self.assertEqual((window.state.desired_forward, window.state.desired_turn), (0, 0))
        QTest.keyRelease(window.platform_search, Qt.Key.Key_W)
        self.assertFalse(window._keys)

    def test_view_buttons_expose_the_requested_data_and_keep_mission(self):
        window = self.window
        platform_id = window.selected_id
        route = [Point(window.state.pose.x + 4, window.state.pose.y)]
        window.service.set_route(platform_id, route)
        window.service.start_mission(platform_id)
        window._refresh()
        pages = {'telemetry': window.telemetry, 'sensors': window.sensor_page,
                 'events': window.log_page, 'camera': window.camera_page}
        for mode in ('sensors', 'telemetry', 'events', 'camera', 'map', 'sensors', 'map'):
            with self.subTest(mode=mode):
                QTest.mouseClick(window.view_buttons[mode], Qt.MouseButton.LeftButton)
                self.app.processEvents()
                self.assertEqual(window._workspace_mode, mode)
                self.assertEqual(window.map_page.isVisible(), mode in ('map', 'sensors'))
                self.assertEqual(window.tabs.isVisible(), mode != 'map')
                if mode != 'map':
                    self.assertIs(window.tabs.currentWidget(), pages[mode])
                    self.assertTrue(pages[mode].isVisible())
                self.assertEqual([key for key, button in window.view_buttons.items() if button.isChecked()], [mode])
                self.assertEqual(window.selected_id, platform_id)
                self.assertEqual(window.state.route, route)
                self.assertEqual(window.state.mission_status, 'RUNNING')

    def test_details_and_direct_sensor_selection_reveal_correct_surface(self):
        window = self.window
        for page in (window.warning_table, window.profile_details, window.integration_page):
            window._show_details(page)
            self.app.processEvents()
            self.assertIs(window.tabs.currentWidget(), page)
            self.assertTrue(page.isVisible())
            self.assertFalse(window.map_page.isVisible())
            self.assertFalse(any(button.isChecked() for button in window.view_buttons.values()))
        window.tabs.setCurrentWidget(window.sensor_page)
        self.app.processEvents()
        self.assertTrue(window.map_page.isVisible())
        self.assertTrue(window.sensor_page.isVisible())
        self.assertTrue(window.view_buttons['sensors'].isChecked())

    def test_stop_remains_visible_and_usable_at_required_sizes_and_views(self):
        window = self.window
        for size in ((1280, 800), (1440, 900), (1920, 1080)):
            window.resize(*size)
            self.app.processEvents()
            self.assertEqual((window.width(), window.height()), size)
            for mode in window.view_buttons:
                with self.subTest(size=size, mode=mode):
                    window._set_workspace(mode)
                    self.app.processEvents()
                    stop = window.stop_button
                    self.assertTrue(stop.isVisible())
                    self.assertTrue(stop.isEnabled())
                    rectangle = QRect(stop.mapTo(window, QPoint()), stop.size())
                    self.assertTrue(window.rect().contains(rectangle), str(rectangle))
                    self.assertEqual(stop.visibleRegion().boundingRect(), stop.rect())
                    window._begin_manual((1, 0))
                    self.assertGreater(window.state.desired_forward, 0)
                    QTest.mouseClick(stop, Qt.MouseButton.LeftButton)
                    self.assertEqual((window.state.desired_forward, window.state.desired_turn), (0, 0))
                    self.assertEqual(window.state.speed, 0)

    def test_large_fleet_scrolls_to_and_selects_every_platform(self):
        source = Path(__file__).resolve().parents[1] / 'config' / 'demo_platforms.json'
        config = json.loads(source.read_text(encoding='utf-8'))
        templates = config['platforms']
        fleet = []
        for index in range(15):
            spec = deepcopy(templates[index % len(templates)])
            spec['id'] = f'fleet-{index:02}'
            spec['name'] = f'Платформа {index:02}'
            fleet.append(spec)
        config['platforms'] = fleet
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fleet.json'
            path.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
            large = OperatorWindow(path)
            try:
                large.timer.stop()
                large.set_reduced_motion(True)
                large.resize(1280, 800)
                large.show()
                self.app.processEvents()
                self.assertEqual(large.platform_list.count(), 15)
                self.assertEqual(large.fleet_count.text(), '15')
                self.assertGreater(large.platform_list.verticalScrollBar().maximum(), 0)
                for row in (0, 7, 14):
                    item = large.platform_list.item(row)
                    large.platform_list.scrollToItem(item, QListWidget.ScrollHint.PositionAtCenter)
                    self.app.processEvents()
                    rectangle = large.platform_list.visualItemRect(item)
                    self.assertTrue(large.platform_list.viewport().rect().contains(rectangle.center()))
                    QTest.mouseClick(large.platform_list.viewport(), Qt.MouseButton.LeftButton, pos=rectangle.center())
                    self.assertEqual(large.selected_id, f'fleet-{row:02}')
                    self.assertEqual(large.map.selected_id, f'fleet-{row:02}')
                large.platform_search.setText('fleet-14')
                self.assertEqual(self.visible_ids(large), ['fleet-14'])
                large.platform_search.clear()
                self.assertEqual(len(self.visible_ids(large)), 15)
            finally:
                large.close()
                self.app.processEvents()

    def test_command_result_appears_after_success_and_rejection_keeps_state(self):
        window = self.window
        previous = window.command_status.text()
        original = window.service.set_route
        route = [Point(10, 10)]

        def apply_route(platform_id, points):
            self.assertEqual(window.command_status.text(), previous)
            original(platform_id, points)

        with patch.object(window.service, 'set_route', side_effect=apply_route) as callback:
            self.assertTrue(window._call('set_route', route))
        callback.assert_called_once_with(window.selected_id, route)
        self.assertEqual(window.state.route, route)
        self.assertIn('Принято локальной моделью', window.command_status.text())
        self.assertIn('Маршрут', window.command_status.text())
        self.assertFalse(window._call('set_route', [Point(-1, 10)]))
        self.assertEqual(window.state.route, route)
        self.assertIn('Отклонено', window.command_status.text())
        self.assertIn('внутри поля', window.command_status.text())
        self.assertNotIn('Принято', window.command_status.text())
        self.assertIn('внутри поля', window.statusBar().currentMessage())

    def test_command_feedback_belongs_to_selected_platform(self):
        window = self.window
        first = window.selected_id
        second = next(pid for pid in window.service.platforms if pid != first)
        self.assertTrue(window._call('set_route', [Point(10, 10)]))
        first_result = window.command_status.text()
        window._select_platform(second)
        self.assertEqual(window.command_status.text(), 'Ожидание команды')
        self.assertFalse(window._call('start_mission'))
        self.assertIn('Отклонено', window.command_status.text())
        window._select_platform(first)
        self.assertEqual(window.command_status.text(), first_result)

    def test_reduced_motion_stops_transition_without_changing_data(self):
        window = self.window
        pose = deepcopy(window.state.pose)
        window.set_reduced_motion(False)
        window._set_workspace('events')
        self.assertEqual(window._fade.state(), QAbstractAnimation.State.Running)
        window.set_reduced_motion(True)
        self.assertEqual(window._fade.state(), QAbstractAnimation.State.Stopped)
        self.assertEqual(window._fade_effect.opacity(), 1)
        window._set_workspace('map')
        self.assertEqual(window._fade.state(), QAbstractAnimation.State.Stopped)
        self.assertEqual(window._fade_effect.opacity(), 1)
        self.assertEqual(window.state.pose, pose)

    def test_settings_cancel_preserves_motion_preference_and_accept_applies_it(self):
        window = self.window
        for accept in (False, True):
            def choose(accept=accept):
                dialog = next(child for child in window.findChildren(QDialog) if child.isVisible())
                checkbox = dialog.findChild(QCheckBox)
                checkbox.setChecked(False)
                buttons = dialog.findChild(QDialogButtonBox)
                role = QDialogButtonBox.StandardButton.Ok if accept else QDialogButtonBox.StandardButton.Cancel
                QTest.mouseClick(buttons.button(role), Qt.MouseButton.LeftButton)
            QTimer.singleShot(0, choose)
            window._open_settings()
            self.assertEqual(window._reduced_motion, not accept)

    def test_replacing_recording_reveals_playback_and_never_shows_live_speed_history(self):
        window = self.window
        examples = Path(__file__).resolve().parents[1] / 'examples'
        window._speed_history[window.selected_id].extend((1.2, 2.4, 1.8))
        window._refresh()
        self.assertEqual(list(window.speed_trace.samples), [1.2, 2.4, 1.8])
        window.load_sensor_file(examples / 'lidar-room.txt')
        window._set_workspace('map')
        self.assertFalse(window.tabs.isVisible())
        window.load_sensor_file(examples / 'sonar-route.txt')
        self.app.processEvents()
        self.assertEqual(window._workspace_mode, 'sensors')
        self.assertTrue(window.sensor_page.isVisible())
        self.assertTrue(window.map_page.isVisible())
        self.assertTrue(window.play_button.isVisible())
        self.assertEqual(list(window.speed_trace.samples), [])
        window._leave_replay()
        self.assertEqual(list(window.speed_trace.samples), [1.2, 2.4, 1.8])

    def test_close_releases_keys_stops_timer_and_disconnects_fleet(self):
        window = self.window
        other = next(pid for pid in window.service.platforms if pid != window.selected_id)
        source = window.service.platforms[other]
        window.service.set_route(other, [Point(source.pose.x + 2, source.pose.y)])
        window.service.start_mission(other)
        window.setFocus()
        self.app.processEvents()
        QTest.keyPress(window, Qt.Key.Key_W)
        self.assertGreater(window.state.desired_forward, 0)
        window.timer.start()
        window.close()
        self.app.processEvents()
        self.assertFalse(window.timer.isActive())
        self.assertFalse(window._keys)
        self.assertIsNone(window._manual)
        for state in window.service.platforms.values():
            self.assertFalse(state.connected)
            self.assertEqual((state.desired_forward, state.desired_turn, state.speed), (0, 0, 0))
            self.assertNotEqual(state.mission_status, 'RUNNING')

    def test_async_import_attaches_to_original_platform_after_selection_changes(self):
        window = self.window
        original = window.selected_id
        other = next(pid for pid in window.service.platforms if pid != original)
        example = Path(__file__).resolve().parents[1] / 'examples' / 'lidar-room.txt'
        window._open_sensor_file(example)
        self.assertIn(original, window._pending_imports)
        self.assertNotIn(original, window._replays)
        window._select_platform(other)
        window._set_workspace('telemetry')
        other_pose = deepcopy(window.state.pose)
        self.wait_for_import()
        self.assertEqual(window.selected_id, other)
        self.assertEqual(window.state.pose, other_pose)
        self.assertEqual(window._workspace_mode, 'telemetry')
        self.assertEqual(window.map.selected_id, other)
        self.assertIn(original, window._replays)
        self.assertNotIn(other, window._replays)
        self.assertTrue(window.direction_buttons[0].isEnabled())
        window._select_platform(original)
        self.assertEqual(window.metric_values['battery'].text(), 'Нет в TXT')
        self.assertFalse(window.direction_buttons[0].isEnabled())
        self.assertTrue(window.play_button.isEnabled())

    def test_return_to_simulation_and_reset_cancel_pending_import(self):
        window = self.window
        example = Path(__file__).resolve().parents[1] / 'examples' / 'mixed-route.txt'
        for cancel in (window._leave_replay, window._reset):
            with self.subTest(action=cancel.__name__):
                window._set_workspace('sensors')
                window._open_sensor_file(example)
                self.assertIn(window.selected_id, window._pending_imports)
                cancel()
                self.assertNotIn(window.selected_id, window._pending_imports)
                self.wait_for_import()
                self.assertNotIn(window.selected_id, window._replays)
                self.assertTrue(window.direction_buttons[0].isEnabled())
                self.assertFalse(window.play_button.isEnabled())
                self.assertEqual(window.map.bounds, (0, 100, 0, 70))

    def test_async_invalid_file_preserves_live_or_recorded_source(self):
        window = self.window
        example = Path(__file__).resolve().parents[1] / 'examples' / 'sonar-route.txt'
        with tempfile.TemporaryDirectory() as directory:
            invalid = Path(directory) / 'invalid.txt'
            invalid.write_text('time_s,type,x_m,y_m,heading_deg,angle_deg,range_m\n0,lidar,,,,0,5\n', encoding='utf-8')
            for recording in (False, True):
                with self.subTest(recording=recording):
                    if recording:
                        window.load_sensor_file(example)
                        previous = window._replays[window.selected_id]
                        previous.seek(previous.times[0] + 2)
                        previous.playing = True
                        window._refresh()
                    else:
                        previous = None
                    pose = deepcopy(window.state.pose)
                    clouds = deepcopy(window.map._clouds)
                    with patch('operator_stub.ui.QMessageBox.warning') as warning:
                        window._open_sensor_file(invalid)
                        self.wait_for_import()
                    warning.assert_called_once()
                    self.assertIs(window._replays.get(window.selected_id), previous)
                    self.assertEqual(window.state.pose, pose)
                    self.assertEqual(window.map._clouds, clouds)
                    self.assertIn('Ошибка TXT', window.statusBar().currentMessage())
                    if previous:
                        self.assertEqual(previous.time_s, previous.times[0] + 2)
                        self.assertTrue(previous.playing)

    def test_stale_telemetry_blocks_motion_controls_and_keeps_stop_available(self):
        window = self.window
        state = window.state
        window.service.set_route(window.selected_id, [Point(state.pose.x + 5, state.pose.y)])
        window._begin_manual((1, 0))
        window.service.tick(.1)
        self.assertGreater(state.speed, 0)
        state.telemetry_age_s = 3
        window._refresh()
        self.assertEqual((state.desired_forward, state.desired_turn), (0, 0))
        self.assertFalse(window.keyboard_checkbox.isEnabled())
        self.assertTrue(all(not control.isEnabled() for control in window.direction_buttons))
        self.assertFalse(window.start_button.isEnabled())
        window._begin_manual((1, 0))
        self.assertEqual(state.desired_forward, 0)
        QTest.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
        self.assertNotEqual(state.mission_status, 'RUNNING')
        self.assertIn('устарели', window.metric_values['connection'].text())
        self.assertTrue(window.stop_button.isEnabled())
        self.assertTrue(window.stop_button.isVisible())
        QTest.mouseClick(window.stop_button, Qt.MouseButton.LeftButton)
        self.assertEqual((state.speed, state.desired_forward, state.desired_turn), (0, 0, 0))


if __name__ == '__main__':
    unittest.main()
