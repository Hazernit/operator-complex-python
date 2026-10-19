"""Локальная демонстрационная логика, не зависящая от PySide6.

Не содержит подключения к роботу, сети, ROS 2 или БД. Контракт адаптера
явно отделён от общей модели состояния. Следование маршруту ниже служит
только проверке операторской панели на условном поле.
"""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Iterable

from .adapters import AdapterSnapshot, MockAdapter, RobotAdapter
from .adapters.mock import finite_number
from .models import (
    Event, Point, State, TEST_DATA_SOURCE,
    MISSION_IDLE, MISSION_RUNNING, MISSION_PAUSED,
    MISSION_COMPLETED, MISSION_CANCELLED,
)


DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "platforms": [
        {
            "id": "demo-uav", "name": "БПЛА — заглушка", "kind": "БПЛА",
            "description": "Учебный мультикоптер: инерция горизонтальной скорости, плавный курс, фиксированная высота 8 м",
            "initial_pose": {"x": 18, "y": 50, "heading": 0},
            "telemetry_fields": [
                {"key": "demo_battery", "label": "Тестовый заряд", "unit": "%", "value": 85,
                 "semantic": "battery_percent"},
                {"key": "demo_signal", "label": "Тестовый сигнал", "unit": "%", "value": 90,
                 "semantic": "link_quality_percent",
                 "demo": {"kind": "wave", "amplitude": 4, "period_s": 18}},
                {"key": "demo_altitude", "label": "Модель: высота", "unit": "м", "value": 8},
                {"key": "demo_flight_state", "label": "Демо: состояние полёта", "value": "Тестовый статус"},
            ],
        },
        {
            "id": "demo-ugv", "name": "НРТК — заглушка", "kind": "НРТК",
            "description": "Учебный дифференциальный привод: ограниченные разгон и торможение, поворот на месте",
            "initial_pose": {"x": 18, "y": 30, "heading": 0},
            "telemetry_fields": [
                {"key": "demo_battery", "label": "Тестовый заряд", "unit": "%", "value": 76,
                 "semantic": "battery_percent"},
                {"key": "demo_signal", "label": "Тестовый сигнал", "unit": "%", "value": 88,
                 "semantic": "link_quality_percent",
                 "demo": {"kind": "wave", "amplitude": 5, "period_s": 20}},
                {"key": "demo_obstacle_distance", "label": "LiDAR: ближайшее препятствие ±20°", "unit": "м", "value": 30},
                {"key": "demo_chassis_state", "label": "Демо: ходовая", "value": "Тестовый статус"},
            ],
        },
        {
            "id": "demo-usv", "name": "БЭК — заглушка", "kind": "БЭК",
            "description": "Учебный корпус с рулём: продольная инерция, плавная динамика курса; на месте руль не поворачивает корпус",
            "initial_pose": {"x": 18, "y": 10, "heading": 0},
            "telemetry_fields": [
                {"key": "demo_battery", "label": "Тестовый заряд", "unit": "%", "value": 92,
                 "semantic": "battery_percent"},
                {"key": "demo_signal", "label": "Тестовый сигнал", "unit": "%", "value": 86,
                 "semantic": "link_quality_percent",
                 "demo": {"kind": "wave", "amplitude": 4, "period_s": 15}},
                {"key": "demo_depth", "label": "Модель: эхолот (вертикальная глубина)", "unit": "м", "value": 12},
                {"key": "demo_hull_state", "label": "Демо: состояние корпуса", "value": "Тестовый статус"},
            ],
        },
    ],
}


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Недопустимое нечисловое значение JSON: {value}")


class OperatorService:
    WIDTH = 100.0
    HEIGHT = 70.0
    MANUAL_TIMEOUT_S = 0.4
    MAX_ROUTE_POINTS = 500
    MAX_EVENTS = 250

    def __init__(
        self,
        config_path: str | Path | None = None,
        *,
        adapters: Iterable[RobotAdapter] | None = None,
    ) -> None:
        if config_path is not None and adapters is not None:
            raise ValueError("Укажите конфигурацию или готовые адаптеры")
        if adapters is None:
            config = deepcopy(DEFAULT_CONFIG)
            if config_path is not None:
                with Path(config_path).open("r", encoding="utf-8") as source:
                    config = json.load(source, parse_constant=_reject_json_constant)
            if not isinstance(config, dict) or config.get("schema_version", 1) != 1:
                raise ValueError("Поддерживается конфигурация schema_version=1")
            specs = config.get("platforms")
            if not isinstance(specs, list) or not specs:
                raise ValueError("Конфигурация должна содержать непустой список platforms")
            adapters = [MockAdapter(spec) for spec in specs]
        self.platforms: dict[str, State] = {}
        self._adapters: dict[str, RobotAdapter] = {}
        self.events: deque[Event] = deque(maxlen=self.MAX_EVENTS)
        self._elapsed = 0.0
        self._last_manual_command: dict[str, float | None] = {}
        for adapter in adapters:
            platform_id = adapter.info.id
            if platform_id in self.platforms:
                raise ValueError(f"Повторяющийся идентификатор платформы: {platform_id}")
            self._adapters[platform_id] = adapter
            self.platforms[platform_id] = State(
                info=adapter.info,
                pose=deepcopy(adapter.initial_pose),
                fields=deepcopy(adapter.field_specs),
            )
            self._last_manual_command[platform_id] = None
        if not self.platforms:
            raise ValueError("Нужна хотя бы одна платформа")
        self.note("", "Загружена программная заглушка. Источник всех показаний: тестовые данные.")

    def note(self, platform_id: str, message: str, level: str = "INFO") -> None:
        self.events.append(Event(datetime.now(timezone.utc), platform_id, str(message), level.upper()))

    def connect(self, platform_id: str) -> None:
        state, adapter = self._get(platform_id)
        if state.connected:
            return
        snapshot = adapter.connect()
        state.connected = True
        self._apply_snapshot(state, snapshot)
        self._clear_input(state)
        state.mode = "Миссия приостановлена" if state.mission_status == MISSION_PAUSED else "Ожидание"
        self.note(platform_id, "Подключён тестовый источник. Движение автоматически не возобновляется.")

    def disconnect(self, platform_id: str) -> None:
        state, adapter = self._get(platform_id)
        if not state.connected:
            return
        adapter.halt()
        self._apply_snapshot(state, adapter.tick(0.0))
        adapter.disconnect()
        self._clear_input(state)
        state.connected = False
        state.speed = 0.0
        state.mode = "Отключена"
        if state.mission_status == MISSION_RUNNING:
            state.mission_status = MISSION_PAUSED
        self.note(platform_id, "Тестовый источник отключён; положение сохранено, движение прекращено.", "WARNING")

    def set_velocity(self, platform_id: str, forward: float, turn: float) -> None:
        state, adapter = self._get(platform_id)
        self._require_capability(state, "manual")
        forward = finite_number(forward, "Линейный ввод")
        turn = finite_number(turn, "Угловой ввод")
        if not -1 <= forward <= 1 or not -1 <= turn <= 1:
            raise ValueError("Демонстрационный ввод должен быть в диапазоне [-1; 1]")
        self._require_connection(state)
        if state.mission_status in (MISSION_RUNNING, MISSION_PAUSED):
            raise ValueError("Перед ручным управлением отмените текущую миссию")
        adapter.set_velocity(forward, turn)
        if (forward or turn) and (forward != state.desired_forward or turn != state.desired_turn):
            state.collision = False
        state.desired_forward, state.desired_turn = forward, turn
        # Neutral explicitly cancels the dead-man deadline. It is a request to
        # coast/decelerate, not a pending motion command that may later expire.
        self._last_manual_command[platform_id] = self._elapsed if forward or turn else None
        state.mode = "Ручное управление" if forward or turn else (
            "Торможение" if state.speed > 0.03 or abs(state.yaw_rate_deg_s) > 0.1 else "Ожидание"
        )

    def stop(self, platform_id: str) -> None:
        state, adapter = self._get(platform_id)
        if state.connected:
            adapter.halt()
            self._apply_snapshot(state, adapter.tick(0.0))
        self._clear_input(state)
        state.speed = 0.0
        if state.mission_status == MISSION_RUNNING:
            state.mission_status = MISSION_PAUSED
        state.mode = "Отключена" if not state.connected else (
            "Миссия приостановлена" if state.mission_status == MISSION_PAUSED else "Ожидание"
        )
        self.note(platform_id, "Демонстрационное движение остановлено.")

    def set_route(self, platform_id: str, points: Iterable[Point]) -> None:
        state, _ = self._get(platform_id)
        if state.mission_status in (MISSION_RUNNING, MISSION_PAUSED):
            raise ValueError("Перед изменением маршрута отмените текущую миссию")
        validated: list[Point] = []
        for point in points:
            if not isinstance(point, Point):
                raise ValueError("Маршрут должен состоять из объектов Point(x, y)")
            x = finite_number(point.x, "Координата X")
            y = finite_number(point.y, "Координата Y")
            if not 0 <= x <= self.WIDTH or not 0 <= y <= self.HEIGHT:
                raise ValueError("Точки маршрута должны находиться внутри поля X:0–100, Y:0–70")
            validated.append(Point(x, y))
            if len(validated) > self.MAX_ROUTE_POINTS:
                raise ValueError(f"В маршруте допускается до {self.MAX_ROUTE_POINTS} точек")
        state.route = validated
        state.waypoint_index = 0
        state.mission_status = MISSION_IDLE
        self.note(platform_id, f"Задан тестовый маршрут: {len(validated)} точек.")

    def start_mission(self, platform_id: str) -> None:
        state, adapter = self._get(platform_id)
        self._require_capability(state, "mission")
        self._require_connection(state)
        if not state.route:
            raise ValueError("Сначала задайте хотя бы одну точку маршрута")
        if state.mission_status == MISSION_RUNNING:
            raise ValueError("Миссия уже выполняется")
        if state.mission_status == MISSION_PAUSED:
            raise ValueError("Возобновите приостановленную миссию или отмените её")
        self._clear_input(state)
        adapter.halt()
        state.collision = False
        state.waypoint_index = 0
        state.mission_status = MISSION_RUNNING
        state.mode = "Тестовая миссия"
        self.note(platform_id, "Начато выполнение тестового маршрута.")

    def pause_mission(self, platform_id: str) -> None:
        state, _ = self._get(platform_id)
        if state.mission_status != MISSION_RUNNING:
            raise ValueError("Можно приостановить только выполняющуюся миссию")
        self.stop(platform_id)

    def resume_mission(self, platform_id: str) -> None:
        state, _ = self._get(platform_id)
        self._require_capability(state, "mission")
        self._require_connection(state)
        if state.mission_status != MISSION_PAUSED:
            raise ValueError("Нет приостановленной миссии")
        state.collision = False
        state.mission_status = MISSION_RUNNING
        state.mode = "Тестовая миссия"
        self.note(platform_id, "Тестовая миссия возобновлена оператором.")

    def cancel_mission(self, platform_id: str) -> None:
        state, adapter = self._get(platform_id)
        if state.connected:
            adapter.halt()
            self._apply_snapshot(state, adapter.tick(0.0))
        self._clear_input(state)
        state.speed = 0.0
        state.collision = False
        state.mission_status = MISSION_CANCELLED
        state.mode = "Ожидание" if state.connected else "Отключена"
        self.note(platform_id, "Тестовая миссия отменена.")

    def reset(self, platform_id: str) -> None:
        state, adapter = self._get(platform_id)
        self._apply_snapshot(state, adapter.reset())
        state.collision = False
        self._clear_input(state)
        state.route = []
        state.waypoint_index = 0
        state.mission_status = MISSION_IDLE
        state.mode = "Ожидание" if state.connected else "Отключена"
        state.telemetry_age_s = 0.0 if state.connected else None
        self.note(platform_id, "Программная заглушка сброшена в начальное состояние.")

    def tick(self, dt: float) -> None:
        dt = finite_number(dt, "Шаг времени")
        if not 0 <= dt <= 60:
            raise ValueError("Шаг времени должен быть в диапазоне [0; 60] секунд")
        if dt == 0:
            return
        steps = max(1, math.ceil(dt / 0.05))
        step = dt / steps
        for _ in range(steps):
            self._elapsed += step
            for platform_id, state in self.platforms.items():
                adapter = self._adapters[platform_id]
                if not state.connected:
                    if state.telemetry_age_s is not None:
                        state.telemetry_age_s += step
                    continue
                if state.mission_status == MISSION_RUNNING:
                    self._advance_mission(state, adapter)
                else:
                    received = self._last_manual_command[platform_id]
                    if received is not None and self._elapsed - received > self.MANUAL_TIMEOUT_S + 1e-9:
                        was_moving = bool(state.desired_forward or state.desired_turn)
                        self._clear_input(state)
                        if was_moving:
                            adapter.halt()
                            state.mode = "Ожидание"
                            self.note(platform_id, "Истёк срок ручной команды; тестовое движение остановлено.", "WARNING")
                collision_before = state.collision
                self._apply_snapshot(state, adapter.tick(step))
                if state.collision and not collision_before:
                    self.note(platform_id, "Контакт с препятствием учебной среды; движение остановлено. Автоматический объезд не реализован.", "WARNING")
                    if state.mission_status == MISSION_RUNNING:
                        adapter.halt()
                        state.mission_status = MISSION_PAUSED
                        state.mode = "Миссия приостановлена"

    def export_snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "source": TEST_DATA_SOURCE,
            "coordinate_system": "Локальное учебное поле в метрах; курс против часовой от +X",
            "bounds": {"width": self.WIDTH, "height": self.HEIGHT},
            "platforms": [
                {
                    "id": state.info.id, "name": state.info.name, "kind": state.info.kind,
                    "source": state.info.source, "connected": state.connected,
                    "description": state.info.description,
                    "capabilities": list(state.info.capabilities),
                    "mode": state.mode,
                    "pose": {"x": state.pose.x, "y": state.pose.y, "heading": state.pose.heading},
                    "pose_source": "Синтетическая локализация: одометрия + курс",
                    "yaw_rate_deg_s": state.yaw_rate_deg_s,
                    "collision": state.collision,
                    "speed": state.speed, "telemetry_age_s": state.telemetry_age_s,
                    "fields": {key: {"label": value.label, "unit": value.unit,
                                     "value": value.value, "semantic": value.semantic}
                               for key, value in state.fields.items()},
                    "route": [{"x": point.x, "y": point.y} for point in state.route],
                    "mission_status": state.mission_status, "waypoint_index": state.waypoint_index,
                }
                for state in self.platforms.values()
            ],
            "events": [
                {"time": event.time.isoformat(), "platform_id": event.platform_id,
                 "message": event.message, "level": event.level}
                for event in self.events
            ],
        }

    def _advance_mission(self, state: State, adapter: RobotAdapter) -> None:
        while state.waypoint_index < len(state.route):
            target = state.route[state.waypoint_index]
            dx, dy = target.x - state.pose.x, target.y - state.pose.y
            distance = math.hypot(dx, dy)
            boat = state.info.kind == "БЭК"
            final = state.waypoint_index == len(state.route) - 1
            reach = (0.8 if final else 2.5) if boat else 0.4
            if distance <= reach and (not final or not boat or state.speed <= 0.85):
                state.waypoint_index += 1
                self.note(state.info.id, f"Достигнута тестовая точка {state.waypoint_index}/{len(state.route)}.")
                continue
            # Look ahead toward the following leg before reaching a boat's
            # corner. Waypoints guide a curved track, never assign pose/yaw.
            if boat and not final:
                lookahead = max(4.0, state.speed * 2.0)
                if distance < lookahead:
                    following = state.route[state.waypoint_index + 1]
                    length = math.hypot(following.x - target.x, following.y - target.y)
                    blend = min(1.0, (lookahead - distance) / max(length, 1e-6))
                    dx += (following.x - target.x) * blend
                    dy += (following.y - target.y) * blend
            desired_heading = math.degrees(math.atan2(dy, dx))
            error = (desired_heading - state.pose.heading + 180.0) % 360.0 - 180.0
            if boat:
                # Rate damping reduces Nomoto lag/overshoot. Never request zero
                # thrust solely for a 90-degree error: a rudder needs flow.
                turn = max(-1.0, min(1.0, (error - 1.8 * state.yaw_rate_deg_s) / 28.0))
                alignment = max(0.28, math.cos(math.radians(error)))
                stopping_speed = math.sqrt(2.0 * 0.30 * max(0.0, distance - 0.55))
                forward = min(0.65, stopping_speed / 4.0 if final else 0.65) * alignment
                if distance > 0.8 and abs(error) > 35:
                    forward = max(0.19, forward)
            else:
                turn = max(-1.0, min(1.0, (error - 0.45 * state.yaw_rate_deg_s) / 45.0))
                alignment = max(0.0, math.cos(math.radians(error)))
                forward = min(0.65, distance / (5.0 if state.info.kind == "БПЛА" else 3.0)) * alignment
            adapter.set_velocity(forward, turn)
            return
        adapter.halt()
        state.mission_status = MISSION_COMPLETED
        state.speed = 0.0
        state.mode = "Ожидание"
        self.note(state.info.id, "Тестовая миссия завершена.")

    def _get(self, platform_id: str) -> tuple[State, RobotAdapter]:
        if platform_id not in self.platforms:
            raise ValueError(f"Неизвестная платформа: {platform_id}")
        return self.platforms[platform_id], self._adapters[platform_id]

    @staticmethod
    def _require_connection(state: State) -> None:
        if not state.connected:
            raise ValueError("Сначала подключите тестовый источник")

    @staticmethod
    def _require_capability(state: State, capability: str) -> None:
        if capability not in state.info.capabilities:
            name = "ручное управление" if capability == "manual" else "выполнение миссий"
            raise ValueError(f"Адаптер платформы не поддерживает {name}")

    def _clear_input(self, state: State) -> None:
        state.desired_forward = state.desired_turn = 0.0
        self._last_manual_command[state.info.id] = None

    @staticmethod
    def _apply_snapshot(state: State, snapshot: AdapterSnapshot) -> None:
        state.pose = snapshot.pose
        state.speed = snapshot.speed
        state.telemetry_age_s = 0.0
        state.sensor_frame = snapshot.sensor_frame
        state.true_pose = snapshot.true_pose
        state.yaw_rate_deg_s = snapshot.yaw_rate_deg_s
        # Keep contact visible after the instantaneous physics flag vanishes.
        # Only an explicit operator action acknowledges this warning; an idle
        # telemetry update or a zero command must not hide it on the next frame.
        state.collision = state.collision or snapshot.collision
        if (state.mission_status not in (MISSION_RUNNING, MISSION_PAUSED)
                and not (state.desired_forward or state.desired_turn)
                and state.mode in ("Ожидание", "Торможение")):
            state.mode = "Торможение" if state.speed > 0.03 or abs(state.yaw_rate_deg_s) > 0.1 else "Ожидание"
        for key, value in snapshot.values.items():
            if key in state.fields:
                state.fields[key].value = value
