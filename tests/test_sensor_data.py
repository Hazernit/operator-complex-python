"""Recording contracts: validation, localization, sensor geometry and replay."""

import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from operator_stub.models import Pose
from operator_stub.sensor_data import (
    RangeReading, SensorDataError, SensorFrame, SensorRecording,
    interpolation_sample, load_recording, project_reading,
)


HEADER = "time_s,type,x_m,y_m,heading_deg,angle_deg,range_m,fov_deg,max_range_m,x_offset_m,y_offset_m,yaw_offset_deg\n"


class SensorDataTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "sensors.txt"

    def load(self, body, header=HEADER):
        self.path.write_text(header + body, encoding="utf-8")
        return load_recording(self.path)

    def test_lidar_projected_in_rotated_robot_frame(self):
        frame = SensorFrame(0, Pose(10, 20, 90), (RangeReading("lidar", 0, 5),))
        ox, oy, x, y = project_reading(frame, frame.readings[0])
        self.assertAlmostEqual(ox, 10)
        self.assertAlmostEqual(oy, 20)
        self.assertAlmostEqual(x, 10)
        self.assertAlmostEqual(y, 25)

    def test_sensor_extrinsic_translation_and_rotation(self):
        reading = RangeReading("sonar", 0, 4, fov_deg=30, x_offset_m=2,
                               y_offset_m=1, yaw_offset_deg=90)
        result = project_reading(SensorFrame(0, Pose(10, 20, 90), (reading,)), reading)
        for actual, expected in zip(result, (9, 22, 5, 22)):
            self.assertAlmostEqual(actual, expected)

    def test_pose_interpolation_short_way_across_zero_heading(self):
        recording = self.load("10,pose,0,10,350,,,,,,,\n11,lidar,,,,0,5,,,,,\n12,pose,4,14,10,,,,,,,\n")
        frame = recording.frames[1]
        self.assertEqual((frame.pose.x, frame.pose.y), (2, 12))
        self.assertAlmostEqual(frame.pose.heading, 0)
        self.assertEqual(recording.duration, 2)
        self.assertEqual(recording.duration_s, 2)

    def test_no_return_is_finite_endpoint_with_hit_false(self):
        recording = self.load("0,pose,10,10,0,,,,,,,\n0,lidar,,,,45,inf,,20,,,\n")
        reading = recording.frames[0].readings[0]
        self.assertEqual(reading.range_m, 20)
        self.assertFalse(reading.hit)
        self.assertTrue(all(math.isfinite(value) for value in project_reading(recording.frames[0], reading)))

    def test_sonar_defaults_and_offsets(self):
        recording = self.load("0,pose,1,2,3,,,,,,,\n0,sonar,,,,20,9,,,0.4,-0.1,15\n")
        reading = recording.frames[0].readings[0]
        self.assertEqual((reading.fov_deg, reading.max_range_m), (30, 30))
        self.assertEqual((reading.x_offset_m, reading.y_offset_m, reading.yaw_offset_deg), (0.4, -0.1, 15))

    def test_interpolated_playback_never_moves_old_scan(self):
        recording = self.load("0,pose,10,10,0,,,,,,,\n0,lidar,,,,0,5,,,,,\n2,pose,20,10,0,,,,,,,\n")
        frame = interpolation_sample(recording, 1)
        self.assertEqual(frame.pose.x, 15)
        self.assertEqual(frame.reading_time_s, 0)
        self.assertEqual(project_reading(frame, frame.readings[0]), (10, 10, 15, 10))
        self.assertEqual(interpolation_sample(recording, 100).pose.x, 20)
        self.assertEqual(interpolation_sample(recording, -10).pose.x, 10)

    def test_playback_does_not_show_scan_from_future(self):
        recording = self.load("0,pose,10,10,0,,,,,,,\n1,lidar,,,,0,5,,,,,\n2,pose,20,10,0,,,,,,,\n")
        self.assertFalse(interpolation_sample(recording, 0.5).readings)
        self.assertTrue(interpolation_sample(recording, 1.5).readings)

    def async_recording(self):
        return self.load("0,pose,10,10,0,,,,,,,\n0,lidar,,,,0,5,,,,,\n"
                         "1,sonar,,,,0,4,,,,,\n2,lidar,,,,0,6,,,,,\n"
                         "3,pose,40,10,0,,,,,,,\n")

    def test_asynchronous_lidar_and_sonar_are_held_independently(self):
        recording = self.async_recording()
        sample = interpolation_sample(recording, 2.5)
        by_sensor = {reading.sensor: reading for reading in sample.readings}
        self.assertEqual(set(by_sensor), {"lidar", "sonar"})
        self.assertEqual(by_sensor["lidar"].measurement_time_s, 2)
        self.assertEqual(by_sensor["sonar"].measurement_time_s, 1)
        self.assertEqual(by_sensor["lidar"].range_m, 6)
        self.assertEqual(by_sensor["sonar"].range_m, 4)
        self.assertEqual((sample.pose.x, sample.pose.y), (35, 10))
        self.assertEqual(project_reading(sample, by_sensor["lidar"]), (30, 10, 36, 10))
        self.assertEqual(project_reading(sample, by_sensor["sonar"]), (20, 10, 24, 10))

    def test_asynchronous_channels_never_show_future_scans_after_seeking(self):
        recording = self.async_recording()
        interpolation_sample(recording, 2.5)
        before_sonar = interpolation_sample(recording, 0.5)
        self.assertEqual([reading.sensor for reading in before_sonar.readings], ["lidar"])
        self.assertEqual(before_sonar.readings[0].measurement_time_s, 0)
        between_scans = interpolation_sample(recording, 1.5)
        by_sensor = {reading.sensor: reading for reading in between_scans.readings}
        self.assertEqual(by_sensor["lidar"].measurement_time_s, 0)
        self.assertEqual(by_sensor["lidar"].range_m, 5)
        self.assertEqual(by_sensor["sonar"].measurement_time_s, 1)

    def test_asynchronous_rotating_sensor_uses_its_own_acquisition_heading(self):
        recording = self.load("0,pose,10,10,0,,,,,,,\n0,lidar,,,,0,5,,,,,\n"
                              "1,sonar,,,,0,4,,,,,\n2,lidar,,,,0,5,,,,,\n"
                              "3,pose,10,40,90,,,,,,,\n")
        sample = interpolation_sample(recording, 2.5)
        by_sensor = {reading.sensor: reading for reading in sample.readings}
        sonar = by_sensor["sonar"]
        lidar = by_sensor["lidar"]
        self.assertAlmostEqual(sonar.measurement_pose.heading, 30)
        self.assertAlmostEqual(lidar.measurement_pose.heading, 60)
        for actual, expected in zip(project_reading(sample, sonar),
                                    (10, 20, 10 + 4 * math.cos(math.radians(30)), 22)):
            self.assertAlmostEqual(actual, expected)
        for actual, expected in zip(project_reading(sample, lidar),
                                    (10, 30, 12.5, 30 + 5 * math.sin(math.radians(60)))):
            self.assertAlmostEqual(actual, expected)

    def test_unsorted_times_sorted_with_warning(self):
        recording = self.load("2,pose,20,10,0,,,,,,,\n1,lidar,,,,0,5,,,,,\n0,pose,10,10,0,,,,,,,\n")
        self.assertEqual([frame.time_s for frame in recording.frames], [0, 1, 2])
        self.assertEqual(len(recording.warnings), 1)

    def test_utf8_bom_comments_and_semicolon(self):
        text = "\ufeff# Данные\n\n" + HEADER.replace(",", ";") + "0;pose;1;2;90;;;;;;;\n0;sonar;;;;0;5;;;;;\n"
        self.path.write_text(text, encoding="utf-8")
        recording = load_recording(self.path)
        self.assertEqual(recording.frames[0].pose.heading, 90)
        self.assertEqual(recording.frames[0].readings[0].sensor, "sonar")

    def test_tab_and_space_delimiters(self):
        for separator in ("\t", " "):
            with self.subTest(separator=separator):
                recording = self.load(separator.join(("0", "pose", "1", "2", "90")) + "\n",
                                      separator.join(("time_s", "type", "x_m", "y_m", "heading_deg")) + "\n")
                self.assertEqual(recording.frames[0].pose.x, 1)

    def test_whitespace_blank_placeholder(self):
        recording = self.load("0 pose 1 2 90 - -\n0 lidar - - - 0 5\n",
                              "time_s type x_m y_m heading_deg angle_deg range_m\n")
        self.assertEqual(len(recording.frames[0].readings), 1)

    def test_ranges_only_require_localization(self):
        with self.assertRaisesRegex(SensorDataError, "Нужны строки pose"):
            self.load("0,lidar,,,,0,5,,,,,\n")

    def test_sensor_outside_localization_span_rejected(self):
        for sensor_time in (0, 3):
            with self.subTest(sensor_time=sensor_time):
                with self.assertRaisesRegex(SensorDataError, "вне диапазона pose"):
                    self.load(f"1,pose,10,10,0,,,,,,,\n{sensor_time},lidar,,,,0,5,,,,,\n2,pose,20,10,0,,,,,,,\n")

    def test_nonfinite_values_rejected_with_line_number(self):
        invalid_rows = (
            "0,pose,nan,10,0,,,,,,,\n",
            "inf,pose,10,10,0,,,,,,,\n",
            "0,pose,10,10,0,,,,,,,\n0,lidar,,,,0,nan,,,,,\n",
            "0,pose,10,10,0,,,,,,,\n0,lidar,,,,0,-inf,,,,,\n",
            "0,pose,10,10,0,,,,,,,\n0,lidar,,,,0,5,,,,,inf\n",
        )
        for rows in invalid_rows:
            with self.subTest(rows=rows):
                with self.assertRaisesRegex(SensorDataError, "Строка"):
                    self.load(rows)

    def test_bad_column_count_and_type_rejected(self):
        for row in ("0,pose,1,2\n", "0,laser,,,,0,5,,,,,\n"):
            with self.subTest(row=row):
                with self.assertRaises(SensorDataError):
                    self.load(row)

    def test_duplicate_pose_and_header_rejected(self):
        with self.assertRaisesRegex(SensorDataError, "повторная pose"):
            self.load("0,pose,1,2,90,,,,,,,\n0,pose,2,3,90,,,,,,,\n")
        with self.assertRaisesRegex(SensorDataError, "уникальными"):
            self.load("0,pose,1\n", "time_s,type,time_s\n")

    def test_invalid_ranges_fov_and_limits_rejected(self):
        invalid_rows = (
            "0,lidar,,,,0,-1,,,,,\n", "0,lidar,,,,0,31,,30,,,\n",
            "0,lidar,,,,0,2,,1001,,,\n", "0,sonar,,,,0,2,0,,,,\n",
            "0,sonar,,,,0,2,181,,,,\n", "0,lidar,,,,0,2,30,,,,\n",
            "-1,pose,1,2,0,,,,,,,\n", "0,pose,1000001,2,0,,,,,,,\n",
        )
        for row in invalid_rows:
            with self.subTest(row=row):
                with self.assertRaises(SensorDataError):
                    self.load("0,pose,1,2,0,,,,,,,\n" + row)

    def test_file_size_and_row_limits(self):
        self.path.write_bytes(b"abcdef")
        with patch("operator_stub.sensor_data.MAX_FILE_BYTES", 5):
            with self.assertRaisesRegex(SensorDataError, "10 МиБ"):
                load_recording(self.path)
        with patch("operator_stub.sensor_data.MAX_ROWS", 1):
            with self.assertRaisesRegex(SensorDataError, "много строк"):
                self.load("0,pose,1,2,0,,,,,,,\n1,pose,2,2,0,,,,,,,\n")
        with patch("operator_stub.sensor_data.MAX_FRAMES", 1):
            with self.assertRaisesRegex(SensorDataError, "временных кадров"):
                self.load("0,pose,1,2,0,,,,,,,\n1,pose,2,2,0,,,,,,,\n")

    def test_empty_broken_encoding_and_missing_file(self):
        with self.assertRaises(SensorDataError):
            self.load("", "# Empty\n")
        self.path.write_bytes(b"\xff\xff")
        with self.assertRaisesRegex(SensorDataError, "UTF-8"):
            load_recording(self.path)
        with self.assertRaisesRegex(SensorDataError, "прочитать"):
            load_recording(self.path.with_name("missing.txt"))

    def test_empty_recording_and_bad_cursor_rejected(self):
        with self.assertRaises(SensorDataError):
            interpolation_sample(SensorRecording((), ""), 0)
        recording = self.load("0,pose,1,2,0,,,,,,,\n")
        with self.assertRaises(SensorDataError):
            interpolation_sample(recording, math.nan)

    def test_shipped_examples_parse_and_have_sensor_hits(self):
        folder = Path(__file__).resolve().parents[1] / "examples"
        for filename in ("lidar-room.txt", "sonar-route.txt", "mixed-route.txt"):
            with self.subTest(filename=filename):
                recording = load_recording(folder / filename)
                self.assertGreater(recording.duration, 0)
                self.assertGreater(len(recording.frames), 3)
                self.assertTrue(any(reading.hit for frame in recording.frames for reading in frame.readings))


if __name__ == "__main__":
    unittest.main()
