"""Граница между общим приложением и сменным источником данных.

Реальный адаптер в будущем преобразует согласованные сообщения оборудования
в AdapterSnapshot. Сам интерфейс не устанавливает сетевые соединения и не
обещает поддержку неизвестного оборудования.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from operator_stub.models import PlatformInfo, Pose, TelemetryField

if TYPE_CHECKING:
    from operator_stub.sensor_data import SensorFrame


@dataclass
class AdapterSnapshot:
    pose: Pose
    speed: float
    values: dict[str, Any]
    sensor_frame: SensorFrame | None = None
    true_pose: Pose | None = None
    yaw_rate_deg_s: float = 0.0
    collision: bool = False


class RobotAdapter(ABC):
    info: PlatformInfo
    initial_pose: Pose
    field_specs: dict[str, TelemetryField]

    @abstractmethod
    def connect(self) -> AdapterSnapshot:
        """Подключиться и вернуть подтверждённое начальное состояние."""

    @abstractmethod
    def disconnect(self) -> None:
        """Прекратить сеанс и сбросить отложенные команды."""

    @abstractmethod
    def set_velocity(self, forward: float, turn: float) -> None:
        """Задать нормированный демонстрационный ввод, диапазон [-1; 1]."""

    def halt(self) -> None:
        """Немедленная остановка учебной среды; реальный адаптер определит свой STOP."""
        self.set_velocity(0.0, 0.0)

    @abstractmethod
    def tick(self, dt: float) -> AdapterSnapshot:
        """Получить следующее состояние, не блокируя поток интерфейса."""

    @abstractmethod
    def reset(self) -> AdapterSnapshot:
        """Сбросить только демонстрационную модель."""

