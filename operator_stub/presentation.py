"""Общие правила отображения статусов без зависимости от Qt и транспорта.

Назначение каналов задаёт адаптер через semantic. Их смысл не выводится
из названий датчиков: незнакомое оборудование может передавать любые поля.
Пороговые предупреждения демонстрационные и не управляют движением.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real

from .models import MISSION_PAUSED, State


@dataclass(frozen=True)
class Profile:
    title: str
    environment: str
    manual_hint: str
    limitation: str


@dataclass(frozen=True)
class Warning:
    code: str
    level: str
    message: str


_PROFILES = {
    "БПЛА": Profile(
        "БПЛА", "Воздушная среда",
        "W/S — движение, A/D — курс. Высота автоматически удерживается.",
        "Квадрокоптер: плавный разгон и торможение, инерция вектора скорости. Высота фиксирована: 8 м; полный 3D-полёт не моделируется.",
    ),
    "НРТК": Profile(
        "НРТК", "Наземная среда",
        "W/S — ход, A/D — дифференциальный поворот, в том числе на месте.",
        "Колёсный дифференциальный привод: ограничены разгон, торможение и скорость поворота. При контакте движение останавливается; автообъезд не реализован.",
    ),
    "БЭК": Profile(
        "БЭК", "Водная среда",
        "W/S — тяга, A/D — руль. Для поворота нужен ход.",
        "Катер с рулём: инерция хода и угловой скорости, поворот до 20°/с. Волны и течения не моделируются; параметры корпуса учебные.",
    ),
}

_FALLBACK = Profile(
    "Платформа", "Среда не определена",
    "Общие команды доступны согласно возможностям адаптера.",
    "Тип оборудования не определён. Состав данных и специальные команды уточняются при интеграции.",
)


def profile_for(kind: str) -> Profile:
    return _PROFILES.get(kind, _FALLBACK)


def metric_value(state: State, semantic: str) -> float | None:
    """Вернуть однозначное значение процента; неизвестное значение — None.

    Наличие значения не означает актуальность: состояние соединения и возраст
    телеметрии отображаются отдельно. Отключённый канал не считается нулевым.
    """
    fields = [field for field in state.fields.values() if field.semantic == semantic]
    if len(fields) != 1:
        return None
    value = fields[0].value
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return None
    return result if math.isfinite(result) and 0 <= result <= 100 else None


def warnings_for(state: State) -> list[Warning]:
    """Вычислить активные предупреждения без изменения состояния платформы."""
    result: list[Warning] = []
    if state.collision:
        result.append(Warning('collision', 'WARNING', 'Контакт с препятствием в учебной среде. Движение остановлено; измените маршрут или отведите платформу.'))
    if not state.connected:
        result.append(Warning(
            "offline", "WARNING",
            "Источник отключён. На карте сохранено последнее известное положение; показания не актуальны.",
        ))
    else:
        battery = metric_value(state, "battery_percent")
        link = metric_value(state, "link_quality_percent")
        if battery is None:
            result.append(Warning("battery_unknown", "WARNING", "Заряд батареи неизвестен: источник не передал корректное значение."))
        elif battery <= 20:
            result.append(Warning(
                "battery_low", "CRITICAL" if battery <= 10 else "WARNING",
                f"Низкий тестовый заряд батареи: {battery:g}%.",
            ))
        if link is None:
            result.append(Warning("link_unknown", "WARNING", "Качество связи неизвестно: источник не передал корректное значение."))
        elif link <= 30:
            result.append(Warning(
                "link_weak", "CRITICAL" if link <= 10 else "WARNING",
                f"Низкое тестовое качество связи: {link:g}%.",
            ))
        age = state.telemetry_age_s
        if isinstance(age, Real) and not isinstance(age, bool) and math.isfinite(age) and age > 2:
            result.append(Warning("telemetry_stale", "WARNING", f"Телеметрия устарела: последнее обновление {age:.1f} с назад."))
    if state.mission_status == MISSION_PAUSED:
        result.append(Warning("mission_paused", "INFO", "Миссия приостановлена. Продолжение требует команды оператора."))
    return result
