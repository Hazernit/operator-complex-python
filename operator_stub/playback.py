"""Read-only playback of localized sensor recordings; never sends commands."""
from __future__ import annotations

import bisect
import math

from .sensor_data import SensorRecording, interpolation_sample, project_reading


class RecordingPlayer:
    def __init__(self, recording: SensorRecording):
        if not recording.frames:
            raise ValueError('В записи нет кадров.')
        self.recording = recording
        self.times = tuple(frame.time_s for frame in recording.frames)
        self.time_s = self.times[0]
        self.playing = False
        self.speed = 1.0
        first_pose = recording.frames[0].pose
        xmin = xmax = first_pose.x
        ymin = ymax = first_pose.y

        def include(x, y):
            nonlocal xmin, xmax, ymin, ymax
            xmin, xmax = min(xmin, x), max(xmax, x)
            ymin, ymax = min(ymin, y), max(ymax, y)

        for frame in recording.frames:
            include(frame.pose.x, frame.pose.y)
            for reading in frame.readings:
                ox, oy, x, y = project_reading(frame, reading)
                include(ox, oy)
                include(x, y)
                if reading.sensor == 'sonar':
                    pose = reading.measurement_pose or frame.reading_pose or frame.pose
                    centre = pose.heading + reading.yaw_offset_deg + reading.angle_deg
                    angles = [centre - reading.fov_deg / 2, centre + reading.fov_deg / 2]
                    angles.extend(angle for angle in range(math.ceil(angles[0] / 90) * 90, math.floor(angles[1] / 90) * 90 + 1, 90))
                    for angle in angles:
                        bearing = math.radians(angle)
                        include(ox + reading.range_m * math.cos(bearing), oy + reading.range_m * math.sin(bearing))
        width, height = max(10.0, xmax - xmin), max(10.0, ymax - ymin)
        centre_x, centre_y = (xmin + xmax) / 2, (ymin + ymax) / 2
        self.bounds = (centre_x - width * .6, centre_x + width * .6,
                       centre_y - height * .6, centre_y + height * .6)

    @property
    def index(self):
        return max(0, bisect.bisect_right(self.times, self.time_s) - 1)

    @property
    def frame(self):
        return interpolation_sample(self.recording, self.time_s)

    @property
    def measured_speed(self):
        index = self.index
        if index == len(self.times) - 1:
            return 0.0
        left, right = self.recording.frames[index:index + 2]
        return math.hypot(right.pose.x - left.pose.x, right.pose.y - left.pose.y) / (right.time_s - left.time_s)

    @property
    def trajectory(self):
        frames = self.recording.frames[:self.index + 1]
        stride = max(1, len(frames) // 4000)
        result = [(frame.pose.x, frame.pose.y) for frame in frames[::stride]]
        pose = self.frame.pose
        if not result or result[-1] != (pose.x, pose.y):
            result.append((pose.x, pose.y))
        return result

    def seek(self, time_s):
        if not math.isfinite(time_s):
            raise ValueError('Время записи должно быть конечным.')
        self.time_s = max(self.times[0], min(self.times[-1], time_s))

    def advance(self, dt):
        if self.playing:
            self.seek(self.time_s + max(0, dt) * self.speed)
            if self.time_s >= self.times[-1]:
                self.playing = False
