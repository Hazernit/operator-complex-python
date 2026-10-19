"""Заменяемые адаптеры данных платформ."""

from .base import AdapterSnapshot, RobotAdapter
from .mock import MockAdapter

__all__ = ["AdapterSnapshot", "RobotAdapter", "MockAdapter"]

