"""Desktop UI over a replaceable demo service. Widgets never contain protocol logic."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import replace
from html import escape
import json
from pathlib import Path
import sys
import time

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from .map_widget import MapWidget
from .models import Point
from .playback import RecordingPlayer
from .recording_loader import RecordingLoader
from .presentation import metric_value, profile_for, warnings_for
from .sensor_data import load_recording
from .service import OperatorService


STATUS = {
    'IDLE': 'Нет задания', 'RUNNING': 'Выполняется', 'PAUSED': 'Пауза',
    'COMPLETED': 'Завершено', 'CANCELLED': 'Отменено',
}

from .design import STYLE
from .workspace import WorkspaceMixin


def label(text, name=None, wrap=False):
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        result.setObjectName(name)
    result.setWordWrap(wrap)
    return result


def button(text, callback=None, name=None):
    result = QPushButton(text)
    if name:
        result.setObjectName(name)
    if callback:
        result.clicked.connect(callback)
    return result


class OperatorWindow(WorkspaceMixin, QMainWindow):
    def __init__(self, config_path=None):
        super().__init__()
        self.service = OperatorService(config_path)
        self.selected_id = next((p for p,s in self.service.platforms.items() if s.info.kind == 'НРТК'), next(iter(self.service.platforms)))
        self.trails = defaultdict(lambda: deque(maxlen=2000))
        self._manual = None
        self._keys = set()
        self._last_events = None
        self._active_alerts = {}
        self._replays = {}
        self._pending_imports = {}
        self._closing = False
        self.recording_loader = RecordingLoader(self)
        self.recording_loader.success.connect(self._recording_ready)
        self.recording_loader.failure.connect(self._recording_failed)
        self._last_tick = time.monotonic()
        self.setWindowTitle('Оператор · Единый комплекс · DEMO')
        self.resize(1440, 900)
        self.setMinimumSize(1100, 720)
        self.setStyleSheet(STYLE)
        self._build()
        QApplication.instance().installEventFilter(self)
        for platform_id in self.service.platforms:
            self.service.connect(platform_id)
        self._refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)
        self.statusBar().showMessage('Локальная симуляция и просмотр записей · физические роботы не подключены')

    @staticmethod
    def _scroll_page(page):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(page)
        return area

    def _build_sensor_page(self):
        page = QWidget()
        page.setMinimumHeight(215)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 8, 10, 5)
        layout.setSpacing(5)
        files = QHBoxLayout()
        self.load_sensor_button = button('Загрузить TXT', self._choose_sensor_file, 'primary')
        files.addWidget(self.load_sensor_button)
        self.example_choice = QComboBox()
        for name, filename in [('LiDAR · комната', 'lidar-room.txt'), ('Сонар · поворот катера', 'sonar-route.txt'), ('LiDAR + сонар', 'mixed-route.txt')]:
            self.example_choice.addItem(name, filename)
        files.addWidget(self.example_choice)
        self.sensor_example_button = button('Открыть пример', self._load_sensor_example)
        files.addWidget(self.sensor_example_button)
        self.return_simulation_button = button('К симуляции', self._leave_replay)
        files.addWidget(self.return_simulation_button)
        files.addStretch()
        layout.addLayout(files)
        self.sensor_source = label('', 'muted', True)
        layout.addWidget(self.sensor_source)
        playback = QHBoxLayout()
        self.play_button = button('Воспроизвести', self._toggle_playback)
        playback.addWidget(self.play_button)
        self.playhead = QSlider(Qt.Orientation.Horizontal)
        self.playhead.setRange(0, 1000)
        self.playhead.valueChanged.connect(self._seek_recording)
        playback.addWidget(self.playhead, 1)
        self.play_time = label('—')
        playback.addWidget(self.play_time)
        self.play_speed = QComboBox()
        for speed in (.5, 1.0, 2.0, 4.0):
            self.play_speed.addItem(f'{speed:g}×', speed)
        self.play_speed.setCurrentIndex(1)
        playback.addWidget(self.play_speed)
        layout.addLayout(playback)
        layers = QHBoxLayout()
        self.layer_controls = {}
        for key, caption, enabled in [('draw_sensors', 'Скан', True), ('draw_points', 'Накопленные LiDAR-точки', True), ('draw_rays', 'Лучи', True), ('draw_world', 'Учебная среда', False)]:
            control = QCheckBox(caption)
            control.setChecked(enabled)
            control.toggled.connect(lambda value, attribute=key: self._set_map_layer(attribute, value))
            self.layer_controls[key] = control
            layers.addWidget(control)
        layers.addStretch()
        layout.addLayout(layers)
        self.sensor_table = QTableWidget(0, 5)
        self.sensor_table.setHorizontalHeaderLabels(['Датчик', 't измерения, с', 'Угол, °', 'Дальность, м', 'Ширина луча, °'])
        self.sensor_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sensor_table.verticalHeader().setVisible(False)
        self.sensor_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.sensor_table, 1)
        return self._scroll_page(page)

    def _set_map_layer(self, name, value):
        setattr(self.map, name, value)
        self.map.update()

    def _choose_sensor_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Загрузить запись датчиков', '', 'Запись датчиков (*.txt *.csv);;Все файлы (*)')
        if path:
            self._open_sensor_file(path)

    def _load_sensor_example(self):
        self._open_sensor_file(Path(__file__).resolve().parents[1] / 'examples' / self.example_choice.currentData())

    def _open_sensor_file(self, path):
        request_id = self.recording_loader.start(path, self.selected_id)
        self._pending_imports[self.selected_id] = request_id
        self.statusBar().showMessage('Подготовка TXT в фоне. Текущий источник сохраняется до проверки файла.')
        self._refresh()
        return request_id

    def _recording_ready(self, request_id, platform_id, player):
        if self._closing or self._pending_imports.get(platform_id) != request_id:
            return
        self._pending_imports.pop(platform_id, None)
        self._install_sensor_player(player, platform_id)
        self.statusBar().showMessage(f'Загружен TXT для {platform_id}: {Path(player.recording.source_path).name}', 5000)

    def _recording_failed(self, request_id, platform_id, message):
        if self._closing or self._pending_imports.get(platform_id) != request_id:
            return
        self._pending_imports.pop(platform_id, None)
        self.service.note(platform_id, f'Не удалось загрузить TXT: {message}', 'WARNING')
        self._refresh()
        self.statusBar().showMessage(f'Ошибка TXT для {platform_id}: {message}', 7000)
        if platform_id == self.selected_id:
            QMessageBox.warning(self, 'Не удалось загрузить датчики', message)

    def load_sensor_file(self, path):
        # Synchronous public API for scripts/tests. GUI actions use the worker.
        player = RecordingPlayer(load_recording(path))
        self._pending_imports.pop(self.selected_id, None)
        self._install_sensor_player(player, self.selected_id)
        return True

    def _install_sensor_player(self, player, platform_id):
        # Parsing succeeded completely before any simulation or source is changed.
        selected = platform_id == self.selected_id
        if selected:
            self._release_manual()
        self.service.stop(platform_id)
        self._replays[platform_id] = player
        self.map.reset_observations(platform_id)
        if selected:
            self.map.bounds = player.bounds
            self.map.fit_map()
        self._ingest_recording(player, rebuild=True, platform_id=platform_id)
        self.service.note(platform_id, f'Загружена запись датчиков: {Path(player.recording.source_path).name}. Управление при просмотре записи отключено.')
        for warning in player.recording.warnings:
            self.service.note(platform_id, warning, 'WARNING')
        if selected:
            self._set_workspace('sensors')
        self._refresh()

    def _leave_replay(self):
        cancelled = self._pending_imports.pop(self.selected_id, None) is not None
        player = self._replays.pop(self.selected_id, None)
        if player is None:
            if cancelled:
                self.statusBar().showMessage('Загрузка TXT отменена. Текущий источник сохранён.', 5000)
                self._refresh()
            return
        self.map.reset_observations(self.selected_id)
        self.map.bounds = (0, 100, 0, 70)
        self.map.fit_map()
        self.service.note(self.selected_id, 'Просмотр записи завершён. Снова отображаются имитируемые датчики.')
        self._refresh()

    def _ingest_recording(self, player, rebuild=False, previous_index=None, platform_id=None):
        platform_id = platform_id or self.selected_id
        if rebuild:
            self.map.reset_observations(platform_id)
        first = 0 if rebuild else (player.index if previous_index is None else previous_index + 1)
        for frame in player.recording.frames[first:player.index + 1]:
            self.map.ingest_frame(platform_id, frame)

    def _seek_recording(self, position):
        player = self._replays.get(self.selected_id)
        if player:
            player.seek(player.times[0] + position / 1000 * player.recording.duration)
            self._ingest_recording(player, rebuild=True)
            self._refresh()

    def _toggle_playback(self):
        player = self._replays.get(self.selected_id)
        if player:
            if player.time_s >= player.times[-1] and not player.playing:
                player.seek(player.times[0])
                self._ingest_recording(player, rebuild=True)
            player.playing = not player.playing
            self._refresh()

    def _display_state(self):
        player = self._replays.get(self.selected_id)
        if player:
            frame = player.frame
            return replace(self.state, pose=frame.pose, sensor_frame=frame, true_pose=None, connected=True,
                           fields={}, speed=player.measured_speed, mode='Запись датчиков')
        return self.state

    def _placeholder(self, title, description):
        result = QWidget()
        lay = QVBoxLayout(result)
        lay.setContentsMargins(25,18,25,18)
        lay.addStretch()
        lay.addWidget(label(title))
        lay.addWidget(label(description,'muted',True))
        lay.addStretch()
        return result

    @property
    def state(self):
        return self.service.platforms[self.selected_id]

    def _call(self, method, *args):
        if self.selected_id in self._replays:
            self.statusBar().showMessage('Открыта запись датчиков. Для управления нажмите «К симуляции».', 5000)
            return False
        try:
            getattr(self.service,method)(self.selected_id,*args)
        except (ValueError, RuntimeError, KeyError) as error:
            self.service.note(self.selected_id, str(error), 'WARNING')
            self._record_command(method, str(error))
            self.statusBar().showMessage(str(error),7000)
            self._refresh()
            return False
        self._record_command(method)
        self._refresh()
        return True

    def _selection_changed(self,current,previous):
        self._release_manual()
        if current:
            self.selected_id = current.data(Qt.ItemDataRole.UserRole)
            self._animate_context()
            self.map.fit_map()
            self._refresh()

    def _select_platform(self, platform_id):
        for row in range(self.platform_list.count()):
            item = self.platform_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == platform_id:
                self.platform_list.setCurrentItem(item)
                return

    def _warning_selected(self, row, column):
        item = self.warning_table.item(row, 0)
        if item:
            self._select_platform(item.data(Qt.ItemDataRole.UserRole))

    def _connect_all(self):
        for platform_id in self.service.platforms:
            self.service.connect(platform_id)
        self._refresh()

    def _toggle_connection(self):
        self._release_manual()
        self._call('disconnect' if self.state.connected else 'connect')

    def _edit_toggled(self,enabled):
        if hasattr(self,'map'):
            self.map.edit_route=enabled
            self.map.update()

    def _begin_manual(self,velocity):
        if self.selected_id not in self._replays and 'manual' in self.state.info.capabilities and self.state.connected and self.state.telemetry_age_s is not None and self.state.telemetry_age_s <= 2 and self.state.mission_status not in ('RUNNING','PAUSED'):
            self._manual=velocity
            self._send_manual()

    def _send_manual(self):
        if self.selected_id in self._replays:
            return
        if self.state.telemetry_age_s is None or self.state.telemetry_age_s > 2:
            self._release_manual()
            return
        velocity=self._manual
        if self.keyboard_checkbox.isEnabled() and self.keyboard_checkbox.isChecked() and self._keys:
            forward=int(bool(self._keys & {Qt.Key.Key_W,Qt.Key.Key_Up}))-int(bool(self._keys & {Qt.Key.Key_S,Qt.Key.Key_Down}))
            turn=int(bool(self._keys & {Qt.Key.Key_A,Qt.Key.Key_Left}))-int(bool(self._keys & {Qt.Key.Key_D,Qt.Key.Key_Right}))
            velocity=(forward,turn)
        if velocity is not None:
            factor=self.power.value()/100
            try:
                self.service.set_velocity(self.selected_id,velocity[0]*factor,velocity[1]*factor)
            except (ValueError,RuntimeError):
                self._release_manual()

    def _neutral_manual(self):
        try:
            self.service.set_velocity(self.selected_id, 0, 0)
        except (ValueError, RuntimeError):
            # A capability/connection can disappear while a key is held. If a
            # normal neutral command is no longer accepted, clear it safely.
            self.service.stop(self.selected_id)

    def _release_manual(self):
        active=self._manual is not None or bool(self._keys)
        self._manual=None
        self._keys.clear()
        if active and hasattr(self,'selected_id'):
            self._neutral_manual()

    def _stop(self):
        self._release_manual()
        player = self._replays.get(self.selected_id)
        if player:
            player.playing = False
            self._refresh()
            return
        self._call('stop')

    def _add_waypoint(self,x,y):
        if self._call('set_route',self.state.route+[Point(x,y)]):
            self.statusBar().showMessage(f'Добавлена демо-точка {len(self.state.route)}: {x:.1f}; {y:.1f}',3000)

    def _clear_route(self):
        self._call('set_route',[])

    def _mission_action(self,action):
        self._release_manual()
        self._call(action)

    def _pause_resume(self):
        self._mission_action('resume_mission' if self.state.mission_status=='PAUSED' else 'pause_mission')

    def _reset(self):
        self._release_manual()
        self._leave_replay()
        self._call('reset')
        self.trails[self.selected_id].clear()
        self._speed_history[self.selected_id].clear()
        self.map.reset_observations(self.selected_id)

    def _save_route(self):
        path,_=QFileDialog.getSaveFileName(self,'Сохранить демонстрационный маршрут','demo_route.json','JSON (*.json)')
        if not path:
            return
        payload={'format':'operator-stub-route','version':1,'coordinate_system':'demo-local','platform_id':self.selected_id,'points':[{'x':p.x,'y':p.y} for p in self.state.route]}
        self._write_json(path,payload)

    def _load_route(self):
        path,_=QFileDialog.getOpenFileName(self,'Загрузить демонстрационный маршрут','','JSON (*.json)')
        if not path:
            return
        try:
            data=json.loads(Path(path).read_text(encoding='utf-8'))
            if not isinstance(data,dict):
                raise ValueError('Файл маршрута должен содержать JSON-объект.')
            if data.get('format')!='operator-stub-route' or data.get('version')!=1 or data.get('coordinate_system')!='demo-local':
                raise ValueError('Ожидается маршрут заглушки версии 1 в координатах demo-local.')
            points=data['points']
            if not isinstance(points,list) or len(points)>self.service.MAX_ROUTE_POINTS:
                raise ValueError(f'Маршрут должен содержать не более {self.service.MAX_ROUTE_POINTS} точек.')
            self._call('set_route',[Point(p['x'],p['y']) for p in points])
        except (OSError,ValueError,KeyError,TypeError) as error:
            QMessageBox.warning(self,'Не удалось загрузить маршрут',str(error))

    def _write_json(self,path,payload):
        try:
            Path(path).write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
            self.statusBar().showMessage(f'Сохранено: {path}',5000)
        except (OSError,ValueError) as error:
            QMessageBox.warning(self,'Не удалось сохранить файл',str(error))

    def _export_session(self):
        path,_=QFileDialog.getSaveFileName(self,'Экспорт состояния комплекса','operator_session.json','JSON (*.json)')
        if not path:
            return
        payload = self.service.export_snapshot()
        payload['view'] = {
            'selected_platform_id': self.selected_id,
            'source': 'recording' if self.selected_id in self._replays else 'simulation',
            'recordings': {
                platform_id: {'source_file': player.recording.source_path, 'time_s': player.time_s,
                              'playing': player.playing,
                              'pose': {'x': player.frame.pose.x, 'y': player.frame.pose.y, 'heading': player.frame.pose.heading}}
                for platform_id, player in self._replays.items()
            },
        }
        self._write_json(path, payload)

    def _tick(self):
        now=time.monotonic()
        dt=min(now-self._last_tick,0.2)
        self._last_tick=now
        self._send_manual()
        self.service.tick(dt)
        for platform_id,state in self.service.platforms.items():
            if platform_id in self._replays:
                continue
            trail=self.trails[platform_id]
            point=(state.pose.x,state.pose.y)
            if not trail or abs(trail[-1][0]-point[0])+abs(trail[-1][1]-point[1])>0.04:
                trail.append(point)
            self.map.ingest_frame(platform_id, state.sensor_frame)
        player = self._replays.get(self.selected_id)
        if player:
            previous = player.index
            player.speed = self.play_speed.currentData()
            player.advance(dt)
            self._ingest_recording(player, previous_index=previous)
        self._sample_metrics()
        self._refresh()

    @staticmethod
    def _percent_text(state, semantic):
        value = metric_value(state, semantic)
        if not state.connected:
            return '—'
        return 'Нет данных' if value is None else f'{value:.0f}%'

    def _refresh(self):
        state = self._display_state()
        player = self._replays.get(self.selected_id)
        profile = profile_for(state.info.kind)
        connected = sum(s.connected for s in self.service.platforms.values())
        self.overall_status.setText(f'{connected} из {len(self.service.platforms)} подключено')
        for row in range(self.platform_list.count()):
            item = self.platform_list.item(row)
            source = self.service.platforms[item.data(Qt.ItemDataRole.UserRole)]
            replay = self._replays.get(source.info.id)
            battery = self._percent_text(source, 'battery_percent')
            link = self._percent_text(source, 'link_quality_percent')
            status = '● Подключено' if source.connected else '○ Отключено'
            item.setText(f'{source.info.name}\n{source.info.kind} · {source.info.id}\n' + (f'TXT · {Path(replay.recording.source_path).name}\nПросмотр записи датчиков' if replay else f'Заряд {battery} · связь {link}\n{status} · {source.mode}'))
            item.setToolTip(f'{source.info.name}\n{source.mode}\nИсточник: {source.info.source}')
        self.platform_title.setText(f'{state.info.kind} · {state.info.id}')
        self.profile_label.setText(f'{profile.title} · {profile.environment}')
        self.manual_hint.setText('Просмотр записи. Для управления моделью нажмите «К симуляции».' if player else profile.manual_hint)
        self.platform_limitation.setText('TXT: поза из локализации и сканы датчиков. Модель движения не применяется; высота, батарея и связь в этом формате не заданы.' if player else profile.limitation)
        self.connection_button.setText('Отключить демо' if state.connected else 'Подключить демо')
        self.connection_button.setEnabled(player is None)
        self.source_banner.setText(f'ЗАПИСЬ ДАТЧИКОВ · {Path(player.recording.source_path).name} · Просмотр показаний, команды роботу не передаются.' if player else 'УЧЕБНАЯ СИМУЛЯЦИЯ · Разные модели движения и имитируемые датчики. Параметры не калиброваны под реальные аппараты.')
        age = state.telemetry_age_s
        stale = state.connected and (age is None or age > 2)
        connection = 'Демо подключено' if state.connected else 'Отключено · последнее положение'
        if stale:
            connection += ' · данные устарели'
        self.metric_values['connection'].setText(connection)
        if player:
            self.metric_values['connection'].setText('TXT · источник данных из файла')
        for key, semantic, warning_threshold in [('battery', 'battery_percent', 20), ('link', 'link_quality_percent', 30)]:
            value = metric_value(state, semantic)
            text = self._percent_text(state, semantic)
            if stale and value is not None:
                text += ' *'
            self.metric_values[key].setText(text)
            if player:
                self.metric_values[key].setText('Нет в TXT')
            last = 'нет данных' if value is None else f'{value:g}%'
            tooltip = f'Тестовые данные. Последнее значение: {last}. Источник: {state.info.source}.'
            if not state.connected or stale:
                tooltip += ' Значение не является актуальным.'
            self.metric_values[key].setToolTip(tooltip)
            color = '#8a98a8' if not state.connected or stale or value is None else (
                '#b43d46' if value <= 10 else '#976715' if value <= warning_threshold else '#23735c'
            )
            self.metric_values[key].setStyleSheet(f'color: {color};')
            bar = self.metric_bars[key]
            bar.setValue(round(value) if value is not None and state.connected else 0)
            bar.setEnabled(state.connected and value is not None and not stale)
            bar.setStyleSheet(f'QProgressBar::chunk {{ background: {color}; }}')
        self.metric_values['mode'].setText(state.mode)
        self.metric_values['mission'].setText('Запись · ' + ('идёт' if player.playing else 'пауза') if player else STATUS.get(state.mission_status, state.mission_status))
        self.metric_values['position'].setText(f'{state.pose.x:.1f} / {state.pose.y:.1f}')
        self.metric_values['position'].setToolTip(f'Демонстрационная локальная система. X={state.pose.x:.2f}, Y={state.pose.y:.2f}, курс={state.pose.heading:.1f}°.' + (' Последнее известное положение.' if not state.connected else ''))
        if player:
            self.metric_values['position'].setToolTip(f'Положение из TXT в локальной системе, метры. X={state.pose.x:.2f}, Y={state.pose.y:.2f}, курс={state.pose.heading:.1f}°. Между отсчётами применяется интерполяция.')
        self.metric_values['position'].setStyleSheet('color: #213c55;' if state.connected else 'color: #8a98a8;')
        self.metric_values['speed'].setText(f'{state.speed:.2f}')
        for key in ('speed', 'position'):
            self.metric_values[key].setStyleSheet('color: #9295a1;' if not state.connected or stale else 'color: #252733;')
            if not state.connected or stale:
                self.metric_values[key].setToolTip('Последнее полученное значение. Данные не актуальны.')
        self.route_info.setText(f'Точек: {len(state.route)}   ·   Пройдено: {min(state.waypoint_index, len(state.route))}')
        manual = player is None and 'manual' in state.info.capabilities
        mission = player is None and 'mission' in state.info.capabilities
        idle = state.mission_status not in ('RUNNING', 'PAUSED')
        self.start_button.setEnabled(mission and state.connected and not stale and bool(state.route) and idle)
        self.pause_button.setText('Продолжить' if state.mission_status == 'PAUSED' else 'Пауза')
        self.pause_button.setEnabled(mission and state.connected and not stale and not idle)
        self.cancel_button.setEnabled(player is None and not idle)
        self.clear_button.setEnabled(mission and idle)
        self.load_route_button.setEnabled(mission and idle)
        self.save_route_button.setEnabled(mission and bool(state.route))
        self.edit_checkbox.setEnabled(mission and idle)
        manual_enabled = manual and state.connected and not stale and idle
        self.keyboard_checkbox.setEnabled(manual_enabled)
        if not manual_enabled:
            self._release_manual()
        for index, control in enumerate(self.direction_buttons):
            control.setEnabled(manual_enabled)
            control.setToolTip(('Вперёд', 'Поворот влево', 'Назад', 'Поворот вправо')[index] + ' · ' + state.info.kind if manual else 'Адаптер не поддерживает ручное управление')
        if not manual:
            self.keyboard_checkbox.setToolTip('Ручное управление недоступно в возможностях адаптера.')
        self.freshness.setText(f'Выбрано: {state.info.id}\nДанные не поступали' if age is None else f'Выбрано: {state.info.id}\nВозраст данных: {age:.1f} с\nКурс на карте: {state.pose.heading:.0f}°')
        if player:
            self.freshness.setText(f'TXT: {Path(player.recording.source_path).name}\nВремя записи: {player.time_s - player.times[0]:.1f} / {player.recording.duration:g} с\nКурс из файла: {state.pose.heading:.0f}°')
        capabilities = ' · '.join(name for key, name in [('manual', 'ручное управление'), ('mission', 'маршрут')] if key in state.info.capabilities) or 'только наблюдение'
        self.profile_details.setText(f'{state.info.name} · {profile.environment}\n\n{profile.limitation}\n\nВозможности адаптера: {capabilities}.\nОбщий принцип: выбрать устройство → подключить → ручной ввод или маршрут → остановка.\n\n{state.info.description}\nКоординаты X/Y, скорость и профильные показания демонстрационные. Состав реального оборудования пока не определён.')
        self.map.platforms = self.service.platforms
        if player:
            self.map.platforms = {**self.service.platforms, self.selected_id: state}
        self.map.selected_id = self.selected_id
        self.map.trails = self.trails
        if player:
            self.map.trails = {**self.trails, self.selected_id: player.trajectory}
        self.map.bounds = player.bounds if player else (0, 100, 0, 70)
        self.map.draw_plan = player is None
        self.layer_controls['draw_world'].setEnabled(player is None)
        self.map.draw_world = player is None and self.layer_controls['draw_world'].isChecked()
        self.map.sensor_frame = state.sensor_frame
        if not player:
            self.map.ingest_frame(self.selected_id, state.sensor_frame)
        self.map.edit_route = mission and self.edit_checkbox.isChecked() and idle
        self.map.update()
        rows = []
        for key, field in state.fields.items():
            value = 'Нет данных' if field.value is None else (
                f'{field.value:.2f}' if isinstance(field.value, (int, float)) and not isinstance(field.value, bool) else str(field.value)
            )
            rows.append((f'{field.label}  [{key}]', value, field.unit))
        if not rows:
            rows.append(('В TXT нет батареи и связи. LiDAR / сонар — во вкладке «Датчики / TXT».', 'Не подменяются симуляцией', '') if player else ('Поля телеметрии не заданы', 'Настройте JSON-профиль', ''))
        self.telemetry.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, text in enumerate(values):
                current = self.telemetry.item(row, column)
                if current is None:
                    current = QTableWidgetItem()
                    self.telemetry.setItem(row, column, current)
                if current.text() != str(text):
                    current.setText(str(text))
                current.setForeground(QColor('#243b53' if state.connected and not stale else '#8a98a8'))
                current.setToolTip('Тестовые данные' if state.connected and not stale else 'Последнее значение; данные не актуальны')
        self._refresh_alerts()
        self._refresh_events()
        self._refresh_sensor_panel(state.sensor_frame, player)
        self._refresh_workspace()

    def _refresh_sensor_panel(self, frame, player):
        for control in (self.play_button, self.playhead, self.play_speed, self.return_simulation_button):
            control.setEnabled(player is not None)
        loading = self.selected_id in self._pending_imports
        self.load_sensor_button.setEnabled(not loading)
        self.sensor_example_button.setEnabled(not loading)
        self.return_simulation_button.setEnabled(player is not None or loading)
        if player:
            self.play_button.setText('Пауза' if player.playing else 'Воспроизвести')
            elapsed, duration = player.time_s - player.times[0], player.recording.duration
            self.play_time.setText(f'{elapsed:.1f} / {duration:.1f} с')
            self.playhead.blockSignals(True)
            self.playhead.setValue(round(1000 * elapsed / duration) if duration else 0)
            self.playhead.blockSignals(False)
            self.sensor_source.setText(f'TXT: {Path(player.recording.source_path).name} · {len(player.recording.frames)} кадров · Поза из файла; сканы закреплены в момент измерения.')
        else:
            self.play_time.setText('Симуляция')
            self.sensor_source.setText('Имитируемые датчики · Трек по локализации · LiDAR — точки, сонар — дуги · Для загрузки файла нажмите «Загрузить TXT».')
        if loading:
            self.sensor_source.setText('Подготовка TXT в фоне… Текущий источник сохранён. «К симуляции» отменяет загрузку.')
        readings = frame.readings[:500] if frame else ()
        self.sensor_table.setRowCount(len(readings))
        for row, reading in enumerate(readings):
            timestamp = reading.measurement_time_s if reading.measurement_time_s is not None else (frame.reading_time_s if frame.reading_time_s is not None else frame.time_s)
            values = (reading.sensor.upper(), f'{timestamp:.2f}', f'{reading.angle_deg:g}', f'{reading.range_m:.2f}' if reading.hit else 'Нет отражения', f'{reading.fov_deg:g}')
            for column, value in enumerate(values):
                item = self.sensor_table.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.sensor_table.setItem(row, column, item)
                item.setText(value)
        if frame:
            reading_time = frame.reading_time_s if frame.reading_time_s is not None else frame.time_s
            self.sensor_source.setToolTip(f'Источник: {frame.source}\nПоза: t={frame.time_s:.2f} с; скан: t={reading_time:.2f} с. Отображаются первые {len(readings)} из {len(frame.readings)} измерений.')

    def _refresh_alerts(self):
        alerts = [(state, replace(warning, message='Сохранённая симуляция (не TXT): ' + warning.message) if state.info.id in self._replays else warning)
                  for state in self.service.platforms.values() for warning in warnings_for(state)]
        ranks = {'CRITICAL': 0, 'ERROR': 0, 'WARNING': 1, 'INFO': 2}
        alerts.sort(key=lambda pair: (ranks.get(pair[1].level, 2), pair[0].info.id, pair[1].code))
        current = {(state.info.id, warning.code): warning for state, warning in alerts}
        for key, warning in current.items():
            previous = self._active_alerts.get(key)
            if previous is None or previous.level != warning.level:
                self.service.note(key[0], warning.message, warning.level)
        for key, warning in self._active_alerts.items():
            if key not in current:
                self.service.note(key[0], f'Снято: {warning.message}', 'INFO')
        self._active_alerts = current
        self.warning_table.setRowCount(len(alerts))
        severity_labels = {'CRITICAL': 'Критично', 'ERROR': 'Ошибка', 'WARNING': 'Внимание', 'INFO': 'Информация'}
        colors = {'CRITICAL': '#b33d35', 'ERROR': '#b33d35', 'WARNING': '#9b651c', 'INFO': '#4e6a89'}
        for row, (state, warning) in enumerate(alerts):
            for column, text in enumerate((severity_labels.get(warning.level, warning.level), f'{state.info.kind} · {state.info.id}', warning.message)):
                item = self.warning_table.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.warning_table.setItem(row, column, item)
                item.setText(text)
                item.setData(Qt.ItemDataRole.UserRole, state.info.id)
                item.setForeground(QColor(colors.get(warning.level, '#4e6a89')))
                item.setToolTip(warning.message + '\nДвойной щелчок — выбрать устройство')
        self.warning_table.resizeRowsToContents()
        count = sum(warning.level != 'INFO' for _, warning in alerts)
        self.tabs.setTabText(self.warning_tab_index, f'Предупреждения ({count})')
        if alerts:
            state, warning = alerts[0]
            self.alert_summary.setText(f'{severity_labels.get(warning.level, warning.level).upper()} · {state.info.kind} / {state.info.id}: {warning.message}')
            color = colors.get(warning.level, '#4e6a89')
            background = '#fff0ee' if warning.level in ('CRITICAL', 'ERROR') else '#fff4df' if warning.level == 'WARNING' else '#e9f0f8'
        else:
            self.alert_summary.setText('ПРЕДУПРЕЖДЕНИЯ · Нет активных предупреждений в демо-источниках')
            color, background = '#326956', '#e9f4ef'
        self.alert_summary.setVisible(bool(alerts))
        self.alert_summary.setToolTip(self.alert_summary.text())
        self.alert_summary.setStyleSheet(f'color: {color}; background: {background}; border-radius: 6px; padding: 7px 10px;')

    def _refresh_events(self):
        scope, severity = self.log_scope.currentIndex(), self.log_level.currentIndex()
        events = [event for event in self.service.events if (not scope or event.platform_id in ('', self.selected_id)) and (not severity or event.level in ('WARNING', 'CRITICAL', 'ERROR'))]
        signature = (scope, severity, self.selected_id, tuple((e.time, e.platform_id, e.message, e.level) for e in events))
        if signature == self._last_events:
            return
        self._last_events = signature
        names = {'INFO': 'Событие', 'WARNING': 'Предупреждение', 'CRITICAL': 'Критично', 'ERROR': 'Ошибка'}
        colors = {'INFO': '#4e6a89', 'WARNING': '#9b651c', 'CRITICAL': '#b33d35', 'ERROR': '#b33d35'}
        lines = [f'<div style="margin-bottom:5px;color:{colors.get(e.level, "#4e6a89")}"><b>{e.time.astimezone():%H:%M:%S} · {escape(e.platform_id or "Система")} · {escape(names.get(e.level, e.level))}</b> &nbsp; {escape(e.message)}</div>' for e in events]
        self.log.setHtml(''.join(lines) or '<p>Нет событий для выбранного фильтра.</p>')
        self.log.moveCursor(QTextCursor.MoveOperation.End)

    @staticmethod
    def _control_key(event: QKeyEvent):
        key = event.key()
        keys = {Qt.Key.Key_W, Qt.Key.Key_A, Qt.Key.Key_S, Qt.Key.Key_D,
                Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right,
                Qt.Key.Key_Space, Qt.Key.Key_Escape}
        if key in keys:
            return key
        letters = {'w': Qt.Key.Key_W, 'ц': Qt.Key.Key_W,
                   'a': Qt.Key.Key_A, 'ф': Qt.Key.Key_A,
                   's': Qt.Key.Key_S, 'ы': Qt.Key.Key_S,
                   'd': Qt.Key.Key_D, 'в': Qt.Key.Key_D}
        letter = event.text().casefold()
        if letter in letters:
            return letters[letter]
        if 0 <= key <= 0x10ffff and chr(key).casefold() in letters:
            return letters[chr(key).casefold()]
        # Qt exposes nativeVirtualKey as platform-specific data. On macOS this
        # is the physical ANSI virtual key; synthetic events may contain no data.
        if sys.platform == 'darwin' and any((event.nativeVirtualKey(), event.nativeScanCode(), event.nativeModifiers())):
            return {13: Qt.Key.Key_W, 0: Qt.Key.Key_A,
                    1: Qt.Key.Key_S, 2: Qt.Key.Key_D}.get(event.nativeVirtualKey())
        return None

    @staticmethod
    def _is_text_input(widget):
        while isinstance(widget, QWidget):
            if isinstance(widget, (QLineEdit, QAbstractSpinBox)):
                return True
            if isinstance(widget, (QTextEdit, QPlainTextEdit)) and not widget.isReadOnly():
                return True
            if isinstance(widget, QComboBox) and widget.isEditable():
                return True
            widget = widget.parentWidget()
        return False

    def _keyboard_allowed(self, widget=None, *, stop=False):
        if not hasattr(self, 'keyboard_checkbox') or not self.keyboard_checkbox.isChecked():
            return False
        stopping_mission = stop and (self.state.mission_status in ('RUNNING', 'PAUSED') or self.selected_id in getattr(self, '_replays', {}))
        if not self.keyboard_checkbox.isEnabled() and not stopping_mission:
            return False
        widget = widget or QApplication.focusWidget() or self
        return isinstance(widget, QWidget) and widget.window() is self and not self._is_text_input(widget)

    def keyPressEvent(self,event: QKeyEvent):
        key = self._control_key(event)
        shortcut_modifiers = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier
        if self._keyboard_allowed(stop=key in (Qt.Key.Key_Space, Qt.Key.Key_Escape)) and key is not None and not event.modifiers() & shortcut_modifiers:
            if key in (Qt.Key.Key_Space, Qt.Key.Key_Escape):
                if not event.isAutoRepeat():
                    self._stop()
            else:
                self._keys.add(key)
                self._send_manual()
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self,event: QKeyEvent):
        key = self._control_key(event)
        if key in self._keys:
            if not event.isAutoRepeat():
                self._keys.discard(key)
                if self._keys:
                    self._send_manual()
                else:
                    # Send neutral input immediately, without waiting for a UI tick.
                    self._neutral_manual()
            event.accept()
        elif self._keyboard_allowed(stop=True) and key in (Qt.Key.Key_Space, Qt.Key.Key_Escape):
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def eventFilter(self,watched,event):
        # Filtering at application level also works when a read-only table or
        # a direction button has focus. Separate windows and editors keep typing.
        if event.type() == QEvent.Type.FocusIn and isinstance(watched, QWidget):
            if watched.window() is not self or self._is_text_input(watched):
                self._release_manual()
        if event.type() in (QEvent.Type.KeyPress,QEvent.Type.KeyRelease):
            shortcut_modifiers = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier
            key = self._control_key(event)
            allowed = self._keyboard_allowed(watched, stop=key in (Qt.Key.Key_Space, Qt.Key.Key_Escape))
            if allowed and key is not None and (not event.modifiers() & shortcut_modifiers or key in self._keys):
                if event.type()==QEvent.Type.KeyPress:
                    self.keyPressEvent(event)
                else:
                    self.keyReleaseEvent(event)
                return True
        return super().eventFilter(watched,event)

    def changeEvent(self,event):
        if event.type()==QEvent.Type.ActivationChange and not self.isActiveWindow() and hasattr(self,'service'):
            self._release_manual()
        super().changeEvent(event)

    def closeEvent(self,event):
        self._closing = True
        self._pending_imports.clear()
        self._release_manual()
        self.timer.stop()
        QApplication.instance().removeEventFilter(self)
        for platform_id in self.service.platforms:
            self.service.disconnect(platform_id)
        super().closeEvent(event)
