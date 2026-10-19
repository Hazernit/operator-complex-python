"""Sensor map contracts: measured geometry, uncertainty and selected source."""

from __future__ import annotations

import os
from pathlib import Path
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

try:
    import PySide6
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication
except ImportError:
    QT_AVAILABLE = False
else:
    QT_AVAILABLE = True
    from operator_stub.map_widget import MapWidget

from operator_stub.models import PlatformInfo, Pose, State
from operator_stub.sensor_data import RangeReading, SensorFrame


@unittest.skipUnless(QT_AVAILABLE, "Для проверок карты нужен PySide6-Essentials")
class SensorMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plugins = Path(PySide6.__file__).parent / "Qt" / "plugins"
        if plugins.is_dir():
            QCoreApplication.addLibraryPath(str(plugins))
        cls.app = QApplication.instance() or QApplication(["operator-sensor-map-tests"])

    def setUp(self):
        self.widget = MapWidget()
        self.widget.resize(720, 490)
        self.widget.platforms = {
            "selected": State(PlatformInfo("selected", "Наземная", "НРТК"),
                              connected=True, pose=Pose(15, 15, 0)),
            "hidden": State(PlatformInfo("hidden", "Лодка", "БЭК"),
                            connected=True, pose=Pose(70, 20, 90)),
        }
        self.widget.selected_id = "selected"
        self.widget.show()
        self.app.processEvents()

    def tearDown(self):
        self.widget.close()
        self.app.processEvents()

    def cloud(self, platform_id="selected"):
        return tuple(self.widget._clouds.get(platform_id, {}).values())

    def test_ninety_degree_heading_projects_forward_lidar_north(self):
        frame = SensorFrame(1, Pose(10, 20, 90), (RangeReading("lidar", 0, 5),))
        self.widget.ingest_frame("selected", frame)
        self.assertEqual(len(self.cloud()), 1)
        x, y = self.cloud()[0]
        self.assertAlmostEqual(x, 10)
        self.assertAlmostEqual(y, 25)
        origin_screen = self.widget.world_to_screen(10, 20)
        measured_screen = self.widget.world_to_screen(x, y)
        self.assertAlmostEqual(origin_screen.x(), measured_screen.x())
        self.assertLess(measured_screen.y(), origin_screen.y())

    def test_sonar_echoes_do_not_create_precise_obstacle_cloud(self):
        frame = SensorFrame(1, Pose(40, 30, 0), (
            RangeReading("sonar", 0, 12, fov_deg=40),
            RangeReading("sonar", 45, 8, fov_deg=30),
        ))
        self.widget.ingest_frame("selected", frame)
        self.assertFalse(self.cloud())
        self.widget.sensor_frame = frame
        with_sonar = self.widget.grab().toImage()
        self.widget.draw_sensors = False
        self.assertNotEqual(with_sonar, self.widget.grab().toImage())

    def test_lidar_hits_accumulate_but_no_return_does_not(self):
        frame = SensorFrame(1, Pose(40, 30, 0), (
            RangeReading("lidar", 0, 10),
            RangeReading("lidar", 90, 30, hit=False),
            RangeReading("sonar", -90, 15, fov_deg=30),
        ))
        self.widget.ingest_frame("selected", frame)
        self.assertEqual(self.cloud(), ((50, 30),))

    def test_held_scan_uses_acquisition_pose_and_is_not_reingested(self):
        first = SensorFrame(1.5, Pose(50, 40, 90), (RangeReading("lidar", 0, 10),),
                            "Файл", reading_pose=Pose(20, 25, 0), reading_time_s=1)
        second = SensorFrame(1.8, Pose(55, 45, 120), first.readings, "Файл",
                             reading_pose=Pose(20, 25, 0), reading_time_s=1)
        self.widget.ingest_frame("selected", first)
        self.assertEqual(self.cloud(), ((30, 25),))
        self.widget.ingest_frame("selected", second)
        self.assertEqual(self.cloud(), ((30, 25),))
        self.widget.sensor_frame = second
        self.assertFalse(self.widget.grab().isNull())

    def test_other_platform_cloud_does_not_affect_selected_map(self):
        self.widget.draw_sensors = False
        self.widget.sensor_frame = None
        before = self.widget.grab().toImage()
        frame = SensorFrame(1, Pose(50, 30, 0), (
            RangeReading("lidar", 0, 15), RangeReading("lidar", 90, 20),
        ))
        self.widget.ingest_frame("hidden", frame)
        self.assertTrue(self.cloud("hidden"))
        self.assertEqual(before, self.widget.grab().toImage())

    def test_layers_can_be_hidden_and_restored_without_losing_measurements(self):
        frame = SensorFrame(1, Pose(35, 25, 20), (
            RangeReading("lidar", 0, 20), RangeReading("lidar", 80, 17),
            RangeReading("sonar", -40, 15, fov_deg=35),
        ))
        self.widget.ingest_frame("selected", frame)
        self.widget.sensor_frame = frame
        enabled = self.widget.grab().toImage()
        points_before = self.cloud()
        self.widget.draw_points = False
        self.widget.draw_rays = False
        self.widget.draw_sensors = False
        disabled = self.widget.grab().toImage()
        self.assertNotEqual(enabled, disabled)
        self.assertEqual(points_before, self.cloud())
        self.widget.draw_points = True
        self.widget.draw_rays = True
        self.widget.draw_sensors = True
        self.assertEqual(enabled, self.widget.grab().toImage())

    def test_cloud_layer_and_live_sensor_layer_are_independent(self):
        frame = SensorFrame(1, Pose(40, 30, 0), (RangeReading("lidar", 0, 20),))
        self.widget.sensor_frame = frame
        self.widget.ingest_frame("selected", frame)
        self.widget.draw_sensors = False
        self.widget.draw_points = True
        cloud_only = self.widget.grab().toImage()
        self.widget.draw_points = False
        self.assertNotEqual(cloud_only, self.widget.grab().toImage())

    def test_reset_clears_only_requested_observations(self):
        frame = SensorFrame(1, Pose(40, 30, 0), (RangeReading("lidar", 0, 10),))
        self.widget.ingest_frame("selected", frame)
        self.widget.ingest_frame("hidden", frame)
        self.widget.reset_observations("selected")
        self.assertFalse(self.cloud("selected"))
        self.assertTrue(self.cloud("hidden"))
        self.widget.ingest_frame("selected", frame)
        self.assertTrue(self.cloud("selected"))

    def test_imported_map_can_use_negative_and_large_coordinates(self):
        self.widget.bounds = (-120.0, 240.0, -50.0, 190.0)
        for x, y in ((-120, -50), (240, 190), (15, 120), (0, 0)):
            with self.subTest(x=x, y=y):
                screen = self.widget.world_to_screen(x, y)
                restored_x, restored_y = self.widget.screen_to_world(screen)
                self.assertAlmostEqual(restored_x, x)
                self.assertAlmostEqual(restored_y, y)
                self.assertGreaterEqual(screen.x(), 0)
                self.assertLessEqual(screen.x(), self.widget.width())
                self.assertGreaterEqual(screen.y(), 0)
                self.assertLessEqual(screen.y(), self.widget.height())
        frame = SensorFrame(1, Pose(-40, 90, 90), (RangeReading("lidar", 0, 30),))
        self.widget.ingest_frame("selected", frame)
        self.widget.sensor_frame = frame
        x, y = self.cloud()[0]
        self.assertAlmostEqual(x, -40)
        self.assertAlmostEqual(y, 120)
        self.assertFalse(self.widget.grab().isNull())


if __name__ == "__main__":
    unittest.main()
