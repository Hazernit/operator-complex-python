"""Read-only recording UI: atomic import, seeking and platform isolation."""

from __future__ import annotations

import math
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

try:
    import PySide6
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:
    QT_AVAILABLE = False
else:
    QT_AVAILABLE = True
    from operator_stub.ui import OperatorWindow

from operator_stub.models import Point
from operator_stub.sensor_data import project_reading
from operator_stub.service import DEFAULT_CONFIG


@unittest.skipUnless(QT_AVAILABLE, "Для проверок GUI нужен PySide6-Essentials")
class SensorUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plugins = Path(PySide6.__file__).parent / "Qt" / "plugins"
        if plugins.is_dir():
            QCoreApplication.addLibraryPath(str(plugins))
        cls.app = QApplication.instance() or QApplication(["operator-recording-ui-tests"])
        cls.examples = Path(__file__).resolve().parents[1] / "examples"

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.recording = Path(self.folder.name) / "localized-scan.txt"
        self.recording.write_text(
            "time_s,type,x_m,y_m,heading_deg,angle_deg,range_m\n"
            "10,pose,10,10,0,,\n10,lidar,,,,0,5\n"
            "12,pose,20,10,0,,\n12,lidar,,,,0,5\n"
            "14,pose,30,10,0,,\n14,lidar,,,,0,5\n",
            encoding="utf-8",
        )
        self.invalid = Path(self.folder.name) / "bad-sensors.txt"
        self.invalid.write_text("time_s,type\n0,unknown\n", encoding="utf-8")
        self.window = OperatorWindow()
        self.window.timer.stop()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def points(self, platform_id=None):
        platform_id = platform_id or self.window.selected_id
        return tuple(self.window.map._clouds.get(platform_id, {}).values())

    def deterministic_tick(self, dt=0.1):
        next_time = self.window._last_tick + dt
        with patch("operator_stub.ui.time.monotonic", return_value=next_time):
            self.window._tick()

    def test_all_examples_load_and_display_measured_values_only(self):
        window = self.window
        for filename in ("lidar-room.txt", "sonar-route.txt", "mixed-route.txt"):
            with self.subTest(filename=filename):
                self.assertTrue(window.load_sensor_file(self.examples / filename))
                player = window._replays[window.selected_id]
                display = window._display_state()
                self.assertEqual(display.fields, {})
                self.assertEqual(display.mode, "Запись датчиков")
                self.assertIsNone(display.true_pose)
                self.assertEqual((display.pose.x, display.pose.y),
                                 (player.frame.pose.x, player.frame.pose.y))
                self.assertEqual(display.sensor_frame.readings, player.frame.readings)
                self.assertEqual(window.map.sensor_frame, display.sensor_frame)
                self.assertEqual(window.sensor_table.rowCount(), len(player.frame.readings))
                self.assertIn(filename, window.sensor_source.text())
                for key in ("battery", "link"):
                    self.assertEqual(window.metric_values[key].text(), "Нет в TXT")
                    self.assertFalse(window.metric_bars[key].isEnabled())
                self.assertEqual(window.metric_values["mode"].text(), "Запись датчиков")
                self.assertEqual(window.tabs.currentWidget(), window.sensor_page)

    def test_seek_uses_recording_absolute_time_and_localized_pose(self):
        window = self.window
        window.load_sensor_file(self.recording)
        window._seek_recording(500)
        player = window._replays[window.selected_id]
        self.assertEqual(player.time_s, 12)
        display = window._display_state()
        self.assertEqual((display.pose.x, display.pose.y), (20, 10))
        self.assertEqual(window.playhead.value(), 500)
        self.assertIn("2.0 / 4.0", window.play_time.text())
        window._seek_recording(250)
        self.assertEqual(player.time_s, 11)
        self.assertEqual(window._display_state().pose.x, 15)
        frame = window.map.sensor_frame
        self.assertEqual(frame.reading_time_s, 10)
        self.assertEqual(project_reading(frame, frame.readings[0]), (10, 10, 15, 10))

    def test_seek_backwards_rebuilds_cloud_without_future_measurements(self):
        window = self.window
        window.load_sensor_file(self.recording)
        window._seek_recording(1000)
        self.assertEqual(self.points(), ((15, 10), (25, 10), (35, 10)))
        window._seek_recording(0)
        self.assertEqual(self.points(), ((15, 10),))
        self.assertEqual(window.map.trails[window.selected_id], [(10, 10)])
        window._seek_recording(500)
        self.assertEqual(self.points(), ((15, 10), (25, 10)))
        self.assertNotIn((35, 10), self.points())

    def test_play_pause_advance_and_replay_from_end(self):
        window = self.window
        window.load_sensor_file(self.recording)
        player = window._replays[window.selected_id]
        self.assertFalse(player.playing)
        window._toggle_playback()
        self.assertTrue(player.playing)
        self.deterministic_tick(0.1)
        self.assertAlmostEqual(player.time_s, 10.1)
        window._toggle_playback()
        self.assertFalse(player.playing)
        self.deterministic_tick(0.1)
        self.assertAlmostEqual(player.time_s, 10.1)
        window._seek_recording(1000)
        window._toggle_playback()
        self.assertTrue(player.playing)
        self.assertEqual(player.time_s, 10)
        self.assertEqual(self.points(), ((15, 10),))

    def test_recording_disables_manual_and_mission_commands(self):
        window = self.window
        window.service.set_route(window.selected_id, [Point(25, 30)])
        window._refresh()
        self.assertTrue(window.start_button.isEnabled())
        window.load_sensor_file(self.recording)
        for control in (*window.direction_buttons, window.keyboard_checkbox,
                        window.start_button, window.pause_button, window.cancel_button,
                        window.clear_button, window.load_route_button, window.save_route_button,
                        window.edit_checkbox, window.connection_button):
            self.assertFalse(control.isEnabled())
        self.assertFalse(window.map.edit_route)
        self.assertFalse(window.map.draw_plan)
        self.assertTrue(window.stop_button.isEnabled())
        with patch.object(window.service, "set_velocity") as manual, \
             patch.object(window.service, "set_route") as route:
            window._begin_manual((1, 0))
            window._send_manual()
            window._add_waypoint(70, 60)
            manual.assert_not_called()
            route.assert_not_called()

    def test_space_escape_and_stop_pause_playback_without_robot_commands(self):
        window = self.window
        window.show()
        window.load_sensor_file(self.recording)
        window.sensor_table.setFocus()
        self.app.processEvents()
        player = window._replays[window.selected_id]
        with patch.object(window.service, "stop") as stop, \
             patch.object(window.service, "set_velocity") as manual:
            for key in (Qt.Key.Key_Space, Qt.Key.Key_Escape):
                with self.subTest(key=key):
                    player.playing = True
                    QTest.keyClick(window.sensor_table, key)
                    self.assertFalse(player.playing)
            player.playing = True
            QTest.mouseClick(window.stop_button, Qt.MouseButton.LeftButton)
            self.assertFalse(player.playing)
            QTest.keyClick(window.sensor_table, Qt.Key.Key_W)
            self.assertFalse(window._keys)
            self.assertIsNone(window._manual)
            stop.assert_not_called()
            manual.assert_not_called()

    def test_switching_platform_preserves_playhead_and_independent_live_motion(self):
        window = self.window
        recorded_id = window.selected_id
        other_id = next(platform_id for platform_id in window.service.platforms if platform_id != recorded_id)
        window.load_sensor_file(self.recording)
        window._seek_recording(500)
        player = window._replays[recorded_id]
        player.playing = True
        live_recorded_pose = (window.state.pose.x, window.state.pose.y)
        window._select_platform(other_id)
        self.assertEqual(window.selected_id, other_id)
        self.assertIs(window._display_state(), window.state)
        self.assertTrue(window.keyboard_checkbox.isEnabled())
        before = (window.state.pose.x, window.state.pose.y)
        window.service.set_velocity(other_id, 1, 0)
        self.deterministic_tick(0.2)
        after = (window.state.pose.x, window.state.pose.y)
        self.assertGreater(math.dist(before, after), 0)
        self.assertEqual(player.time_s, 12)
        window._select_platform(recorded_id)
        self.assertIs(window._replays[recorded_id], player)
        self.assertEqual(player.time_s, 12)
        self.assertEqual(window._display_state().pose.x, 20)
        self.assertEqual((window.state.pose.x, window.state.pose.y), live_recorded_pose)

    def test_two_platforms_keep_independent_recordings(self):
        window = self.window
        first_id = window.selected_id
        second_id = next(platform_id for platform_id in window.service.platforms if platform_id != first_id)
        window.load_sensor_file(self.recording)
        window._seek_recording(500)
        first_player = window._replays[first_id]
        window._select_platform(second_id)
        window.load_sensor_file(self.examples / "sonar-route.txt")
        window._seek_recording(250)
        second_player = window._replays[second_id]
        self.assertEqual(len(window._replays), 2)
        self.assertEqual(first_player.time_s, 12)
        self.assertAlmostEqual(second_player.time_s, 7.5)
        window._select_platform(first_id)
        self.assertIs(window._replays[first_id], first_player)
        self.assertEqual(window.playhead.value(), 500)
        window._select_platform(second_id)
        self.assertIs(window._replays[second_id], second_player)
        self.assertEqual(window.playhead.value(), 250)

    def test_invalid_file_does_not_replace_or_pause_existing_recording(self):
        window = self.window
        window.load_sensor_file(self.recording)
        window._seek_recording(500)
        player = window._replays[window.selected_id]
        player.playing = True
        before_points = self.points()
        before_bounds = window.map.bounds
        before_events = tuple(window.service.events)
        with patch.object(window.service, "stop") as stop:
            with self.assertRaises(ValueError):
                window.load_sensor_file(self.invalid)
            stop.assert_not_called()
        self.assertIs(window._replays[window.selected_id], player)
        self.assertTrue(player.playing)
        self.assertEqual(player.time_s, 12)
        self.assertEqual(self.points(), before_points)
        self.assertEqual(window.map.bounds, before_bounds)
        self.assertEqual(tuple(window.service.events), before_events)

    def test_invalid_file_does_not_change_live_mode(self):
        window = self.window
        window.service.set_velocity(window.selected_id, 0.5, 0)
        window._refresh()
        before_state = window.state.mode, window.state.desired_forward
        before_points = self.points()
        with patch.object(window.service, "stop") as stop:
            with self.assertRaises(ValueError):
                window.load_sensor_file(self.invalid)
            stop.assert_not_called()
        self.assertFalse(window._replays)
        self.assertEqual((window.state.mode, window.state.desired_forward), before_state)
        self.assertEqual(self.points(), before_points)

    def test_leaving_recording_removes_txt_cloud_and_restores_live_controls(self):
        window = self.window
        selected_id = window.selected_id
        window.load_sensor_file(self.recording)
        window._seek_recording(1000)
        self.assertIn((35, 10), self.points())
        live_frame = window.state.sensor_frame
        expected_cloud = {}
        for reading in live_frame.readings:
            if reading.sensor == "lidar" and reading.hit:
                _, _, x, y = project_reading(live_frame, reading)
                expected_cloud[(round(x * 4), round(y * 4))] = (x, y)
        window._leave_replay()
        self.assertNotIn(selected_id, window._replays)
        self.assertIs(window._display_state(), window.state)
        self.assertIs(window.map.sensor_frame, window.state.sensor_frame)
        self.assertEqual(window.map.bounds, (0, 100, 0, 70))
        self.assertEqual(set(self.points()), set(expected_cloud.values()))
        self.assertTrue(all(control.isEnabled() for control in window.direction_buttons))
        self.assertTrue(window.keyboard_checkbox.isEnabled())
        self.assertTrue(window.map.draw_plan)
        self.assertTrue(window.map.edit_route)
        self.assertFalse(window.play_button.isEnabled())
        self.assertFalse(window.return_simulation_button.isEnabled())
        self.assertNotEqual(window.metric_values["battery"].text(), "Нет в TXT")

    def test_recording_hides_simulation_world_and_restores_layer_preference(self):
        window = self.window
        world_control = window.layer_controls["draw_world"]
        world_control.setChecked(True)
        self.assertTrue(window.map.draw_world)
        window.load_sensor_file(self.recording)
        self.assertFalse(window.map.draw_world)
        self.assertFalse(world_control.isEnabled())
        self.assertTrue(world_control.isChecked(), "Сохраняется настройка слоя для симуляции")
        window._seek_recording(500)
        self.assertFalse(window.map.draw_world)
        window._leave_replay()
        self.assertTrue(world_control.isEnabled())
        self.assertTrue(world_control.isChecked())
        self.assertTrue(window.map.draw_world)

    def test_available_recording_is_not_shown_as_disconnected_simulation(self):
        window = self.window
        window.service.disconnect(window.selected_id)
        self.assertFalse(window.state.connected)
        window.load_sensor_file(self.recording)
        self.assertFalse(window.state.connected, "Загрузка файла не подключает адаптер симуляции")
        self.assertTrue(window._display_state().connected)
        self.assertTrue(window.map._visible_platforms()[window.selected_id].connected)
        self.assertEqual(window.metric_values["connection"].text(), "TXT · источник данных из файла")
        self.assertEqual(window.metric_values["mode"].text(), "Запись датчиков")
        self.assertIn("Время записи", window.freshness.text())
        window._leave_replay()
        self.assertFalse(window._display_state().connected)
        self.assertFalse(window.map._visible_platforms()[window.selected_id].connected)
        self.assertFalse(window.keyboard_checkbox.isEnabled())

    def test_saved_simulation_warning_is_labelled_without_false_resolution(self):
        # Configure the source itself: STOP during import refreshes its snapshot.
        config = deepcopy(DEFAULT_CONFIG)
        for platform in config["platforms"]:
            if platform["kind"] == "НРТК":
                next(field for field in platform["telemetry_fields"]
                     if field.get("semantic") == "battery_percent")["value"] = 9
        config_path = Path(self.folder.name) / "low-battery.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        self.window.close()
        self.window = OperatorWindow(config_path)
        self.window.timer.stop()
        window = self.window
        platform_id = window.selected_id
        window._refresh()
        warning_key = (platform_id, "battery_low")
        self.assertIn(warning_key, window._active_alerts)
        original_level = window._active_alerts[warning_key].level
        before_count = len(window.service.events)
        window.load_sensor_file(self.recording)
        warning = window._active_alerts[warning_key]
        prefix = "Сохранённая симуляция (не TXT): "
        self.assertTrue(warning.message.startswith(prefix))
        self.assertEqual(warning.level, original_level)
        selected_messages = [
            window.warning_table.item(row, 2).text()
            for row in range(window.warning_table.rowCount())
            if window.warning_table.item(row, 2).data(Qt.ItemDataRole.UserRole) == platform_id
        ]
        self.assertTrue(selected_messages)
        self.assertTrue(all(message.startswith(prefix) for message in selected_messages))
        new_events = tuple(window.service.events)[before_count:]
        self.assertFalse(any(event.message.startswith("Снято:") for event in new_events))
        self.assertEqual(window.metric_values["battery"].text(), "Нет в TXT")
        window._leave_replay()
        self.assertIn(warning_key, window._active_alerts)
        self.assertFalse(window._active_alerts[warning_key].message.startswith(prefix))
        self.assertEqual(window._active_alerts[warning_key].level, original_level)
        self.assertFalse(any(event.message.startswith("Снято:") for event in tuple(window.service.events)[before_count:]))


if __name__ == "__main__":
    unittest.main()
