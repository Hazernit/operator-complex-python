"""Детерминированный источник тестовых данных без сетевых подключений.

Используются разные учебные модели движения и геометрические дальномеры.
Это локальная модель, а не цифровой двойник известного реального аппарата.
"""

from __future__ import annotations

from copy import deepcopy
import math
from numbers import Real
from typing import Any

from operator_stub.models import PlatformInfo, Pose, TelemetryField
from operator_stub.motion import MotionModel
from operator_stub.world import raycast, water_depth
from .base import AdapterSnapshot, RobotAdapter


def finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name}: требуется число")
    try:
        result = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{name}: число слишком велико") from error
    if not math.isfinite(result):
        raise ValueError(f"{name}: число должно быть конечным")
    return result


class MockAdapter(RobotAdapter):
    WIDTH = 100.0
    HEIGHT = 70.0

    def __init__(self, config: dict[str, Any]):
        if not isinstance(config, dict):
            raise ValueError("Описание платформы должно быть объектом")
        for key in ("id", "name", "kind"):
            if not isinstance(config.get(key), str) or not config[key].strip():
                raise ValueError(f"Платформа: поле {key} должно быть непустой строкой")
        description = config.get("description", PlatformInfo.__dataclass_fields__["description"].default)
        if not isinstance(description, str):
            raise ValueError("description должен быть строкой")
        capabilities = config.get("capabilities", ["manual", "mission"])
        if not isinstance(capabilities, list) or any(
            not isinstance(value, str) or value not in ("manual", "mission")
            for value in capabilities
        ):
            raise ValueError("capabilities должен быть списком возможностей manual/mission")
        if len(set(capabilities)) != len(capabilities):
            raise ValueError("capabilities не должен содержать повторяющиеся возможности")
        self.info = PlatformInfo(
            config["id"], config["name"], config["kind"],
            description=description, capabilities=tuple(capabilities),
        )
        pose = config.get("initial_pose", {})
        if not isinstance(pose, dict):
            raise ValueError("initial_pose должен быть объектом")
        x = finite_number(pose.get("x", 10.0), "Начальная координата X")
        y = finite_number(pose.get("y", 10.0), "Начальная координата Y")
        heading = finite_number(pose.get("heading", 0.0), "Начальный курс")
        if not 0 <= x <= self.WIDTH or not 0 <= y <= self.HEIGHT:
            raise ValueError("Начальное положение выходит за границы демонстрационного поля")
        self.initial_pose = Pose(x, y, heading % 360.0)
        specs = config.get("telemetry_fields", [])
        if not isinstance(specs, list):
            raise ValueError("telemetry_fields должен быть списком")
        self.field_specs: dict[str, TelemetryField] = {}
        self._generators: dict[str, dict[str, Any]] = {}
        core_semantics: set[str] = set()
        for spec in specs:
            if not isinstance(spec, dict):
                raise ValueError("Описание поля телеметрии должно быть объектом")
            key = spec.get("key")
            label = spec.get("label")
            unit = spec.get("unit", "")
            semantic = spec.get("semantic")
            if not isinstance(key, str) or not key.strip():
                raise ValueError("Поле телеметрии должно содержать непустой key")
            if key in self.field_specs:
                raise ValueError(f"Повторяющийся ключ телеметрии: {key}")
            if not isinstance(label, str) or not label.strip() or not isinstance(unit, str):
                raise ValueError(f"Поле {key}: label и unit должны быть строками")
            if semantic is not None:
                if not isinstance(semantic, str) or not semantic.strip():
                    raise ValueError(f"Поле {key}: semantic должен быть непустой строкой или null")
                semantic = semantic.strip()
            value = spec.get("value")
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueError(f"Поле {key}: поддерживаются число, строка, bool или null")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                finite_number(value, f"Значение поля {key}")
            is_core_percent = semantic in ("battery_percent", "link_quality_percent")
            if is_core_percent:
                if semantic in core_semantics:
                    raise ValueError(f"Повторяющийся semantic: {semantic}")
                core_semantics.add(semantic)
                if value is not None:
                    percent = finite_number(value, f"Значение поля {key}")
                    if not 0 <= percent <= 100:
                        raise ValueError(f"Поле {key}: процент должен быть в диапазоне [0; 100] или null")
            self.field_specs[key] = TelemetryField(key, label, unit, value, semantic=semantic)
            demo = spec.get("demo")
            if demo is not None:
                if not isinstance(demo, dict) or demo.get("kind") != "wave":
                    raise ValueError(f"Поле {key}: поддерживается только demo.kind=wave")
                base = finite_number(value, f"Начальное значение поля {key}")
                amplitude = finite_number(demo.get("amplitude", 1.0), "Амплитуда")
                period = finite_number(demo.get("period_s", 20.0), "Период")
                if amplitude < 0 or period <= 0:
                    raise ValueError("Амплитуда должна быть неотрицательной, период положительным")
                if not math.isfinite(base + amplitude) or not math.isfinite(base - amplitude):
                    raise ValueError(f"Поле {key}: диапазон демонстрационной волны слишком велик")
                if is_core_percent and not (0 <= base - amplitude <= base + amplitude <= 100):
                    raise ValueError(f"Поле {key}: демонстрационный процент должен оставаться в диапазоне [0; 100]")
                self._generators[key] = {"base": base, "amplitude": amplitude, "period_s": period}
        self._pose = deepcopy(self.initial_pose)
        self._motion = MotionModel(self.info.kind, self.initial_pose)
        self._pose = self._motion.pose
        self._elapsed = 0.0
        self._forward = 0.0
        self._turn = 0.0
        self._speed = 0.0
        self._connected = False

    def connect(self) -> AdapterSnapshot:
        self._connected = True
        self.halt()
        return self._snapshot()

    def disconnect(self) -> None:
        self.halt()
        self._connected = False

    def halt(self) -> None:
        """Явный STOP учебной среды, отличающийся от отпускания газа/руля."""
        self._forward = self._turn = self._speed = 0.0
        self._motion.halt()

    def set_velocity(self, forward: float, turn: float) -> None:
        forward = finite_number(forward, "Линейный ввод")
        turn = finite_number(turn, "Угловой ввод")
        if not -1 <= forward <= 1 or not -1 <= turn <= 1:
            raise ValueError("Демонстрационный ввод должен быть в диапазоне [-1; 1]")
        if not self._connected:
            raise ValueError("Платформа отключена")
        self._forward, self._turn = forward, turn

    def tick(self, dt: float) -> AdapterSnapshot:
        dt = finite_number(dt, "Шаг времени")
        if not 0 <= dt <= 60:
            raise ValueError("Шаг времени должен быть в диапазоне [0; 60] секунд")
        if not self._connected or dt == 0:
            return self._snapshot()
        self._elapsed += dt
        self._motion.step(self._forward, self._turn, dt)
        self._speed = self._motion.speed
        return self._snapshot()

    def reset(self) -> AdapterSnapshot:
        self._motion = MotionModel(self.info.kind, self.initial_pose)
        self._pose = self._motion.pose
        self._elapsed = self._forward = self._turn = self._speed = 0.0
        return self._snapshot()

    def _snapshot(self) -> AdapterSnapshot:
        values = {key: spec.value for key, spec in self.field_specs.items()}
        for key, generator in self._generators.items():
            # Сначала ограничиваем время одним периодом, затем вычисляем долю.
            # Прямое elapsed / period переполняется для малых period_s.
            period = generator["period_s"]
            phase = math.tau * ((self._elapsed % period) / period)
            values[key] = round(generator["base"] + generator["amplitude"] * math.sin(phase), 3)
        frame = self._sensor_frame()
        # These known demo channels are now derived from the model. Arbitrary
        # configured channels retain their provided values/generators.
        derived = {
            "demo_altitude": 8.0,
            "demo_flight_state": "Удержание высоты 8 м / движение в плоскости",
            "demo_obstacle_distance": min((r.range_m for r in frame.readings
                                            if abs(r.angle_deg) <= 20 and r.hit), default=30.0),
            "demo_chassis_state": "Контакт с препятствием" if self._motion.collision else "Модель дифференциального привода",
            "demo_depth": water_depth(self._pose.x, self._pose.y),
            "demo_hull_state": "Контакт с препятствием" if self._motion.collision else "Корпус с рулём / инерция",
            "model_yaw_rate": round(self._motion.yaw_rate_deg_s, 2),
            "model_speed": round(self._speed, 3),
        }
        values.update({key: value for key, value in derived.items() if key in self.field_specs})
        return AdapterSnapshot(frame.pose, self._speed, values, frame, deepcopy(self._pose),
                               self._motion.yaw_rate_deg_s, self._motion.collision)

    def _sensor_frame(self):
        from operator_stub.sensor_data import RangeReading, SensorFrame

        # Synthetic odometry/localization estimate: deterministic centimetre
        # error depending on travelled distance; stationary data do not wander.
        travel = self._motion.distance_travelled
        pose = Pose(round(self._pose.x + 0.015 * math.sin(travel / 4.0), 3),
                    round(self._pose.y + 0.015 * math.sin(travel / 6.0), 3),
                    round((self._pose.heading + 0.08 * math.sin(travel / 5.0)) % 360.0, 3))
        readings = []
        angles = range(-135, 136, 5) if self.info.kind == "БЭК" else range(-180, 180, 5)
        for angle in angles:
            distance = raycast(self._pose.x, self._pose.y, self._pose.heading + angle, 30.0)
            measured = min(30.0, max(0.0, distance + 0.01 * math.sin(math.radians(angle + travel))))
            readings.append(RangeReading("lidar", float(angle), round(measured, 3),
                                         max_range_m=30.0, hit=distance < 30.0))
        # A sonar reports one distance over its cone, without an exact bearing.
        # Sample the cone and use its closest echo; visualization must show an
        # arc/sector and must not turn this value into a precise lidar point.
        fov = 40.0 if self.info.kind == "БЭК" else 30.0
        maximum = 20.0 if self.info.kind == "БЭК" else 12.0
        distance = min(raycast(self._pose.x, self._pose.y,
                               self._pose.heading + (-fov / 2 + fov * index / 16), maximum)
                       for index in range(17))
        readings.append(RangeReading("sonar", 0.0, round(distance, 3), max_range_m=maximum,
                                     fov_deg=fov, hit=distance < maximum))
        return SensorFrame(self._elapsed, pose, tuple(readings),
                           "Симуляция: одометрия + курс; LiDAR и сонар по геометрии среды")
