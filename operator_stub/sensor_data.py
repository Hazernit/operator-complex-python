"""Validated sensor recordings and 2-D transforms, without UI dependencies.

The TXT interchange format is described in docs/sensor-format.md. Ranges alone
do not provide localization: a recording must include timestamped poses.
"""

from __future__ import annotations

import bisect
import csv
import math
from dataclasses import dataclass, replace
from functools import cached_property
from pathlib import Path

from .models import Pose


MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ROWS = 100_000
MAX_FRAMES = 20_000
MAX_TIME_S = 10_000_000.0
MAX_POSITION_M = 1_000_000.0
MAX_RANGE_M = 1_000.0


@dataclass(frozen=True)
class RangeReading:
    sensor: str
    angle_deg: float
    range_m: float
    max_range_m: float = 30.0
    fov_deg: float = 0.0
    hit: bool = True
    x_offset_m: float = 0.0
    y_offset_m: float = 0.0
    yaw_offset_deg: float = 0.0
    measurement_pose: Pose | None = None
    measurement_time_s: float | None = None


@dataclass(frozen=True)
class SensorFrame:
    time_s: float
    pose: Pose
    readings: tuple[RangeReading, ...]
    source: str = "Имитируемые датчики"
    # A held scan keeps its acquisition pose when the playback cursor moves.
    reading_pose: Pose | None = None
    reading_time_s: float | None = None


@dataclass(frozen=True)
class SensorRecording:
    frames: tuple[SensorFrame, ...]
    source_path: str
    warnings: tuple[str, ...] = ()

    @property
    def duration(self) -> float:
        return self.frames[-1].time_s - self.frames[0].time_s if self.frames else 0.0

    @property
    def duration_s(self) -> float:
        return self.duration

    @cached_property
    def _times(self) -> tuple[float, ...]:
        return tuple(frame.time_s for frame in self.frames)

    @cached_property
    def _scan_indices(self) -> tuple[int, ...]:
        latest = -1
        indices = []
        for index, frame in enumerate(self.frames):
            if frame.readings:
                latest = index
            indices.append(latest)
        return tuple(indices)

    @cached_property
    def _sensor_scan_indices(self) -> dict[str, tuple[int, ...]]:
        sensors = dict.fromkeys(reading.sensor for frame in self.frames for reading in frame.readings)
        latest = dict.fromkeys(sensors, -1)
        indices: dict[str, list[int]] = {sensor: [] for sensor in sensors}
        for index, frame in enumerate(self.frames):
            for reading in frame.readings:
                latest[reading.sensor] = index
            for sensor in sensors:
                indices[sensor].append(latest[sensor])
        return {sensor: tuple(values) for sensor, values in indices.items()}


class SensorDataError(ValueError):
    """Actionable, atomic recording validation failure."""


def _error(line: int, message: str) -> SensorDataError:
    return SensorDataError(f"Строка {line}: {message}")


def _number(raw: str, line: int, name: str, *, limit: float = MAX_POSITION_M) -> float:
    try:
        value = float(raw)
    except (ValueError, TypeError):
        raise _error(line, f"поле {name}: нужно число, получено {raw!r}") from None
    if not math.isfinite(value) or abs(value) > limit:
        raise _error(line, f"поле {name}: нужно конечное число в пределах ±{limit:g}")
    return value


def _pose_between(times: list[float], poses: dict[float, Pose], time_s: float) -> Pose:
    index = bisect.bisect_right(times, time_s)
    if index == 0:
        pose = poses[times[0]]
        return Pose(pose.x, pose.y, pose.heading)
    if index == len(times) or times[index - 1] == time_s:
        pose = poses[times[index - 1]]
        return Pose(pose.x, pose.y, pose.heading)
    left_t, right_t = times[index - 1], times[index]
    left, right = poses[left_t], poses[right_t]
    amount = (time_s - left_t) / (right_t - left_t)
    difference = (right.heading - left.heading + 180.0) % 360.0 - 180.0
    return Pose(
        left.x + amount * (right.x - left.x),
        left.y + amount * (right.y - left.y),
        (left.heading + amount * difference) % 360.0,
    )


def load_recording(path: str | Path) -> SensorRecording:
    """Read an entire UTF-8 TXT/CSV file or raise without returning partial data."""
    file_path = Path(path)
    try:
        if file_path.stat().st_size > MAX_FILE_BYTES:
            raise SensorDataError("Файл больше 10 МиБ. Разделите запись на несколько файлов.")
        with file_path.open("rb") as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise SensorDataError("Файл больше 10 МиБ. Разделите запись на несколько файлов.")
        text = raw.decode("utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise SensorDataError(f"Не удалось прочитать TXT в UTF-8: {exc}") from exc
    useful = [(index, value.strip()) for index, value in enumerate(text.splitlines(), 1)
              if value.strip() and not value.lstrip().startswith("#")]
    if not useful:
        raise SensorDataError("Файл пуст: нужны заголовок и строки pose/lidar/sonar.")
    if len(useful) - 1 > MAX_ROWS:
        raise SensorDataError(f"Слишком много строк: максимум {MAX_ROWS}.")
    header_line, header_text = useful[0]
    separator = next((candidate for candidate in (",", ";", "\t") if candidate in header_text), None)

    def split(value: str, line: int) -> list[str]:
        if separator is None:
            return ["" if part == "-" else part for part in value.split()]
        try:
            return [part.strip() for part in next(csv.reader([value], delimiter=separator, strict=True))]
        except csv.Error as exc:
            raise _error(line, f"некорректный CSV: {exc}") from exc

    names = [name.lower() for name in split(header_text, header_line)]
    allowed = {"time_s", "type", "x_m", "y_m", "heading_deg", "angle_deg", "range_m",
               "fov_deg", "max_range_m", "x_offset_m", "y_offset_m", "yaw_offset_deg"}
    if len(set(names)) != len(names) or any(not name for name in names):
        raise _error(header_line, "названия столбцов должны быть непустыми и уникальными")
    if not {"time_s", "type"}.issubset(names):
        raise _error(header_line, "нужен заголовок со столбцами time_s,type")
    unknown = set(names) - allowed
    if unknown:
        raise _error(header_line, f"неизвестные столбцы: {', '.join(sorted(unknown))}")
    poses: dict[float, Pose] = {}
    readings: dict[float, list[RangeReading]] = {}
    time_lines: dict[float, int] = {}
    input_times: list[float] = []
    for line, value in useful[1:]:
        parts = split(value, line)
        if len(parts) != len(names):
            raise _error(line, f"ожидалось {len(names)} столбцов, получено {len(parts)}")
        row = dict(zip(names, parts))

        def required(name: str, *, limit: float = MAX_POSITION_M) -> float:
            if not row.get(name, ""):
                raise _error(line, f"для {row.get('type', 'записи')} обязательно поле {name}")
            return _number(row[name], line, name, limit=limit)

        def optional(name: str, default: float, *, limit: float = MAX_POSITION_M) -> float:
            return _number(row[name], line, name, limit=limit) if row.get(name) else default

        time_s = required("time_s", limit=MAX_TIME_S)
        if time_s < 0:
            raise _error(line, "time_s не может быть отрицательным")
        kind = row["type"].lower()
        input_times.append(time_s)
        time_lines.setdefault(time_s, line)
        if len(time_lines) > MAX_FRAMES:
            raise _error(line, f"слишком много временных кадров: максимум {MAX_FRAMES}")
        if kind == "pose":
            if time_s in poses:
                raise _error(line, "повторная pose с тем же time_s; оставьте одно положение")
            poses[time_s] = Pose(required("x_m"), required("y_m"), required("heading_deg") % 360.0)
        elif kind in ("lidar", "sonar"):
            angle = required("angle_deg")
            maximum = optional("max_range_m", 30.0, limit=MAX_RANGE_M)
            if maximum <= 0:
                raise _error(line, "max_range_m должен быть больше нуля")
            distance_raw = row.get("range_m", "")
            if distance_raw.lower() in ("inf", "+inf"):
                distance, hit = maximum, False
            else:
                distance, hit = required("range_m", limit=MAX_RANGE_M), True
                if distance < 0 or distance > maximum:
                    raise _error(line, "range_m должен быть от 0 до max_range_m; нет отражения: inf")
            fov = optional("fov_deg", 30.0 if kind == "sonar" else 0.0, limit=180.0)
            if fov < 0 or (kind == "sonar" and fov <= 0):
                raise _error(line, "fov_deg: у сонара угол больше 0 и не больше 180°")
            if kind == "lidar" and fov != 0:
                raise _error(line, "у отдельного луча lidar fov_deg должен быть 0")
            reading = RangeReading(kind, angle, distance, maximum, fov, hit,
                                   optional("x_offset_m", 0.0), optional("y_offset_m", 0.0),
                                   optional("yaw_offset_deg", 0.0))
            readings.setdefault(time_s, []).append(reading)
        else:
            raise _error(line, f"неизвестный type {kind!r}; доступны pose, lidar, sonar")
        # A malformed unused numeric cell should not silently disappear.
        for name, cell in row.items():
            if name not in ("time_s", "type") and cell:
                if name == "range_m" and kind in ("lidar", "sonar") and cell.lower() in ("inf", "+inf"):
                    continue
                _number(cell, line, name)
    if not poses:
        raise SensorDataError("Нужны строки pose с x_m,y_m,heading_deg: по одним дальностям нельзя построить глобальный маршрут.")
    pose_times = sorted(poses)
    for time_s in readings:
        if not pose_times[0] <= time_s <= pose_times[-1]:
            raise _error(time_lines[time_s], "время датчика вне диапазона pose; добавьте положение до и после измерений")
    warnings = []
    if any(right < left for left, right in zip(input_times, input_times[1:])):
        warnings.append("Строки были упорядочены по time_s; порядок лучей внутри одного времени сохранён.")
    if not readings:
        warnings.append("В записи только pose: можно показать траекторию, измерений lidar/sonar нет.")
    source = f"TXT: {file_path.name}"
    frames = []
    for time_s in sorted(time_lines):
        pose = _pose_between(pose_times, poses, time_s)
        measurement_pose = Pose(pose.x, pose.y, pose.heading)
        bound = tuple(replace(reading, measurement_pose=measurement_pose, measurement_time_s=time_s)
                      for reading in readings.get(time_s, ()))
        frames.append(SensorFrame(time_s, pose, bound, source))
    return SensorRecording(tuple(frames), str(file_path.resolve()), tuple(warnings))


def interpolation_sample(recording: SensorRecording, time_s: float) -> SensorFrame:
    """Interpolate localization; hold each sensor's scan independently.

    The input cursor uses absolute recording seconds and is clamped to its span.
    A scan from the future is never shown. Each reading retains its own pose
    and time, so asynchronous lidar/sonar observations stay correctly located.
    """
    if not recording.frames:
        raise SensorDataError("Запись не содержит кадров.")
    if not math.isfinite(time_s):
        raise SensorDataError("Время воспроизведения должно быть конечным числом.")
    times = recording._times
    cursor = min(max(time_s, times[0]), times[-1])
    left_index = bisect.bisect_right(times, cursor) - 1
    left = recording.frames[left_index]
    if left_index + 1 < len(times) and cursor != left.time_s:
        right = recording.frames[left_index + 1]
        amount = (cursor - left.time_s) / (right.time_s - left.time_s)
        difference = (right.pose.heading - left.pose.heading + 180.0) % 360.0 - 180.0
        pose = Pose(left.pose.x + amount * (right.pose.x - left.pose.x),
                    left.pose.y + amount * (right.pose.y - left.pose.y),
                    (left.pose.heading + amount * difference) % 360.0)
    else:
        pose = Pose(left.pose.x, left.pose.y, left.pose.heading)
    scan_index = recording._scan_indices[left_index]
    scan = recording.frames[scan_index] if scan_index >= 0 else None
    sensor_indices = {sensor: values[left_index]
                      for sensor, values in recording._sensor_scan_indices.items()}
    held = []
    for index in sorted({value for value in sensor_indices.values() if value >= 0}):
        sensor_frame = recording.frames[index]
        for reading in sensor_frame.readings:
            if sensor_indices[reading.sensor] != index:
                continue
            measurement_pose = reading.measurement_pose or sensor_frame.reading_pose or sensor_frame.pose
            measurement_time = reading.measurement_time_s
            if measurement_time is None:
                measurement_time = (sensor_frame.reading_time_s if sensor_frame.reading_time_s is not None
                                    else sensor_frame.time_s)
            if reading.measurement_pose is None or reading.measurement_time_s is None:
                reading = replace(reading, measurement_pose=measurement_pose,
                                  measurement_time_s=measurement_time)
            held.append(reading)
    return SensorFrame(cursor, pose, tuple(held), recording.frames[0].source,
                       (scan.reading_pose or scan.pose) if scan else None,
                       (scan.reading_time_s if scan.reading_time_s is not None else scan.time_s)
                       if scan else None)


def project_reading(frame: SensorFrame, reading: RangeReading) -> tuple[float, float, float, float]:
    """Return world origin/end XY; a sonar end denotes only its beam centre."""
    pose = reading.measurement_pose or frame.reading_pose or frame.pose
    yaw = math.radians(pose.heading)
    origin_x = pose.x + math.cos(yaw) * reading.x_offset_m - math.sin(yaw) * reading.y_offset_m
    origin_y = pose.y + math.sin(yaw) * reading.x_offset_m + math.cos(yaw) * reading.y_offset_m
    bearing = math.radians(pose.heading + reading.yaw_offset_deg + reading.angle_deg)
    return (origin_x, origin_y, origin_x + reading.range_m * math.cos(bearing),
            origin_y + reading.range_m * math.sin(bearing))
