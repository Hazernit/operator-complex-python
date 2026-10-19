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

    PLATFORM_COLORS = {'БПЛА': '#5475b8', 'НРТК': '#d59635', 'БЭК': '#218ca4'}
    DISCONNECTED_COLOR = '#9ba8b8'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 310)
        self.setMouseTracking(True)
        self.platforms = {}
        self.selected_id = None
        self.trails = {}
        self.edit_route = True
        self.zoom = 1.0
        self.pan = QPointF()
        self._drag = None
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
            'Серый цвет означает отсутствие связи. '
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

    def _draw_legend(self, painter):
        painter.setFont(QFont('Arial', 8))
        x = 12
        for text, color in [('План', '#1b9b85'), ('Трек', '#386cbd'), ('LiDAR', '#139dad'), ('Сонар', '#dd982f')]:
            painter.setPen(QPen(QColor(color), 2))
            painter.drawLine(QPointF(x, 32), QPointF(x + 10, 32))
            painter.setPen(QColor('#64748b'))
            painter.drawText(QPointF(x + 14, 36), text)
            x += 77

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
            painter.setBrush(QColor('#409bb1'))
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
                    painter.setPen(QPen(QColor(19, 157, 173, 45), 1))
                    painter.drawLine(origin, endpoint)
                if reading.hit:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor('#078b9d'))
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
                painter.fillPath(path, QColor(221, 152, 47, 23))
                painter.setPen(QPen(QColor(221, 152, 47, 80), 1))
                painter.drawLine(origin, arc[0])
                painter.drawLine(origin, arc[-1])
                painter.setPen(QPen(QColor('#dd982f'), 2, Qt.PenStyle.SolidLine if reading.hit else Qt.PenStyle.DashLine))
                painter.drawPolyline(QPolygonF(arc))

    def _visible_platforms(self):
        state = self.platforms.get(self.selected_id)
        return {self.selected_id: state} if state is not None else {}

    def _transform(self):
        area = self.rect().adjusted(45, 58, -24, -38)
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

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor('#f8fafc'))
        painter.setFont(QFont('Arial', 9))
        xmin, xmax, ymin, ymax = self.bounds
        top_left = self.world_to_screen(xmin, ymax)
        bottom_right = self.world_to_screen(xmax, ymin)
        world_rect = QRectF(top_left, bottom_right)
        painter.fillRect(world_rect, QColor('#ffffff'))
        raw_step = max((xmax - xmin) / 10, (ymax - ymin) / 7)
        power = 10 ** math.floor(math.log10(raw_step))
        step = next(factor * power for factor in (1, 2, 5, 10) if factor * power >= raw_step)
        xs = [index * step for index in range(math.ceil(xmin / step), math.floor(xmax / step) + 1)]
        ys = [index * step for index in range(math.ceil(ymin / step), math.floor(ymax / step) + 1)]
        painter.setPen(QPen(QColor('#e3ebf3'), 1))
        for x in xs:
            painter.drawLine(self.world_to_screen(x, ymin), self.world_to_screen(x, ymax))
        for y in ys:
            painter.drawLine(self.world_to_screen(xmin, y), self.world_to_screen(xmax, y))
        painter.setPen(QPen(QColor('#c1cede'), 1))
        painter.drawRect(world_rect)
        painter.setPen(QColor('#7b899b'))
        for x in xs:
            p = self.world_to_screen(x, ymin)
            painter.drawText(QRectF(p.x() - 25, p.y() + 6, 50, 20), Qt.AlignmentFlag.AlignCenter, f'{x:g}')
        for y in ys:
            p = self.world_to_screen(xmin, y)
            painter.drawText(QRectF(p.x() - 43, p.y() - 9, 37, 18), Qt.AlignmentFlag.AlignRight, f'{y:g}')

        painter.save()
        painter.setClipRect(world_rect)
        if self.draw_world:
            painter.setPen(QPen(QColor('#b8c4cf'), 1))
            painter.setBrush(QColor('#e4e9ef'))
            for x0, y0, x1, y1 in OBSTACLES:
                painter.drawRect(QRectF(self.world_to_screen(x0, y1), self.world_to_screen(x1, y0)))
        self._draw_sensor_layers(painter)

        state = self.platforms.get(self.selected_id)
        if state:
            trail = self.trails.get(self.selected_id, [])
            if len(trail) > 1:
                painter.setPen(QPen(QColor('#386cbd'), 2.5))
                painter.drawPolyline(QPolygonF([self.world_to_screen(*p) for p in trail]))
            if state.route and self.draw_plan:
                points = [self.world_to_screen(point.x, point.y) for point in state.route]
                painter.setPen(QPen(QColor('#1b9b85'), 2, Qt.PenStyle.DashLine))
                painter.drawPolyline(QPolygonF(points))
                for i, point in enumerate(points):
                    painter.setPen(QPen(QColor('#178c78'), 2))
                    painter.setBrush(QColor('#d5f1e9' if i != state.waypoint_index else '#178c78'))
                    painter.drawEllipse(point, 7, 7)
                    painter.setPen(QColor('#173a35'))
                    painter.drawText(point + QPointF(9, -9), str(i + 1))
        for platform_id, platform in self._visible_platforms().items():
            point = self.world_to_screen(platform.pose.x, platform.pose.y)
            color = QColor(self.PLATFORM_COLORS.get(platform.info.kind, '#64748b'))
            if not platform.connected:
                color = QColor(self.DISCONNECTED_COLOR)
            if platform_id == self.selected_id:
                painter.setPen(QPen(QColor('#168f7a'), 2))
                painter.setBrush(QColor('#20168f7a'))
                painter.drawEllipse(point, 20, 20)
            painter.save()
            painter.translate(point)
            painter.rotate(-platform.pose.heading)
            self._draw_platform(painter, platform.info.kind, color)
            painter.restore()
            painter.setPen(QColor('#21354d'))
            painter.setFont(QFont('Arial', 10, QFont.Weight.Bold))
            painter.drawText(point + QPointF(15, 19), f'{platform.info.kind} · {platform_id}')
        painter.restore()
        painter.setPen(QColor('#7b899b'))
        painter.setFont(QFont('Arial', 9))
        painter.drawText(12, 19, 'ВЫБРАННАЯ ПЛАТФОРМА · XY, МЕТРЫ · ДАННЫЕ ДАТЧИКОВ')
        self._draw_legend(painter)
        if not state:
            painter.drawText(12, self.height() - 8, 'Выберите устройство в списке слева')
        elif not state.route:
            painter.drawText(12, self.height() - 8, 'Добавьте точки левой кнопкой мыши' if self.edit_route else 'Редактирование маршрута выключено')
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
            if self.edit_route and self.selected_id in self.platforms:
                x, y = self.screen_to_world(event.position())
                if 0 <= x <= 100 and 0 <= y <= 70:
                    self.waypoint_requested.emit(round(x, 2), round(y, 2))

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag is not None:
            self.pan += event.position() - self._drag
            self._drag = event.position()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag = None
        self.unsetCursor()

    def wheelEvent(self, event: QWheelEvent):
        self.zoom = min(3.0, max(0.65, self.zoom * (1.12 if event.angleDelta().y() > 0 else 1 / 1.12)))
        self.update()
        event.accept()
