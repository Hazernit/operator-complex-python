"""Известная учебная среда в метрах: прямоугольные препятствия и лучи.

Препятствия — горизонтальные сечения; это не карта реального помещения.
"""

from __future__ import annotations

import math

WIDTH, HEIGHT = 100.0, 70.0
OBSTACLES = ((32.0, 16.0, 39.0, 24.0),
             (48.0, 39.0, 58.0, 48.0),
             (69.0, 16.0, 76.0, 30.0),
             (75.0, 53.0, 83.0, 60.0))


def is_free(x: float, y: float, radius: float = 0.0) -> bool:
    if not radius <= x <= WIDTH - radius or not radius <= y <= HEIGHT - radius:
        return False
    return not any(left - radius <= x <= right + radius and
                   bottom - radius <= y <= top + radius
                   for left, bottom, right, top in OBSTACLES)


def raycast(x: float, y: float, heading_deg: float, max_range: float) -> float:
    """Ближайшее пересечение луча с прямоугольником или границей поля."""
    angle = math.radians(heading_deg)
    dx, dy = math.cos(angle), math.sin(angle)
    best = max_range
    if abs(dx) > 1e-12:
        best = min(best, max(0.0, ((WIDTH if dx > 0 else 0.0) - x) / dx))
    if abs(dy) > 1e-12:
        best = min(best, max(0.0, ((HEIGHT if dy > 0 else 0.0) - y) / dy))
    for left, bottom, right, top in OBSTACLES:
        near, far = 0.0, max_range
        for origin, direction, low, high in ((x, dx, left, right), (y, dy, bottom, top)):
            if abs(direction) < 1e-12:
                if not low <= origin <= high:
                    near, far = math.inf, -math.inf
                    break
            else:
                first, last = sorted(((low - origin) / direction, (high - origin) / direction))
                near, far = max(near, first), min(far, last)
        if near <= far and far >= 0:
            best = min(best, max(0.0, near))
    return best


def water_depth(x: float, y: float) -> float:
    """Учебная батиметрия, м; отдельный вертикальный эхолот, не горизонтальный луч."""
    return round(12.0 + 2.0 * math.sin(x / 15.0) * math.cos(y / 18.0), 2)
