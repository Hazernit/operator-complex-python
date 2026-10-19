"""A local demo map of the selected platform and its own route and trail."""
from __future__ import annotations

from collections import OrderedDict
import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath, QPen, QPolygonF, QWheelEvent
from PySide6.QtWidgets import QWidget

from .sensor_data import project_reading
from .world import OBSTACLES


class MapWidget(QWidget):
    waypoint_requested = Signal(float, float)
    platform_selected = Signal(str)

    PLATFORM_COLORS = {'БПЛА': '#6257d5', 'НРТК': '#6257d5', 'БЭК': '#6257d5'}
    DISCONNECTED_COLOR = '#9b9eab'
    ACCENT = '#6257d5'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 310)
        self.setMouseTracking(True)
        self.platforms = {}
        self.selected_id = None
        self.trails = {}
        self.embedded = False
        self.edit_route = True
        self.zoom = 1.0
        self.pan = QPointF()
        self._drag = None
        self._hover = None
        self.bounds = (0.0, 100.0, 0.0, 70.0)
        self.sensor_frame = None
        self.draw_sensors = True
        self.draw_points = True
        self.draw_rays = True
        self.draw_world = False
        self.draw_plan = True
        self._clouds = {}
        self._last_scan = {}
        self.setToolTip(
            'На карте отображается только выбранная платформа. Переключение — в списке устройств слева. '
            'Серый маркер: нет связи; янтарный: данные устарели. '
            'Левая кнопка на свободном месте: точка маршрута. Колесо: масштаб. '
            'Правая или средняя кнопка: перемещение карты.'
        )

    @staticmethod
    def _draw_platform(painter, kind, color):
        """Draw every platform facing local +X; the caller applies its heading."""
        painter.setPen(QPen(QColor('#ffffff'), 1.5))
        painter.setBrush(color)
        if kind == 'БПЛА':
            painter.setPen(QPen(QColor('#ffffff'), 5))
            painter.drawLine(QPointF(-7, -7), QPointF(7, 7))
            painter.drawLine(QPointF(-7, 7), QPointF(7, -7))
            painter.setPen(QPen(color, 3))
            painter.drawLine(QPointF(-7, -7), QPointF(7, 7))
            painter.drawLine(QPointF(-7, 7), QPointF(7, -7))
            painter.setPen(QPen(QColor('#ffffff'), 1.5))
            for x, y in ((-7, -7), (-7, 7), (7, -7), (7, 7)):
                painter.drawEllipse(QPointF(x, y), 4, 4)
            painter.drawPolygon(QPolygonF([
                QPointF(14, 0), QPointF(0, -4), QPointF(-7, 0), QPointF(0, 4),
            ]))
        elif kind == 'НРТК':
            for x, y in ((-8, -11), (3, -11), (-8, 7), (3, 7)):
                painter.drawRoundedRect(QRectF(x, y, 6, 4), 1, 1)
            painter.drawRoundedRect(QRectF(-11, -7, 21, 14), 2, 2)
            painter.drawPolygon(QPolygonF([QPointF(14, 0), QPointF(6, -5), QPointF(6, 5)]))
        elif kind == 'БЭК':
            painter.drawPolygon(QPolygonF([
                QPointF(15, 0), QPointF(5, -8), QPointF(-12, -7),
                QPointF(-12, 7), QPointF(5, 8),
            ]))
            painter.drawRoundedRect(QRectF(-7, -4, 10, 8), 1, 1)
        else:
            painter.drawPolygon(QPolygonF([
                QPointF(13, 0), QPointF(-9, -8), QPointF(-5, 0), QPointF(-9, 8),
            ]))

    def _font(self, size=9, weight=QFont.Weight.Normal):
        font = QFont(self.font())
        font.setPointSizeF(size)
        font.setWeight(weight)
        return font

    def _draw_legend(self, painter):
        painter.setFont(self._font(8))
        x = 19
        for text, color, dashed in [
            ('Маршрут', self.ACCENT, True), ('Трек', '#9890de', False),
            ('LiDAR', '#4a9b9e', False), ('Сонар', '#bd914b', False),
        ]:
            painter.setPen(QPen(QColor(color), 1.7,
                                Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine))
            painter.drawLine(QPointF(x, 43), QPointF(x + 12, 43))
            painter.setPen(QColor('#858594'))
            painter.drawText(QPointF(x + 18, 46), text)
            x += 90 if text == 'Маршрут' else 73

    @staticmethod
    def _data_status(state):
        """Reflect received state only; painting never advances simulation time."""
        if not state.connected:
            return 'Нет связи', '#9396a4', True
        age = state.telemetry_age_s
        if age is None:
            return 'Нет телеметрии', '#b48742', True
        if age > 2:
            return f'Данные {age:.1f} с', '#b48742', True
        return 'Позиция', MapWidget.ACCENT, False

    def reset_observations(self, platform_id):
        self._clouds.pop(platform_id, None)
        self._last_scan.pop(platform_id, None)

    def ingest_frame(self, platform_id, frame):
        if frame is None:
            return
        timestamp = frame.reading_time_s if frame.reading_time_s is not None else frame.time_s
        key = (frame.source, timestamp)
        if self._last_scan.get(platform_id) == key:
            return
        self._last_scan[platform_id] = key
        cloud = self._clouds.setdefault(platform_id, OrderedDict())
        for reading in frame.readings:
            # A sonar echo is an arc, not an accurately localized obstacle point.
            if reading.sensor != 'lidar' or not reading.hit:
                continue
            _, _, x, y = project_reading(frame, reading)
            cell = (round(x * 4), round(y * 4))
            cloud[cell] = (x, y)
            cloud.move_to_end(cell)
        while len(cloud) > 12000:
            cloud.popitem(last=False)

    def _draw_sensor_layers(self, painter):
        if self.draw_points:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor('#7eb3b5'))
            for x, y in self._clouds.get(self.selected_id, {}).values():
                painter.drawEllipse(self.world_to_screen(x, y), 1.8, 1.8)
        if not self.draw_sensors or self.sensor_frame is None:
            return
        frame = self.sensor_frame
        for reading in frame.readings[::max(1, math.ceil(len(frame.readings) / 1500))]:
            ox, oy, ex, ey = project_reading(frame, reading)
            origin, endpoint = self.world_to_screen(ox, oy), self.world_to_screen(ex, ey)
            if reading.sensor == 'lidar':
                if self.draw_rays:
                    painter.setPen(QPen(QColor(74, 155, 158, 32), 1))
                    painter.drawLine(origin, endpoint)
                if reading.hit:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor('#438f93'))
                    painter.drawEllipse(endpoint, 2.6, 2.6)
            else:
                pose = reading.measurement_pose or frame.reading_pose or frame.pose
                bearing = pose.heading + reading.yaw_offset_deg + reading.angle_deg
                half = reading.fov_deg / 2
                angles = [bearing - half + reading.fov_deg * i / 20 for i in range(21)]
                arc = [self.world_to_screen(ox + reading.range_m * math.cos(math.radians(a)), oy + reading.range_m * math.sin(math.radians(a))) for a in angles]
                path = QPainterPath(origin)
                path.lineTo(arc[0])
                for point in arc[1:]:
                    path.lineTo(point)
                path.closeSubpath()
                painter.fillPath(path, QColor(189, 145, 75, 17))
                painter.setPen(QPen(QColor(189, 145, 75, 65), 1))
                painter.drawLine(origin, arc[0])
                painter.drawLine(origin, arc[-1])
                painter.setPen(QPen(QColor('#bd914b'), 1.6, Qt.PenStyle.SolidLine if reading.hit else Qt.PenStyle.DashLine))
                painter.drawPolyline(QPolygonF(arc))

    def _visible_platforms(self):
        state = self.platforms.get(self.selected_id)
        return {self.selected_id: state} if state is not None else {}

    def _viewport_rect(self):
        return QRectF(12, 33 if self.embedded else 58, self.width() - 24, self.height() - (79 if self.embedded else 104))

    def _map_area(self):
        return QRectF(self.rect().adjusted(46, 44 if self.embedded else 69, -28, -72))

    def _transform(self):
        area = self._map_area()
        xmin, xmax, ymin, ymax = self.bounds
        scale = min(area.width() / (xmax - xmin), area.height() / (ymax - ymin)) * self.zoom
        origin = QPointF(area.center().x() - (xmin + xmax) / 2 * scale, area.center().y() + (ymin + ymax) / 2 * scale) + self.pan
        return origin, scale

    def world_to_screen(self, x, y):
        origin, scale = self._transform()
        return QPointF(origin.x() + x * scale, origin.y() - y * scale)

    def screen_to_world(self, point):
        origin, scale = self._transform()
        return (point.x() - origin.x()) / scale, (origin.y() - point.y()) / scale

    def fit_map(self):
        self.zoom = 1.0
        self.pan = QPointF()
        self.update()

    def _set_zoom(self, value, anchor=None):
        world_anchor = self.screen_to_world(anchor) if anchor is not None else None
        self.zoom = min(3.0, max(0.65, value))
        if anchor is not None:
            self.pan += anchor - self.world_to_screen(*world_anchor)
        self.update()

    def zoom_in(self):
        self._set_zoom(self.zoom * 1.2)

    def zoom_out(self):
        self._set_zoom(self.zoom / 1.2)

    def center_selected(self):
        state = self.platforms.get(self.selected_id)
        if state is not None:
            self.pan += self._map_area().center() - self.world_to_screen(state.pose.x, state.pose.y)
            self.update()

    def _draw_grid(self, painter, world_rect):
        xmin, xmax, ymin, ymax = self.bounds
        _, scale = self._transform()
        raw_step = max((xmax - xmin) / 10, (ymax - ymin) / 7)
        power = 10 ** math.floor(math.log10(raw_step))
        step = next(factor * power for factor in (1, 2, 5, 10) if factor * power >= raw_step)
        xs = [index * step for index in range(math.ceil(xmin / step), math.floor(xmax / step) + 1)]
        ys = [index * step for index in range(math.ceil(ymin / step), math.floor(ymax / step) + 1)]
        painter.fillRect(world_rect, QColor('#fcfcfe'))
        if step * scale >= 45:
            minor_step = step / 5
            painter.setPen(QPen(QColor('#f0f0f5'), 0.8))
            for index in range(math.ceil(xmin / minor_step), math.floor(xmax / minor_step) + 1):
                x = index * minor_step
                painter.drawLine(self.world_to_screen(x, ymin), self.world_to_screen(x, ymax))
            for index in range(math.ceil(ymin / minor_step), math.floor(ymax / minor_step) + 1):
                y = index * minor_step
                painter.drawLine(self.world_to_screen(xmin, y), self.world_to_screen(xmax, y))
        painter.setPen(QPen(QColor('#e7e7ef'), 1))
        for x in xs:
            painter.drawLine(self.world_to_screen(x, ymin), self.world_to_screen(x, ymax))
        for y in ys:
            painter.drawLine(self.world_to_screen(xmin, y), self.world_to_screen(xmax, y))
        painter.setPen(QPen(QColor('#d5d5e1'), 1))
        painter.drawRect(world_rect)
        painter.setFont(self._font(8))
        painter.setPen(QColor('#a0a0ae'))
        for x in xs:
            p = self.world_to_screen(x, ymin)
            painter.drawText(QRectF(p.x() - 25, p.y() + 6, 50, 18), Qt.AlignmentFlag.AlignCenter, f'{x:g}')
        for y in ys:
            p = self.world_to_screen(xmin, y)
            painter.drawText(QRectF(p.x() - 37, p.y() - 9, 30, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f'{y:g}')

    def _draw_route(self, painter, state):
        trail = self.trails.get(self.selected_id, [])
        if len(trail) > 1:
            points = QPolygonF([self.world_to_screen(*p) for p in trail])
            painter.setPen(QPen(QColor('#ffffff'), 5, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawPolyline(points)
            painter.setPen(QPen(QColor('#9890de'), 2.5, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawPolyline(points)
        if not state.route or not self.draw_plan:
            return
        points = [self.world_to_screen(point.x, point.y) for point in state.route]
        painter.setPen(QPen(QColor('#ffffff'), 4.5))
        painter.drawPolyline(QPolygonF(points))
        painter.setPen(QPen(QColor(self.ACCENT), 1.7, Qt.PenStyle.DashLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPolyline(QPolygonF(points))
        if state.active_target is not None:
            target = self.world_to_screen(state.active_target.x, state.active_target.y)
            painter.setPen(QPen(QColor('#b6afe9'), 1, Qt.PenStyle.DashLine))
            painter.drawLine(self.world_to_screen(state.pose.x, state.pose.y), target)
        painter.setFont(self._font(8, QFont.Weight.DemiBold))
        for i, point in enumerate(points):
            active = i == state.waypoint_index and state.active_target is not None
            complete = i < state.waypoint_index
            if active:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor('#e9e6fa'))
                painter.drawEllipse(point, 16, 16)
            painter.setPen(QPen(QColor('#c8c3e9' if complete else self.ACCENT), 1.5))
            painter.setBrush(QColor(self.ACCENT if active else '#f0eefb' if complete else '#ffffff'))
            painter.drawEllipse(point, 8, 8)
            painter.setPen(QColor('#ffffff' if active else '#9e97c8' if complete else self.ACCENT))
            painter.drawText(QRectF(point.x() - 8, point.y() - 8, 16, 16), Qt.AlignmentFlag.AlignCenter, str(i + 1))

    def _draw_marker(self, painter, platform_id, platform):
        point = self.world_to_screen(platform.pose.x, platform.pose.y)
        status, status_color, old = self._data_status(platform)
        color = QColor(status_color)
        halo = QColor(status_color)
        halo.setAlpha(22)
        painter.setPen(QPen(QColor('#ffffff'), 3))
        painter.setBrush(halo)
        painter.drawEllipse(point, 24, 24)
        painter.setPen(QPen(color, 1.2, Qt.PenStyle.DashLine if old else Qt.PenStyle.SolidLine))
        painter.setBrush(QColor('#ffffff'))
        painter.drawEllipse(point, 21, 21)
        painter.save()
        painter.translate(point)
        painter.rotate(-platform.pose.heading)
        self._draw_platform(painter, platform.info.kind, color)
        # Heading indicator uses the same local +X convention as the data model.
        painter.setPen(QPen(color, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(27, 0), QPointF(34, 0))
        painter.drawLine(QPointF(31, -3), QPointF(34, 0))
        painter.drawLine(QPointF(31, 3), QPointF(34, 0))
        painter.restore()
        painter.setFont(self._font(9, QFont.Weight.DemiBold))
        title = f'{platform.info.kind} · {platform_id}'
        label_width = max(110, painter.fontMetrics().horizontalAdvance(title) + 22,
                          painter.fontMetrics().horizontalAdvance(status) + 22)
        label_rect = QRectF(point.x() + 30, point.y() - 23, label_width, 45)
        viewport = self._viewport_rect()
        if label_rect.right() > viewport.right() - 8:
            label_rect.moveRight(point.x() - 29)
        label_rect.moveTop(max(viewport.top() + 4, min(label_rect.top(), viewport.bottom() - 49)))
        painter.setPen(QPen(QColor('#e4e3ed'), 1))
        painter.setBrush(QColor(255, 255, 255, 245))
        painter.drawRoundedRect(label_rect, 7, 7)
        painter.setPen(QColor('#373541'))
        painter.drawText(QPointF(label_rect.left() + 10, label_rect.top() + 17), title)
        painter.setFont(self._font(8))
        painter.setPen(color)
        painter.drawText(QPointF(label_rect.left() + 10, label_rect.top() + 33), status)

    def _draw_footer(self, painter):
        _, scale = self._transform()
        raw_distance = 70 / scale
        power = 10 ** math.floor(math.log10(raw_distance))
        distance = max(factor * power for factor in (1, 2, 5, 10) if factor * power <= raw_distance)
        length = distance * scale
        y = self.height() - 17
        painter.setFont(self._font(8))
        painter.setPen(QColor('#858491'))
        painter.drawText(QPointF(19, y - 7), f'{distance:g} м')
        painter.setPen(QPen(QColor('#858491'), 1.2))
        painter.drawLine(QPointF(19, y), QPointF(19 + length, y))
        painter.drawLine(QPointF(19, y - 3), QPointF(19, y + 2))
        painter.drawLine(QPointF(19 + length, y - 3), QPointF(19 + length, y + 2))
        painter.setPen(QColor('#9897a3'))
        if self._hover is not None:
            x, world_y = self.screen_to_world(self._hover)
            text = f'X {x:.1f}   Y {world_y:.1f} м   ·   {self.zoom:.0%}'
        else:
            text = f'Локальные координаты   ·   {self.zoom:.0%}'
        painter.drawText(QRectF(105, self.height() - 36, self.width() - 125, 28),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor('#ffffff'))
        painter.setPen(QPen(QColor('#e8e7ef'), 1))
        header_bottom = 31 if self.embedded else 56
        painter.drawLine(QPointF(12, header_bottom), QPointF(self.width() - 12, header_bottom))
        if not self.embedded:
            painter.setFont(self._font(11, QFont.Weight.DemiBold))
            painter.setPen(QColor('#3b3949'))
            painter.drawText(QPointF(19, 24), 'Локальная карта')
        painter.setFont(self._font(8))
        painter.setPen(QColor('#9998a5'))
        painter.drawText(QRectF(205, 9, self.width() - 224, 22),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, 'Y ↑   X →')
        painter.save()
        if self.embedded:
            painter.translate(0, -25)
        self._draw_legend(painter)
        painter.restore()
        xmin, xmax, ymin, ymax = self.bounds
        world_rect = QRectF(self.world_to_screen(xmin, ymax), self.world_to_screen(xmax, ymin))
        painter.save()
        painter.setClipRect(self._viewport_rect())
        painter.fillRect(self._viewport_rect(), QColor('#f8f8fb'))
        self._draw_grid(painter, world_rect)
        painter.setClipRect(world_rect, Qt.ClipOperation.IntersectClip)
        if self.draw_world:
            painter.setPen(QPen(QColor('#d5d4df'), 1))
            painter.setBrush(QColor('#ecebf2'))
            for x0, y0, x1, y1 in OBSTACLES:
                # The stored rectangles remain exact: rounding would imply free corners.
                painter.drawRect(QRectF(self.world_to_screen(x0, y1), self.world_to_screen(x1, y0)))
        state = self.platforms.get(self.selected_id)
        painter.save()
        if state is not None and self._data_status(state)[2]:
            painter.setOpacity(0.5)
        self._draw_sensor_layers(painter)
        painter.restore()
        if state is not None:
            self._draw_route(painter, state)
        painter.restore()
        painter.save()
        painter.setClipRect(self._viewport_rect())
        for platform_id, platform in self._visible_platforms().items():
            self._draw_marker(painter, platform_id, platform)
        if state is None:
            painter.setFont(self._font(10, QFont.Weight.DemiBold))
            painter.setPen(QColor('#858291'))
            painter.drawText(self._viewport_rect(), Qt.AlignmentFlag.AlignCenter,
                             'Выберите платформу в списке слева')
        painter.restore()
        self._draw_footer(painter)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._drag = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif event.button() == Qt.MouseButton.LeftButton:
            # Prefer the nearest marker over editing the route, even when both are enabled.
            hit = None
            nearest_distance = 18 ** 2
            for platform_id, platform in self._visible_platforms().items():
                point = self.world_to_screen(platform.pose.x, platform.pose.y)
                delta = event.position() - point
                distance = delta.x() ** 2 + delta.y() ** 2
                if distance <= nearest_distance:
                    nearest_distance = distance
                    hit = platform_id
            if hit is not None:
                self.platform_selected.emit(hit)
                event.accept()
                return
            if (self.edit_route and self.selected_id in self.platforms
                    and self._viewport_rect().contains(event.position())):
                x, y = self.screen_to_world(event.position())
                if 0 <= x <= 100 and 0 <= y <= 70:
                    self.waypoint_requested.emit(round(x, 2), round(y, 2))

    def mouseMoveEvent(self, event: QMouseEvent):
        self._hover = event.position() if self._viewport_rect().contains(event.position()) else None
        if self._drag is not None:
            self.pan += event.position() - self._drag
            self._drag = event.position()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag = None
        self.unsetCursor()

    def leaveEvent(self, event):
        self._hover = None
        self.update()
        super().leaveEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        if delta:
            self._set_zoom(self.zoom * (1.12 if delta > 0 else 1 / 1.12), event.position())
        event.accept()
