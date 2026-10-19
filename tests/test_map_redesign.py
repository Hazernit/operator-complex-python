"""Viewport interaction and truthful map status without connected hardware."""
from __future__ import annotations

import os
from pathlib import Path
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

try:
    import PySide6
    from PySide6.QtCore import QCoreApplication, QPointF, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:
    QT_AVAILABLE = False
else:
    QT_AVAILABLE = True
    from operator_stub.map_widget import MapWidget

from operator_stub.service import OperatorService


@unittest.skipUnless(QT_AVAILABLE, 'Для проверок карты нужен PySide6-Essentials')
class MapViewportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plugins = Path(PySide6.__file__).parent / 'Qt' / 'plugins'
        if plugins.is_dir():
            QCoreApplication.addLibraryPath(str(plugins))
        cls.app = QApplication.instance() or QApplication(['operator-map-viewport-tests'])

    def setUp(self):
        self.widget = MapWidget()
        self.service = OperatorService()
        self.widget.platforms = self.service.platforms
        self.widget.selected_id = next(iter(self.service.platforms))
        self.widget.resize(720, 490)
        self.widget.show()
        self.app.processEvents()

    def tearDown(self):
        self.widget.close()

    def test_zoom_controls_and_fit_keep_coordinate_transform_reversible(self):
        for method in (self.widget.zoom_in, self.widget.zoom_out):
            for _ in range(30):
                method()
            self.assertGreaterEqual(self.widget.zoom, 0.65)
            self.assertLessEqual(self.widget.zoom, 3.0)
            x, y = self.widget.screen_to_world(self.widget.world_to_screen(42, 19))
            self.assertAlmostEqual(x, 42)
            self.assertAlmostEqual(y, 19)
        self.widget.pan = QPointF(100, -30)
        self.widget.fit_map()
        self.assertEqual(self.widget.zoom, 1)
        self.assertEqual(self.widget.pan, QPointF())

    def test_zoom_anchor_stays_under_cursor(self):
        anchor = QPointF(217, 193)
        before = self.widget.screen_to_world(anchor)
        self.widget._set_zoom(2.0, anchor)
        after = self.widget.screen_to_world(anchor)
        self.assertAlmostEqual(before[0], after[0])
        self.assertAlmostEqual(before[1], after[1])

    def test_center_selected_keeps_selected_pose_and_other_platforms_unchanged(self):
        state = self.widget.platforms[self.widget.selected_id]
        before = (state.pose.x, state.pose.y, state.pose.heading)
        self.widget.zoom_in()
        self.widget.center_selected()
        marker = self.widget.world_to_screen(state.pose.x, state.pose.y)
        self.assertAlmostEqual(marker.x(), self.widget._map_area().center().x())
        self.assertAlmostEqual(marker.y(), self.widget._map_area().center().y())
        self.assertEqual((state.pose.x, state.pose.y, state.pose.heading), before)
        self.widget.selected_id = None
        old_pan = QPointF(self.widget.pan)
        self.widget.center_selected()
        self.assertEqual(self.widget.pan, old_pan)

    def test_header_footer_and_outside_world_do_not_create_waypoints(self):
        waypoints = []
        self.widget.waypoint_requested.connect(lambda x, y: waypoints.append((x, y)))
        # Pan the world across the header to verify the viewport also gates edits.
        self.widget.pan = QPointF(0, -220)
        for point in (QPointF(300, 25), QPointF(300, 475),
                      self.widget.world_to_screen(110, 50)):
            QTest.mouseClick(self.widget, Qt.MouseButton.LeftButton, pos=point.toPoint())
        self.assertFalse(waypoints)

    def test_marker_status_distinguishes_offline_unknown_stale_and_fresh_data(self):
        state = self.widget.platforms[self.widget.selected_id]
        state.connected = False
        state.telemetry_age_s = 0
        self.assertEqual(self.widget._data_status(state)[0], 'Нет связи')
        state.connected = True
        state.telemetry_age_s = None
        self.assertEqual(self.widget._data_status(state)[0], 'Нет телеметрии')
        state.telemetry_age_s = 3.25
        self.assertIn('3.2 с', self.widget._data_status(state)[0])
        self.assertTrue(self.widget._data_status(state)[2])
        state.telemetry_age_s = 0.1
        self.assertFalse(self.widget._data_status(state)[2])


if __name__ == '__main__':
    unittest.main()
