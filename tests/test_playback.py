"""Read-only recording playback has its own cursor and never drives a robot."""
from __future__ import annotations

import copy
import math
from pathlib import Path
import tempfile
import unittest

from operator_stub.models import Pose
from operator_stub.playback import RecordingPlayer
from operator_stub.sensor_data import (
    RangeReading, SensorFrame, SensorRecording, load_recording, project_reading,
)


def recording():
    return SensorRecording((
        SensorFrame(10.0, Pose(0, 0, 350), (RangeReading('lidar', 10, 5),), 'TXT: test.txt'),
        SensorFrame(12.0, Pose(4, 0, 10), (RangeReading('sonar', 80, 3, fov_deg=30),), 'TXT: test.txt'),
        SensorFrame(15.0, Pose(4, 3, 90), (), 'TXT: test.txt'),
    ), 'test.txt')


class RecordingPlayerTests(unittest.TestCase):
    def test_initial_cursor_uses_absolute_recording_time_and_starts_paused(self):
        player = RecordingPlayer(recording())
        self.assertEqual(player.time_s, 10)
        self.assertEqual(player.index, 0)
        self.assertFalse(player.playing)
        self.assertEqual(player.speed, 1)
        self.assertEqual(player.frame.time_s, 10)

    def test_paused_player_does_not_advance(self):
        player = RecordingPlayer(recording())
        player.seek(11)
        player.advance(3)
        self.assertEqual(player.time_s, 11)
        self.assertFalse(player.playing)

    def test_playback_speed_and_negative_elapsed_time(self):
        player = RecordingPlayer(recording())
        player.playing = True
        player.speed = 2
        player.advance(.5)
        self.assertEqual(player.time_s, 11)
        player.advance(-5)
        self.assertEqual(player.time_s, 11)
        self.assertTrue(player.playing)

    def test_seek_clamps_to_recording_span_and_rejects_nonfinite_time(self):
        player = RecordingPlayer(recording())
        player.seek(-200)
        self.assertEqual(player.time_s, 10)
        self.assertEqual(player.index, 0)
        player.seek(200)
        self.assertEqual(player.time_s, 15)
        self.assertEqual(player.index, 2)
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                player.seek(value)
            self.assertEqual(player.time_s, 15)

    def test_end_of_recording_pauses_and_does_not_wrap(self):
        player = RecordingPlayer(recording())
        player.playing = True
        player.advance(100)
        self.assertEqual(player.time_s, 15)
        self.assertFalse(player.playing)
        player.advance(1)
        self.assertEqual(player.time_s, 15)
        self.assertEqual(player.measured_speed, 0)

    def test_players_of_same_recording_have_independent_cursors(self):
        source = recording()
        first, second = RecordingPlayer(source), RecordingPlayer(source)
        first.playing = True
        first.advance(1)
        second.seek(14)
        self.assertEqual(first.time_s, 11)
        self.assertEqual(second.time_s, 14)
        self.assertTrue(first.playing)
        self.assertFalse(second.playing)
        self.assertEqual(first.speed, 1)
        second.speed = .5
        self.assertEqual(first.speed, 1)

    def test_operations_do_not_mutate_recorded_poses_or_readings(self):
        source = recording()
        before = copy.deepcopy(source)
        player = RecordingPlayer(source)
        player.seek(11)
        player.playing = True
        player.advance(.7)
        _ = player.frame, player.trajectory, player.measured_speed
        player.seek(100)
        player.seek(-100)
        self.assertEqual(source, before)

    def test_interpolated_pose_is_a_copy_and_scan_keeps_acquisition_origin(self):
        source = recording()
        player = RecordingPlayer(source)
        player.seek(11)
        sample = player.frame
        self.assertEqual((sample.pose.x, sample.pose.y), (2, 0))
        self.assertEqual(sample.pose.heading, 0)
        self.assertEqual(sample.reading_time_s, 10)
        original = source.frames[0].readings[0]
        measured = sample.readings[0]
        self.assertEqual((measured.sensor, measured.angle_deg, measured.range_m),
                         (original.sensor, original.angle_deg, original.range_m))
        self.assertEqual(measured.measurement_pose, source.frames[0].pose)
        self.assertEqual(measured.measurement_time_s, 10)
        self.assertEqual((sample.reading_pose.x, sample.reading_pose.y), (0, 0))
        ox, oy, x, y = project_reading(sample, sample.readings[0])
        self.assertEqual((ox, oy), (0, 0))
        self.assertAlmostEqual(x, 5)
        self.assertAlmostEqual(y, 0)
        sample.pose.x = 500
        self.assertEqual(source.frames[0].pose.x, 0)
        self.assertEqual(player.frame.pose.x, 2)

    def test_measured_speed_comes_from_recorded_displacement_and_timestamps(self):
        player = RecordingPlayer(recording())
        self.assertEqual(player.measured_speed, 2)
        player.seek(11)
        self.assertEqual(player.measured_speed, 2)
        player.seek(12)
        self.assertEqual(player.measured_speed, 1)
        player.seek(15)
        self.assertEqual(player.measured_speed, 0)

    def test_measured_trajectory_stops_at_cursor_and_updates_after_seeking(self):
        player = RecordingPlayer(recording())
        player.seek(11)
        self.assertEqual(player.trajectory, [(0, 0), (2, 0)])
        player.seek(13)
        self.assertEqual(player.trajectory, [(0, 0), (4, 0), (4, 1)])
        player.seek(10)
        self.assertEqual(player.trajectory, [(0, 0)])

    def test_bounds_fit_localization_and_projected_reflections(self):
        source = recording()
        player = RecordingPlayer(source)
        minimum_x, maximum_x, minimum_y, maximum_y = player.bounds
        self.assertGreaterEqual(maximum_x - minimum_x, 10)
        self.assertGreaterEqual(maximum_y - minimum_y, 10)
        for frame in source.frames:
            points = [(frame.pose.x, frame.pose.y)]
            points.extend(project_reading(frame, item)[2:] for item in frame.readings if item.hit)
            for x, y in points:
                self.assertLessEqual(minimum_x, x)
                self.assertGreaterEqual(maximum_x, x)
                self.assertLessEqual(minimum_y, y)
                self.assertGreaterEqual(maximum_y, y)

    def test_single_frame_is_playable_and_has_finite_bounds(self):
        player = RecordingPlayer(SensorRecording((SensorFrame(7, Pose(-20, -30, 45), ()),), 'one.txt'))
        player.playing = True
        player.advance(.1)
        self.assertEqual(player.time_s, 7)
        self.assertFalse(player.playing)
        self.assertEqual(player.measured_speed, 0)
        self.assertEqual(player.trajectory, [(-20, -30)])
        self.assertTrue(all(math.isfinite(value) for value in player.bounds))

    def test_bounds_fit_sonar_sector_sensor_offsets_and_no_hit_beams(self):
        scan = SensorFrame(0, Pose(0, 0, 0), (
            RangeReading('sonar', 0, 20, fov_deg=120, x_offset_m=2, y_offset_m=3),
            RangeReading('lidar', 180, 50, max_range_m=50, hit=False),
        ))
        player = RecordingPlayer(SensorRecording((scan,), 'wide-scan.txt'))
        minimum_x, maximum_x, minimum_y, maximum_y = player.bounds
        points = [(2, 3), (-50, 0), (22, 3)]
        points.extend((2 + 20 * math.cos(math.radians(angle)), 3 + 20 * math.sin(math.radians(angle)))
                      for angle in (-60, 60))
        for x, y in points:
            with self.subTest(point=(x, y)):
                self.assertLessEqual(minimum_x, x)
                self.assertGreaterEqual(maximum_x, x)
                self.assertLessEqual(minimum_y, y)
                self.assertGreaterEqual(maximum_y, y)

    def test_empty_recording_is_rejected(self):
        with self.assertRaises(ValueError):
            RecordingPlayer(SensorRecording((), 'empty.txt'))

    def test_loaded_file_heading_interpolates_through_zero_in_short_direction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'heading.txt'
            path.write_text('time_s,type,x_m,y_m,heading_deg\n20,pose,0,0,350\n22,pose,4,0,10\n', encoding='utf-8')
            player = RecordingPlayer(load_recording(path))
            player.seek(21)
            self.assertEqual(player.frame.pose.heading, 0)
            self.assertEqual(player.frame.pose.x, 2)
            self.assertTrue(player.recording.warnings)


if __name__ == '__main__':
    unittest.main()
