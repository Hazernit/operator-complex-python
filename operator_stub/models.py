"""Модели операторской заглушки, независимые от интерфейса и транспорта."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .sensor_data import SensorFrame


TEST_DATA_SOURCE = "Тестовые данные"
MISSION_IDLE = "IDLE"
MISSION_RUNNING = "RUNNING"
MISSION_PAUSED = "PAUSED"
MISSION_COMPLETED = "COMPLETED"
MISSION_CANCELLED = "CANCELLED"
MISSION_LABELS = {
    MISSION_IDLE: "Не запущена",
    MISSION_RUNNING: "Выполняется",
    MISSION_PAUSED: "Приостановлена",
    MISSION_COMPLETED: "Завершена",
    MISSION_CANCELLED: "Отменена",
}


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass
class Pose:
    """Локальное положение в метрах; курс в градусах против часовой от +X."""

    x: float = 0.0
    y: float = 0.0
    heading: float = 0.0


@dataclass(frozen=True)
class PlatformInfo:
    id: str
    name: str
    kind: str
    source: str = TEST_DATA_SOURCE
    description: str = "Программная заглушка; оборудование и протокол ещё не определены"
    capabilities: tuple[str, ...] = ("manual", "mission")


@dataclass
class TelemetryField:
    key: str
    label: str
    unit: str = ""
    value: Any = None
    source: str = TEST_DATA_SOURCE
    semantic: str | None = None


@dataclass
class State:
    info: PlatformInfo
    connected: bool = False
    pose: Pose = field(default_factory=Pose)
    speed: float = 0.0
    fields: dict[str, TelemetryField] = field(default_factory=dict)
    route: list[Point] = field(default_factory=list)
    mission_status: str = MISSION_IDLE
    waypoint_index: int = 0
    mode: str = "Отключена"
    desired_forward: float = 0.0
    desired_turn: float = 0.0
    telemetry_age_s: float | None = None
    sensor_frame: SensorFrame | None = None
    true_pose: Pose | None = None
    yaw_rate_deg_s: float = 0.0
    collision: bool = False

    @property
    def active_target(self) -> Point | None:
        if self.mission_status in (MISSION_RUNNING, MISSION_PAUSED):
            if self.waypoint_index < len(self.route):
                return self.route[self.waypoint_index]
        return None


@dataclass(frozen=True)
class Event:
    time: datetime
    platform_id: str
    message: str
    level: str = "INFO"

