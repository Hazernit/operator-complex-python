"""Выбор платформ и отрисовка локальной карты без оборудования."""

from __future__ import annotations

import os
from pathlib import Path
import unittest

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
    from operator_stub.map_widget import MapWidget

from operator_stub.service import OperatorService
from operator_stub.models import Point


@unittest.skipUnless(QT_AVAILABLE, "Для проверок карты нужен PySide6-Essentials")
class MapWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        plugins = Path(PySide6.__file__).parent / "Qt" / "plugins"
        if plugins.is_dir():
            QCoreApplication.addLibraryPath(str(plugins))
        cls.app = QApplication.instance() or QApplication(["operator-map-tests"])

    def setUp(self) -> None:
        self.service = OperatorService()
        self.widget = MapWidget()
        self.widget.platforms = self.service.platforms
        self.widget.selected_id = next(iter(self.service.platforms))
        self.widget.resize(720, 490)
        self.widget.show()
        self.selected = []
        self.waypoints = []
        self.widget.platform_selected.connect(self.selected.append)
        self.widget.waypoint_requested.connect(lambda x, y: self.waypoints.append((x, y)))
        self.app.processEvents()

    def tearDown(self) -> None:
        self.widget.close()
        self.app.processEvents()

    def test_selected_marker_click_preserves_selection_without_adding_waypoint(self) -> None:
        for editable in (True, False):
            self.widget.edit_route = editable
            for platform_id, state in self.service.platforms.items():
                with self.subTest(editable=editable, kind=state.info.kind):
                    self.widget.selected_id = platform_id
                    position = self.widget.world_to_screen(state.pose.x, state.pose.y)
                    before = len(self.selected)
                    QTest.mouseClick(self.widget, Qt.MouseButton.LeftButton, pos=position.toPoint())
                    self.assertEqual(self.selected[before:], [platform_id])
                    self.assertFalse(self.waypoints)

    def test_hidden_markers_cannot_be_selected_on_map(self) -> None:
        selected_id = self.widget.selected_id
        for editable in (True, False):
            self.widget.edit_route = editable
            for platform_id, state in self.service.platforms.items():
                if platform_id == selected_id:
                    continue
                with self.subTest(editable=editable, kind=state.info.kind):
                    position = self.widget.world_to_screen(state.pose.x, state.pose.y)
                    before = len(self.waypoints)
                    QTest.mouseClick(self.widget, Qt.MouseButton.LeftButton, pos=position.toPoint())
                    self.assertFalse(self.selected)
                    self.assertEqual(self.widget.selected_id, selected_id)
                    self.assertEqual(len(self.waypoints), before + int(editable))
                    if editable:
                        self.assertAlmostEqual(self.waypoints[-1][0], state.pose.x, delta=0.2)
                        self.assertAlmostEqual(self.waypoints[-1][1], state.pose.y, delta=0.2)

    def test_hidden_positions_routes_and_trails_do_not_change_map(self) -> None:
        for platform_id in self.service.platforms:
            self.service.connect(platform_id)
        for selected_id, selected_state in self.service.platforms.items():
            with self.subTest(kind=selected_state.info.kind):
                self.widget.selected_id = selected_id
                self.assertEqual(self.widget._visible_platforms(), {selected_id: selected_state})
                before = self.widget.grab().toImage()
                for platform_id, state in self.service.platforms.items():
                    if platform_id == selected_id:
                        continue
                    state.pose.x = 85 if state.pose.x != 85 else 75
                    state.pose.y = 65 if state.pose.y != 65 else 55
                    state.pose.heading += 45
                    state.route = [Point(70, 60), Point(80, 55)]
                    self.widget.trails[platform_id] = [(60, 60), (75, 55)]
                self.assertEqual(before, self.widget.grab().toImage())

    def test_missing_selection_renders_no_platforms(self) -> None:
        for selected_id in (None, "unknown-platform"):
            with self.subTest(selected_id=selected_id):
                self.widget.selected_id = selected_id
                self.assertEqual(self.widget._visible_platforms(), {})
                before = self.widget.grab().toImage()
                for platform_id, state in self.service.platforms.items():
                    state.pose.x = 80 if state.pose.x != 80 else 70
                    state.pose.heading += 90
                    state.route = [Point(60, 60), Point(70, 60)]
                    self.widget.trails[platform_id] = [(50, 50), (60, 50)]
                self.assertEqual(before, self.widget.grab().toImage())

    def test_empty_map_click_adds_waypoint_only_while_editing(self) -> None:
        position = self.widget.world_to_screen(75, 65).toPoint()
        self.widget.edit_route = True
        QTest.mouseClick(self.widget, Qt.MouseButton.LeftButton, pos=position)
        self.assertEqual(len(self.waypoints), 1)
        self.assertAlmostEqual(self.waypoints[0][0], 75, delta=0.2)
        self.assertAlmostEqual(self.waypoints[0][1], 65, delta=0.2)
        self.assertFalse(self.selected)
        self.widget.edit_route = False
        QTest.mouseClick(self.widget, Qt.MouseButton.LeftButton, pos=position)
        self.assertEqual(len(self.waypoints), 1)

    def test_marker_graphics_render_and_rotate_for_each_kind(self) -> None:
        for platform_id, state in self.service.platforms.items():
            self.service.connect(platform_id)
        for platform_id, state in self.service.platforms.items():
            with self.subTest(kind=state.info.kind):
                self.widget.selected_id = platform_id
                state.pose.heading = 0
                first = self.widget.grab().toImage()
                self.assertFalse(first.isNull())
                state.pose.heading = 90
                rotated = self.widget.grab().toImage()
                self.assertFalse(rotated.isNull())
                self.assertNotEqual(first, rotated)

    def test_minimum_size_leaves_space_below_legend(self) -> None:
        self.widget.resize(420, 310)
        self.app.processEvents()
        # The top axis label starts 9 px above Y=70; legend text ends near Y=39.
        self.assertGreater(self.widget.world_to_screen(0, 70).y() - 9, 40)
        self.assertFalse(self.widget.grab().isNull())


if __name__ == "__main__":
    unittest.main()
