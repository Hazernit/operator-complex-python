"""Native desktop workspace composition, separate from application commands."""
from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
import time

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame,
    QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QProgressBar, QPushButton,
    QScrollArea, QSlider, QSplitter, QTabWidget, QTableWidget, QTextEdit,
    QVBoxLayout, QWidget,
)
from .design import MOTION, PlatformDelegate, Sparkline, icon
from .map_widget import MapWidget
from .models import MISSION_RUNNING, Point
from .presentation import metric_value, warnings_for


def text(value, name=None, wrap=False):
    w=QLabel(value);w.setTextFormat(Qt.TextFormat.PlainText);w.setWordWrap(wrap)
    if name:w.setObjectName(name)
    return w


def action(caption, callback=None, name=None, symbol=None):
    w=QPushButton(caption)
    if name:w.setObjectName(name)
    if symbol:w.setIcon(icon(symbol))
    if callback:w.clicked.connect(callback)
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    return w


def divider():
    return QFrame(objectName='divider')


class WorkspaceMixin:
    def _build(self):
        self._reduced_motion=False
        self._last_sample=0.0
        self._speed_history=defaultdict(lambda:deque(maxlen=150))
        self._command_results={}
        self._workspace_mode='map'
        central=QWidget(objectName='workspace');self.setCentralWidget(central)
        root=QHBoxLayout(central);root.setContentsMargins(0,0,0,0);root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        main=QWidget();outer=QVBoxLayout(main);outer.setContentsMargins(24,15,20,10);outer.setSpacing(12)
        top=QHBoxLayout();top.setSpacing(10)
        top.addWidget(text('Единый операторский комплекс','muted'))
        top.addWidget(text('/','muted'));top.addWidget(text('Рабочее пространство','muted'));top.addStretch()
        top.addWidget(text('DEMO / SIMULATION','badge'))
        self.overall_status=text('','muted');top.addWidget(self.overall_status)
        full=action('',self._toggle_fullscreen,symbol='fullscreen');full.setToolTip('Полный экран · Ctrl+Shift+F');full.setAccessibleName('Переключить полноэкранный режим');full.setFixedSize(30,30);top.addWidget(full)
        outer.addLayout(top)
        heading=QHBoxLayout();title=QVBoxLayout();title.setSpacing(4)
        self.context_title=text('Обзор платформы','heading');title.addWidget(self.context_title)
        self.profile_label=text('','muted');title.addWidget(self.profile_label)
        heading.addLayout(title);heading.addStretch()
        self.context_mode=text('','badge');heading.addWidget(self.context_mode)
        outer.addLayout(heading)
        self.source_banner=text('','warning',True);outer.addWidget(self.source_banner)
        self.alert_summary=text('',wrap=True);self.alert_summary.setMinimumHeight(28)
        self.alert_summary.setMaximumHeight(55)
        outer.addWidget(self.alert_summary)
        nav=QHBoxLayout();nav.setSpacing(3);self.view_buttons={}
        for key,caption,symbol in [('map','Обзор','map'),('telemetry','Телеметрия','chart'),('sensors','Датчики','sensor'),('events','События','log'),('camera','Камеры','camera')]:
            b=action(caption,lambda checked=False,k=key:self._set_workspace(k),'nav',symbol)
            b.setCheckable(True);self.view_buttons[key]=b;nav.addWidget(b)
        self.view_buttons['map'].setChecked(True);nav.addStretch()
        extra=action('Ещё');menu=QMenu(extra)
        for caption,attr in [('Предупреждения','warning_table'),('Особенности платформы','profile_details'),('Подключение оборудования','integration_page')]:
            a=menu.addAction(caption);a.triggered.connect(lambda checked=False,n=attr:self._show_details(getattr(self,n)))
        extra.setMenu(menu);nav.addWidget(extra);outer.addLayout(nav)
        self.main_splitter=QSplitter(Qt.Orientation.Horizontal);self.main_splitter.setChildrenCollapsible(False);self.main_splitter.setHandleWidth(8)
        self.splitter=QSplitter(Qt.Orientation.Vertical);self.splitter.setHandleWidth(7)
        self.map_page=self._build_map_page();self.splitter.addWidget(self.map_page)
        self.tabs=self._build_diagnostics();self.splitter.addWidget(self.tabs)
        self.splitter.setCollapsible(0,True);self.splitter.setCollapsible(1,True)
        self.splitter.setStretchFactor(0,3);self.splitter.setStretchFactor(1,2)
        self.tabs.hide()
        self.main_splitter.addWidget(self.splitter)
        self.inspector=self._build_inspector();self.main_splitter.addWidget(self.inspector)
        self.main_splitter.setStretchFactor(0,1);self.main_splitter.setStretchFactor(1,0);self.main_splitter.setSizes([850,288])
        outer.addWidget(self.main_splitter,1)
        foot=QHBoxLayout();self.platform_limitation=text('','muted',True);self.platform_limitation.setMaximumHeight(34)
        foot.addWidget(self.platform_limitation,1);outer.addLayout(foot)
        root.addWidget(main,1)
        self._fade_effect=QGraphicsOpacityEffect(self.splitter);self.splitter.setGraphicsEffect(self._fade_effect)
        self._fade=QPropertyAnimation(self._fade_effect,b'opacity',self);self._fade.setDuration(MOTION['context']);self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        shortcut=QAction(self);shortcut.setShortcut(QKeySequence('Ctrl+Shift+F'));shortcut.triggered.connect(self._toggle_fullscreen);self.addAction(shortcut)
        search=QAction(self);search.setShortcut(QKeySequence.StandardKey.Find);search.triggered.connect(self.platform_search.setFocus);self.addAction(search)
        self.map.setFocus(Qt.FocusReason.OtherFocusReason)

    def _build_sidebar(self):
        sidebar=QWidget(objectName='sidebar');sidebar.setMinimumWidth(215);sidebar.setMaximumWidth(240)
        side=QVBoxLayout(sidebar);side.setContentsMargins(14,20,14,16);side.setSpacing(12)
        brand=QHBoxLayout();mark=text('');mark.setPixmap(icon('route','#6257d5',26).pixmap(26,26));brand.addWidget(mark);brand.addWidget(text('Оператор','brand'));brand.addStretch();side.addLayout(brand)
        side.addWidget(text('Университетский проект № 4','sidebarNote'))
        side.addSpacing(14)
        caption=QHBoxLayout();caption.addWidget(text('ПЛАТФОРМЫ','section'));caption.addStretch();self.fleet_count=text('','sidebarNote');caption.addWidget(self.fleet_count);side.addLayout(caption)
        self.platform_search=QLineEdit();self.platform_search.setPlaceholderText('Найти платформу…');self.platform_search.setClearButtonEnabled(True);self.platform_search.setAccessibleName('Поиск платформ по имени, типу и идентификатору');self.platform_search.textChanged.connect(self._filter_platforms);side.addWidget(self.platform_search)
        self.platform_list=QListWidget();self.platform_list.setItemDelegate(PlatformDelegate(self.platform_list));self.platform_list.setSpacing(1)
        self.platform_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.platform_list.setMinimumHeight(180)
        self.platform_list.setAccessibleName('Платформы комплекса')
        for platform_id,state in self.service.platforms.items():
            item=QListWidgetItem();item.setSizeHint(QSize(200,112));item.setData(Qt.ItemDataRole.UserRole,platform_id);self.platform_list.addItem(item)
            if platform_id==self.selected_id:self.platform_list.setCurrentItem(item)
        self.platform_list.currentItemChanged.connect(self._selection_changed);side.addWidget(self.platform_list,1)
        self.search_empty=text('Платформы не найдены','muted',True);self.search_empty.hide();side.addWidget(self.search_empty)
        side.addWidget(divider())
        self.freshness=text('','sidebarNote',True);side.addWidget(self.freshness)
        side.addWidget(action('Подключить все демо',self._connect_all,'quiet','connect'))
        side.addWidget(action('Экспорт сеанса',self._export_session,'quiet','export'))
        side.addWidget(action('Сбросить выбранное демо',self._reset,'quiet','reset'))
        side.addWidget(divider());side.addWidget(action('Настройки',self._open_settings,'quiet','settings'))
        side.addWidget(text('Локальные источники · Python / Qt','sidebarNote'))
        return sidebar

    def _build_map_page(self):
        page=QFrame(objectName='surface');lay=QVBoxLayout(page);lay.setContentsMargins(0,0,0,0);lay.setSpacing(0)
        tools=QHBoxLayout();tools.setContentsMargins(14,10,12,8);tools.setSpacing(7)
        tools.addWidget(text('Локальная карта','section'));tools.addStretch()
        self.edit_checkbox=QCheckBox('Добавлять точки');self.edit_checkbox.setMinimumWidth(150);self.edit_checkbox.setChecked(True);self.edit_checkbox.toggled.connect(self._edit_toggled);tools.addWidget(self.edit_checkbox)
        self.map=MapWidget();self.map.embedded=True;self.map.setFocusPolicy(Qt.FocusPolicy.StrongFocus);self.map.setMinimumHeight(170);self.map.waypoint_requested.connect(self._add_waypoint);self.map.platform_selected.connect(self._select_platform)
        for caption,callback,tip,symbol in [ ('−',self.map.zoom_out,'Уменьшить масштаб',None),('+',self.map.zoom_in,'Увеличить масштаб',None),('',self.map.center_selected,'Центрировать платформу','center'),('Вписать',self.map.fit_map,'Показать всю рабочую область',None) ]:
            b=action(caption,callback,symbol=symbol);b.setToolTip(tip);b.setAccessibleName(tip)
            if caption!='Вписать':b.setFixedSize(29,29)
            tools.addWidget(b)
        lay.addLayout(tools);lay.addWidget(divider());lay.addWidget(self.map,1)
        footer=QHBoxLayout();footer.setContentsMargins(13,5,13,9)
        footer.addWidget(text('XY · метры · условная область','muted'));footer.addStretch();footer.addWidget(text('Колесо — масштаб  ·  ПКМ — сдвиг','muted'));lay.addLayout(footer)
        return page

    def _build_inspector(self):
        inspector=QFrame(objectName='surface');inspector.setMinimumWidth(270);inspector.setMaximumWidth(330)
        outer_shell=QVBoxLayout(inspector);outer_shell.setContentsMargins(14,14,14,10);outer_shell.setSpacing(9)
        shell=outer_shell
        h=QHBoxLayout();h.setSpacing(6);self.metric_values={};self.metric_bars={}
        self.platform_title=text('','inspectorTitle');h.addWidget(self.platform_title,1)
        self.connection_button=action('',self._toggle_connection,symbol='connect');self.connection_button.setFixedSize(30,30);h.addWidget(self.connection_button);shell.addLayout(h)
        self.metric_values['connection']=text('','muted',True);shell.addWidget(self.metric_values['connection'])
        shell.addWidget(divider())
        metrics=QGridLayout();metrics.setHorizontalSpacing(14);metrics.setVerticalSpacing(11)
        for i,(key,caption) in enumerate([('battery','БАТАРЕЯ'),('link','СВЯЗЬ'),('speed','СКОРОСТЬ · М/С'),('position','ПОЗИЦИЯ · X / Y')]):
            cell=QFrame(objectName='metric');v=QVBoxLayout(cell);v.setContentsMargins(0,0,0,0);v.setSpacing(4);v.addWidget(text(caption,'section'))
            self.metric_values[key]=text('—','metricValue');v.addWidget(self.metric_values[key])
            if key in ('battery','link'):
                bar=QProgressBar();bar.setTextVisible(False);bar.setRange(0,100);bar.setFixedHeight(4);self.metric_bars[key]=bar;v.addWidget(bar)
            metrics.addWidget(cell,i//2,i%2)
        shell.addLayout(metrics)
        self.speed_trace=Sparkline();self.speed_trace.setMaximumHeight(48);self.speed_trace.hide();shell.addWidget(self.speed_trace)
        # The header and route page carry mode/mission; retain shared labels for presentation contracts.
        self.metric_values['mode']=text('','muted');self.metric_values['mode'].hide()
        self.metric_values['mission']=text('','muted');self.metric_values['mission'].hide()
        shell.addWidget(divider())
        self.control_tabs=QTabWidget();self.control_tabs.setMinimumHeight(140)
        manual=QWidget(objectName='commandPage');ctl=QVBoxLayout(manual);ctl.setContentsMargins(0,10,0,3);ctl.setSpacing(9)
        self.manual_hint=text('','muted',True);ctl.addWidget(self.manual_hint)
        pad=QGridLayout();pad.setSpacing(6);self.direction_buttons=[]
        for caption,pos,velocity in [('↑',(0,1),(1,0)),('←',(1,0),(0,1)),('↓',(1,1),(-1,0)),('→',(1,2),(0,-1))]:
            key=action(caption,name='direction');key.setFixedHeight(37);key.setFocusPolicy(Qt.FocusPolicy.NoFocus);key.pressed.connect(lambda v=velocity:self._begin_manual(v));key.released.connect(self._release_manual);self.direction_buttons.append(key);pad.addWidget(key,*pos)
        ctl.addLayout(pad)
        power=QHBoxLayout();power.addWidget(text('Интенсивность','muted'));power.addStretch();self.power_label=text('40%','muted');power.addWidget(self.power_label);ctl.addLayout(power)
        self.power=QSlider(Qt.Orientation.Horizontal);self.power.setRange(10,100);self.power.setValue(40);self.power.valueChanged.connect(lambda v:self.power_label.setText(f'{v}%'));ctl.addWidget(self.power)
        self.keyboard_checkbox=QCheckBox('Клавиатура · WASD / стрелки');self.keyboard_checkbox.setChecked(True);self.keyboard_checkbox.setToolTip('W/Ц, S/Ы — ход. A/Ф, D/В — курс. Пробел / Esc — СТОП. Текстовые поля не перехватываются.');self.keyboard_checkbox.toggled.connect(lambda _:self._release_manual());ctl.addWidget(self.keyboard_checkbox);ctl.addStretch()
        self.control_tabs.addTab(self._scroll_page(manual),'Ручное')
        route=QWidget(objectName='commandPage');r=QVBoxLayout(route);r.setContentsMargins(0,10,0,3);r.setSpacing(9)
        self.route_info=text('','muted');r.addWidget(self.route_info)
        self.mission_progress=QProgressBar();self.mission_progress.setTextVisible(False);self.mission_progress.setFixedHeight(4);r.addWidget(self.mission_progress)
        rows=QHBoxLayout();self.start_button=action('Запустить',lambda:self._mission_action('start_mission'),'primary');self.pause_button=action('Пауза',self._pause_resume);rows.addWidget(self.start_button);rows.addWidget(self.pause_button);r.addLayout(rows)
        more=QHBoxLayout();self.cancel_button=action('Отменить',lambda:self._mission_action('cancel_mission'));self.clear_button=action('Очистить',self._clear_route);more.addWidget(self.cancel_button);more.addWidget(self.clear_button);r.addLayout(more)
        files=QHBoxLayout();self.load_route_button=action('Загрузить',self._load_route);self.save_route_button=action('Сохранить',self._save_route);files.addWidget(self.load_route_button);files.addWidget(self.save_route_button);r.addLayout(files)
        self.route_points=QListWidget();self.route_points.setMaximumHeight(115);self.route_points.setAccessibleName('Точки маршрута');r.addWidget(self.route_points)
        self.route_hint=text('Включите «Добавлять точки» и укажите их на карте. Одна точка — переход к цели.','muted',True);r.addWidget(self.route_hint);r.addStretch();self.control_tabs.addTab(self._scroll_page(route),'Маршрут')
        self.control_tabs.currentChanged.connect(self._control_context_changed);shell.addWidget(self.control_tabs,1)
        self.command_status=text('Ожидание команды','commandStatus',True);self.command_status.setMinimumHeight(34);self.command_status.setMaximumHeight(55);outer_shell.addWidget(self.command_status)
        self.stop_button=action('СТОП',self._stop,'stop','stop');self.stop_button.setToolTip('Остановка локальной модели. При просмотре TXT — пауза записи. Не аппаратная аварийная остановка.');outer_shell.addWidget(self.stop_button)
        outer_shell.addWidget(text('Пробел / Esc · остановка модели','muted'))
        return inspector

    def _build_diagnostics(self):
        tabs=QTabWidget();tabs.tabBar().hide();tabs.setMinimumHeight(100)
        self.telemetry=QTableWidget(0,3);self.telemetry.setHorizontalHeaderLabels(['Показатель / канал','Значение','Единица'])
        self._configure_table(self.telemetry);self.telemetry.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch);self.telemetry.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.ResizeToContents);self.telemetry.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.ResizeToContents);tabs.addTab(self.telemetry,'Телеметрия')
        self.sensor_page=self._build_sensor_page();tabs.addTab(self.sensor_page,'Датчики / TXT')
        self.warning_table=QTableWidget(0,3);self.warning_table.setHorizontalHeaderLabels(['Уровень','Платформа','Предупреждение']);self._configure_table(self.warning_table)
        for i in (0,1):self.warning_table.horizontalHeader().setSectionResizeMode(i,QHeaderView.ResizeMode.ResizeToContents)
        self.warning_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch);self.warning_table.cellDoubleClicked.connect(self._warning_selected);self.warning_tab_index=tabs.addTab(self.warning_table,'Предупреждения')
        self.log_page=QWidget();l=QVBoxLayout(self.log_page);l.setContentsMargins(12,12,12,8)
        filters=QHBoxLayout();filters.addWidget(text('Журнал сеанса','section'));filters.addStretch();self.log_scope=QComboBox();self.log_scope.addItems(['Все устройства','Выбранное устройство']);self.log_scope.currentIndexChanged.connect(lambda _:self._refresh());filters.addWidget(self.log_scope)
        self.log_level=QComboBox();self.log_level.addItems(['Все события','Предупреждения и ошибки']);self.log_level.currentIndexChanged.connect(lambda _:self._refresh());filters.addWidget(self.log_level);l.addLayout(filters)
        self.log=QTextEdit();self.log.setReadOnly(True);self.log.document().setMaximumBlockCount(400);l.addWidget(self.log);tabs.addTab(self.log_page,'События')
        self.profile_details=text('',wrap=True);self.profile_details.setMargin(20);self.profile_details.setAlignment(Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignLeft);tabs.addTab(self.profile_details,'Профиль')
        self.camera_page=self._empty_page('camera','Видеопоток не настроен','Для выбранной платформы нет источника видео.\nДобавьте провайдер потока после выбора оборудования.\nСимуляция не создаёт фиктивное изображение.');tabs.addTab(self.camera_page,'Камера')
        self.integration_page=self._empty_page('connect','Подключение оборудования','Сейчас используется локальный MockAdapter.\nРеальный транспорт подключается через RobotAdapter.\nПротокол и оборудование ещё не выбраны.');tabs.addTab(self.integration_page,'Интеграция')
        tabs.currentChanged.connect(self._panel_changed)
        return tabs

    @staticmethod
    def _configure_table(table):
        table.verticalHeader().hide();table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers);table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows);table.setAlternatingRowColors(True);table.setShowGrid(False);table.verticalHeader().setDefaultSectionSize(34)

    def _empty_page(self,symbol,title,description):
        w=QWidget();v=QVBoxLayout(w);v.setContentsMargins(28,24,28,24);v.addStretch();pic=text('');pic.setPixmap(icon(symbol,'#a8a2db',48).pixmap(48,48));pic.setAlignment(Qt.AlignmentFlag.AlignCenter);v.addWidget(pic)
        h=text(title,'inspectorTitle');h.setAlignment(Qt.AlignmentFlag.AlignCenter);v.addWidget(h)
        d=text(description,'muted',True);d.setAlignment(Qt.AlignmentFlag.AlignCenter);v.addWidget(d);v.addStretch();return w

    def _set_workspace(self,mode):
        self._release_manual();self._workspace_mode=mode
        for key,b in self.view_buttons.items():b.setChecked(key==mode)
        if mode=='map':
            self.tabs.hide();self.map_page.show();self.splitter.setSizes([max(self.splitter.height(),1),0])
        elif mode=='sensors':
            self.tabs.show();self.map_page.show();self.tabs.setCurrentWidget(self.sensor_page);self.splitter.setSizes([max(240,int(self.splitter.height()*.64)),max(215,int(self.splitter.height()*.36))])
        else:
            page={'telemetry':self.telemetry,'events':self.log_page,'camera':self.camera_page}[mode]
            self.tabs.show();self.map_page.hide();self.tabs.setCurrentWidget(page);self.splitter.setSizes([0,max(self.splitter.height(),1)])
        self._animate_context()

    def _show_details(self,page):
        self._release_manual();self.tabs.show();self.map_page.hide();self.tabs.setCurrentWidget(page)
        for b in self.view_buttons.values():b.setChecked(False)
        self._animate_context()

    def _panel_changed(self,index):
        # Existing callers may select diagnostic widgets directly.
        if not hasattr(self,'sensor_page'):return
        page=self.tabs.widget(index);self.tabs.show()
        mode='sensors' if page is self.sensor_page else 'telemetry' if page is self.telemetry else 'events' if page is self.log_page else 'camera' if page is self.camera_page else 'details'
        self._workspace_mode=mode
        for key,b in self.view_buttons.items():b.setChecked(key==mode)
        self.map_page.setVisible(mode=='sensors')
        if mode=='sensors':self.splitter.setSizes([max(240,int(self.splitter.height()*.64)),max(215,int(self.splitter.height()*.36))])

    def _filter_platforms(self,query):
        query=query.strip().casefold();visible=0
        for row in range(self.platform_list.count()):
            item=self.platform_list.item(row);s=self.service.platforms[item.data(Qt.ItemDataRole.UserRole)]
            match=query in f'{s.info.name} {s.info.kind} {s.info.id}'.casefold();item.setHidden(not match);visible+=match
        if hasattr(self,'search_empty'):self.search_empty.setVisible(visible==0)

    def _control_context_changed(self,index):
        self._release_manual()
        if index==1 and hasattr(self,'tabs'):self._set_workspace('map')

    def _animate_context(self):
        if not hasattr(self,'_fade'):return
        self._fade.stop();self._fade_effect.setOpacity(1.0)
        if not self._reduced_motion:
            self._fade.setStartValue(.82);self._fade.setEndValue(1.0);self._fade.start()

    def _toggle_fullscreen(self):
        self._release_manual()
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _open_settings(self):
        self._release_manual();dialog=QDialog(self);dialog.setWindowTitle('Настройки рабочего пространства');dialog.setMinimumWidth(420);v=QVBoxLayout(dialog);v.setContentsMargins(24,24,24,24);v.setSpacing(16)
        v.addWidget(text('Рабочее пространство','inspectorTitle'))
        reduced=QCheckBox('Уменьшить анимацию');reduced.setChecked(self._reduced_motion);v.addWidget(reduced)
        v.addWidget(text('Светлая тема · системная типографика\nДвижение на карте всегда определяется данными.','muted',True))
        v.addWidget(divider());v.addWidget(text('Локальная учебная симуляция','section'));v.addWidget(text('Координаты заданы в метрах внутри условного поля.\nПодключений к физическим роботам нет.\nНастройки действуют до закрытия приложения.','muted',True))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);v.addWidget(buttons)
        if dialog.exec()==QDialog.DialogCode.Accepted:self.set_reduced_motion(reduced.isChecked())

    def set_reduced_motion(self,enabled):
        self._reduced_motion=bool(enabled)
        if enabled:self._fade.stop();self._fade_effect.setOpacity(1.0)

    def _record_command(self,method,error=None):
        names={'connect':'Подключение','disconnect':'Отключение','stop':'STOP','set_route':'Маршрут','start_mission':'START','pause_mission':'PAUSE','resume_mission':'RESUME','cancel_mission':'Отмена миссии','reset':'Сброс'}
        self._command_results[self.selected_id]=(f'Отклонено · {error}' if error else f'Принято локальной моделью · {names.get(method,method)}',bool(error))

    def _refresh_workspace(self):
        state=self._display_state();player=self._replays.get(self.selected_id)
        self.context_title.setText(state.info.name.replace(' — заглушка','') if state.info.name.endswith(' — заглушка') else state.info.name)
        self.context_mode.setText('TXT / RECORDING' if player else state.mode)
        self.fleet_count.setText(str(len(self.service.platforms)))
        for row in range(self.platform_list.count()):
            item=self.platform_list.item(row);s=self.service.platforms[item.data(Qt.ItemDataRole.UserRole)];rp=self._replays.get(s.info.id)
            age=s.telemetry_age_s;stale=s.connected and (age is None or age>2)
            critical=any(w.level=='CRITICAL' for w in warnings_for(s))
            status='TXT · запись' if rp else 'Отключено' if not s.connected else 'Устаревшие данные' if stale else s.mode
            color='#6257d5' if rp else '#9295a1' if not s.connected else '#b43d46' if critical else '#976715' if stale else '#23735c'
            data={'kind':s.info.kind,'id':s.info.id,'name':s.info.name.replace(' — заглушка',''),'status':status,'color':color,'metrics':('Данные из файла' if rp else f'Заряд {self._percent_text(s,"battery_percent")}   ·   Связь {self._percent_text(s,"link_quality_percent")}')}
            if item.data(Qt.ItemDataRole.UserRole+1)!=data:item.setData(Qt.ItemDataRole.UserRole+1,data)
        self.platform_list.viewport().update()
        result,error=(('TXT · управление отключено',False) if player else self._command_results.get(self.selected_id,('Ожидание команды',False)));self.command_status.setText(result);self.command_status.setToolTip(result)
        self.command_status.setStyleSheet('color: #b43d46; background: #fff1f2; padding: 9px; border-radius: 6px;' if error else '')
        self.route_points.setVisible(player is None)
        self.mission_progress.setVisible(player is None)
        if player:self.route_info.setText('TXT · траектория из файла')
        self.route_hint.setText('Просмотр записи. Маршрут симулятора скрыт; для управления нажмите «К симуляции».' if player else 'Включите «Добавлять точки» и укажите их на карте. Одна точка — переход к цели.')
        self.mission_progress.setRange(0,max(len(state.route),1));self.mission_progress.setValue(min(state.waypoint_index,len(state.route)))
        signature=(self.selected_id,tuple((p.x,p.y) for p in state.route),state.waypoint_index,state.mission_status)
        if getattr(self,'_route_signature',None)!=signature:
            self._route_signature=signature;self.route_points.clear()
            for i,p in enumerate(state.route):
                status='Пройдена' if i<state.waypoint_index else 'Цель' if i==state.waypoint_index and state.mission_status in ('RUNNING','PAUSED') else 'Точка'
                self.route_points.addItem(f'{i+1:02}  {status}    {p.x:g} / {p.y:g} м')
        self.speed_trace.set_samples(deque() if player else self._speed_history[self.selected_id])
        self.connection_button.setText('')
        self.connection_button.setToolTip('Источник TXT' if player else 'Отключить демо' if state.connected else 'Подключить демо')
        self.connection_button.setAccessibleName(self.connection_button.toolTip())

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'speed_trace'):
            self.speed_trace.setVisible(self.height()>=980)

    def _sample_metrics(self):
        now=time.monotonic()
        if now-self._last_sample<.2:return
        self._last_sample=now
        for pid,s in self.service.platforms.items():
            # Recordings have their own timeline; never mix their values with live history.
            if pid in self._replays:continue
            fresh=s.connected and s.telemetry_age_s is not None and s.telemetry_age_s<=2
            self._speed_history[pid].append(s.speed if fresh else None)
