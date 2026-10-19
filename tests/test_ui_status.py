"""Регрессии операторских статусов в реальных Qt-виджетах без оборудования."""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

try:
    import PySide6
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:
    QT_AVAILABLE = False
else:
    QT_AVAILABLE = True
    from operator_stub.ui import OperatorWindow

from operator_stub.models import Point
from operator_stub.presentation import profile_for


@unittest.skipUnless(QT_AVAILABLE, "Для проверок GUI нужен PySide6-Essentials")
class UiStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        plugins = Path(PySide6.__file__).parent / "Qt" / "plugins"
        if plugins.is_dir():
            QCoreApplication.addLibraryPath(str(plugins))
        cls.app = QApplication.instance() or QApplication(["operator-status-tests"])

    def setUp(self) -> None:
        self.window = OperatorWindow()
        self.window.timer.stop()

    def tearDown(self) -> None:
        self.window.close()
        self.app.processEvents()

    @staticmethod
    def set_metric(state, semantic: str, value) -> None:
        next(field for field in state.fields.values() if field.semantic == semantic).value = value

    def test_unknown_zero_and_disconnected_values_are_distinct(self) -> None:
        window = self.window
        state = window.service.platforms[window.selected_id]
        self.set_metric(state, "battery_percent", None)
        self.set_metric(state, "link_quality_percent", None)
        window._refresh()
        self.assertEqual(window.metric_values["battery"].text(), "Нет данных")
        self.assertEqual(window.metric_values["link"].text(), "Нет данных")

        self.set_metric(state, "battery_percent", 0)
        self.set_metric(state, "link_quality_percent", 0)
        window._refresh()
        self.assertIn("0%", window.metric_values["battery"].text().replace(" ", ""))
        self.assertIn("0%", window.metric_values["link"].text().replace(" ", ""))
        self.assertTrue(window.metric_bars["battery"].isEnabled())

        self.set_metric(state, "battery_percent", 42)
        self.set_metric(state, "link_quality_percent", 63)
        window._refresh()
        self.assertEqual(window.metric_bars["battery"].value(), 42)
        self.assertEqual(window.metric_bars["link"].value(), 63)
        window.service.disconnect(state.info.id)
        window._refresh()
        for key in ("battery", "link"):
            self.assertEqual(window.metric_values[key].text(), "—")
            self.assertFalse(window.metric_bars[key].isEnabled())
        self.assertIn("Отключ", window.metric_values["mode"].text())

    def test_fleet_warning_remains_visible_when_another_platform_is_selected(self) -> None:
        window = self.window
        affected_id = next(platform_id for platform_id in window.service.platforms if platform_id != window.selected_id)
        affected = window.service.platforms[affected_id]
        self.set_metric(affected, "battery_percent", 9)
        window._refresh()
        rows = window.warning_table.rowCount()
        self.assertGreater(rows, 0)
        matching = [
            row for row in range(rows)
            if any(window.warning_table.item(row, column).data(Qt.ItemDataRole.UserRole) == affected_id for column in range(3))
        ]
        self.assertTrue(matching, "Предупреждение другой платформы должно быть видно в общем списке")
        self.assertTrue(any("заряд" in window.warning_table.item(row, 2).text().lower() for row in matching))
        self.assertTrue(window.alert_summary.text())
        count = len(window.service.events)
        window._refresh()
        self.assertEqual(len(window.service.events), count, "Неизменное предупреждение не должно засорять журнал")
        self.set_metric(affected, "battery_percent", 8)
        window._refresh()
        self.assertEqual(len(window.service.events), count, "Колебание значения внутри уровня не создаёт новое событие")
        self.set_metric(affected, "battery_percent", 40)
        window._refresh()
        self.assertGreater(len(window.service.events), count, "Восстановление состояния должно попасть в журнал")

    def test_profile_changes_preserve_shared_controls_and_show_differences(self) -> None:
        window = self.window
        control_ids = tuple(id(control) for control in window.direction_buttons)
        for platform_id, state in window.service.platforms.items():
            with self.subTest(kind=state.info.kind):
                window._select_platform(platform_id)
                profile = profile_for(state.info.kind)
                self.assertIn(profile.title, window.profile_label.text())
                self.assertIn(profile.environment, window.profile_label.text())
                self.assertIn(profile.limitation, window.profile_details.text())
                self.assertEqual(tuple(id(control) for control in window.direction_buttons), control_ids)
                self.assertTrue(all(control.isEnabled() for control in window.direction_buttons))
                self.assertTrue(window.metric_values["mode"].text())

    def test_sidebar_switches_single_platform_map_and_preserves_individual_routes(self) -> None:
        window = self.window
        expected = {}
        for platform_id, state in window.service.platforms.items():
            route = [Point(state.pose.x + 5, state.pose.y)]
            window.service.set_route(platform_id, route)
            trail = [(state.pose.x - 1, state.pose.y), (state.pose.x, state.pose.y)]
            window.trails[platform_id].extend(trail)
            expected[platform_id] = (route, trail, state.pose.x, state.pose.y)
        window.show()
        self.app.processEvents()
        for _ in range(2):
            for row in range(window.platform_list.count()):
                item = window.platform_list.item(row)
                platform_id = item.data(Qt.ItemDataRole.UserRole)
                window.platform_list.scrollToItem(item)
                position = window.platform_list.visualItemRect(item).center()
                QTest.mouseClick(window.platform_list.viewport(), Qt.MouseButton.LeftButton, pos=position)
                self.assertEqual(window.selected_id, platform_id)
                self.assertEqual(window.map.selected_id, platform_id)
                self.assertEqual(set(window.map._visible_platforms()), {platform_id})
                route, trail, x, y = expected[platform_id]
                self.assertEqual(window.state.route, route)
                self.assertEqual(list(window.map.trails[platform_id]), trail)
                self.assertEqual((window.state.pose.x, window.state.pose.y), (x, y))

    def test_unavailable_capabilities_disable_corresponding_actions(self) -> None:
        window = self.window
        state = window.service.platforms[window.selected_id]
        window.service.set_route(state.info.id, [Point(30, 30)])
        state.info = replace(state.info, capabilities=())
        window._refresh()
        self.assertTrue(all(not control.isEnabled() for control in window.direction_buttons))
        self.assertFalse(window.keyboard_checkbox.isEnabled())
        for control in (window.start_button, window.pause_button, window.clear_button, window.load_route_button, window.edit_checkbox):
            self.assertFalse(control.isEnabled())
        state.info = replace(state.info, capabilities=("manual", "mission"))
        window._refresh()
        self.assertTrue(all(control.isEnabled() for control in window.direction_buttons))
        self.assertTrue(window.start_button.isEnabled())
        self.assertTrue(window.edit_checkbox.isEnabled())

    def test_disabled_checked_keyboard_does_not_capture_table_keys(self) -> None:
        window = self.window
        window.show()
        window.tabs.setCurrentWidget(window.telemetry)
        window.telemetry.setFocus()
        self.app.processEvents()
        window.keyboard_checkbox.setChecked(True)
        QTest.keyPress(window.telemetry, Qt.Key.Key_W)
        self.assertTrue(window._keys)
        state = window.service.platforms[window.selected_id]
        self.assertGreater(state.desired_forward, 0)

        state.info = replace(state.info, capabilities=())
        window._refresh()
        self.assertTrue(window.keyboard_checkbox.isChecked())
        self.assertFalse(window.keyboard_checkbox.isEnabled())
        self.assertEqual(window._keys, set())
        self.assertEqual(state.desired_forward, 0)
        for key in (Qt.Key.Key_Space, Qt.Key.Key_W):
            with self.subTest(key=key):
                event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
                self.assertFalse(window.eventFilter(window.telemetry, event))
                QTest.keyClick(window.telemetry, key)
                self.assertEqual(window._keys, set())
        self.assertGreater(window.telemetry.rowCount(), 1)
        window.telemetry.setCurrentCell(0, 0)
        QTest.keyClick(window.telemetry, Qt.Key.Key_Down)
        self.assertEqual(window.telemetry.currentRow(), 1)


if __name__ == "__main__":
    unittest.main()
