"""Visual tokens and small native Qt components; no transport dependencies."""
from __future__ import annotations

from collections import deque
from PySide6.QtCore import QPointF, QRectF, Qt, QSize
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QStyledItemDelegate, QStyle, QWidget

COLORS = {
    'canvas': '#f7f8fa', 'surface': '#ffffff', 'sidebar': '#f3f4f7',
    'text': '#252733', 'muted': '#757986', 'line': '#e6e7ec',
    'accent': '#6257d5', 'accent_soft': '#eeecfb', 'success': '#23735c',
    'warning': '#976715', 'danger': '#b43d46',
}
SPACE = (4, 8, 12, 16, 24, 32)
MOTION = {'micro': 120, 'context': 180, 'layout': 220}

STYLE = '''
QWidget { font-family: ".AppleSystemUIFont", "Segoe UI", "DejaVu Sans"; font-size: 13px; color: #252733; }
QMainWindow, QWidget#workspace { background: #f7f8fa; }
QWidget#sidebar { background: #f3f4f7; border-right: 1px solid #e6e7ec; }
QWidget#inspector, QWidget#commandPage, QFrame#surface { background: #ffffff; }
QFrame#surface { border: 1px solid #e6e7ec; border-radius: 10px; }
QFrame#metric { background: transparent; border: none; }
QFrame#divider { background: #e6e7ec; max-height: 1px; }
QLabel { background: transparent; }
QLabel#brand { font-size: 17px; font-weight: 650; letter-spacing: -0.4px; }
QLabel#heading { font-size: 26px; font-weight: 650; letter-spacing: -0.6px; }
QLabel#section { font-size: 11px; font-weight: 600; color: #757986; letter-spacing: 1px; }
QLabel#muted, QLabel#sidebarNote { color: #757986; font-size: 12px; }
QLabel#metricValue { font-size: 23px; font-weight: 550; letter-spacing: -0.4px; }
QLabel#badge { color: #6257d5; background: #eeecfb; border-radius: 5px; padding: 4px 8px; font-size: 11px; font-weight: 600; }
QLabel#warning { color: #757986; font-size: 11px; }
QLabel#inspectorTitle { font-size: 17px; font-weight: 600; }
QLabel#commandStatus { color: #6257d5; background: #f4f3fc; padding: 9px; border-radius: 6px; font-size: 11px; }
QPushButton, QToolButton { background: #ffffff; border: 1px solid #dfe0e7; border-radius: 6px; padding: 7px 11px; font-weight: 500; }
QPushButton:hover, QToolButton:hover { background: #f2f1fa; border-color: #c7c3e9; }
QPushButton:pressed, QToolButton:pressed { background: #e9e6fa; }
QPushButton:focus, QToolButton:focus, QLineEdit:focus, QComboBox:focus { border: 1px solid #6257d5; }
QPushButton:disabled, QToolButton:disabled { color: #a7a9b3; background: #f6f6f8; border-color: #e9e9ee; }
QPushButton#primary { background: #6257d5; color: white; border-color: #6257d5; }
QPushButton#primary:hover { background: #5348c2; }
QPushButton#primary:pressed { background: #453aa9; }
QPushButton#primary:disabled { background: #d8d5f2; border-color: #d8d5f2; color: #ffffff; }
QPushButton#stop { background: #fff5f5; border-color: #e9c4c8; color: #b43d46; padding: 10px; font-weight: 650; }
QPushButton#stop:hover { background: #fde8ea; border-color: #ce8e96; }
QPushButton#stop:pressed { background: #f7d2d7; }
QPushButton#direction { background: #f9f9fc; padding: 3px; border-radius: 8px; font-size: 21px; }
QPushButton#direction:pressed { color: #6257d5; background: #e9e6fa; }
QPushButton#quiet { background: transparent; border-color: transparent; color: #656977; text-align: left; padding: 8px; }
QPushButton#quiet:hover { background: #e9e9f1; color: #252733; }
QPushButton#nav { background: transparent; border-color: transparent; color: #757986; padding: 6px 10px; }
QPushButton#nav:checked { background: white; color: #5147be; border-color: #e1dff3; }
QPushButton#nav:hover { background: #eeeef5; }
QLineEdit, QComboBox { background: #ffffff; border: 1px solid #dfe0e7; border-radius: 6px; padding: 7px 9px; selection-background-color: #dcd8fb; }
QComboBox::drop-down { border: none; width: 19px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #eeecfb; selection-color: #252733; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { border: none; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QTabWidget::pane { background: white; border: none; }
QTabBar::tab { background: #f7f7fa; color: #757986; padding: 7px 14px; border-bottom: 1px solid #e6e7ec; }
QTabBar::tab:selected { background: white; color: #6257d5; border-bottom: 2px solid #6257d5; }
QTableWidget { background: white; alternate-background-color: #fafafd; border: none; gridline-color: #f0f0f5; selection-background-color: #eeecfb; selection-color: #252733; }
QHeaderView::section { background: #f8f8fb; border: none; border-bottom: 1px solid #e6e7ec; color: #757986; padding: 9px; font-size: 11px; font-weight: 500; }
QTableCornerButton::section { background: #f8f8fb; border: none; }
QTextEdit { background: white; border: none; font-family: "Menlo", "Consolas", monospace; font-size: 11px; padding: 6px; }
QProgressBar { border: none; background: #eeedf3; border-radius: 2px; max-height: 4px; }
QProgressBar::chunk { background: #6257d5; border-radius: 2px; }
QSlider::groove:horizontal { height: 4px; background: #e9e8f0; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #8177df; border-radius: 2px; }
QSlider::handle:horizontal { width: 13px; margin: -5px 0; background: white; border: 2px solid #8177df; border-radius: 7px; }
QCheckBox { spacing: 7px; font-size: 12px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #cacbd5; border-radius: 4px; background: white; }
QCheckBox::indicator:checked { background: #6257d5; border-color: #6257d5; }
QCheckBox::indicator:disabled { background: #e8e8ee; border-color: #ddddE5; }
QSplitter::handle { background: #f0f0f5; }
QSplitter::handle:hover { background: #dcd8f5; }
QScrollBar:vertical { background: transparent; width: 7px; margin: 2px; }
QScrollBar::handle:vertical { background: #d2d2dd; border-radius: 2px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QStatusBar { background: #f7f8fa; color: #757986; font-size: 11px; border-top: 1px solid #e6e7ec; }
QStatusBar::item { border: none; }
QMenu { background: white; border: 1px solid #e2e2eb; padding: 5px; }
QMenu::item { padding: 7px 20px 7px 10px; border-radius: 4px; }
QMenu::item:selected { background: #eeecfb; color: #5147be; }
QToolTip { color: #252733; background: #ffffff; border: 1px solid #dfe0e7; padding: 6px; }
QDialog { background: #f7f8fa; }
'''


def draw_symbol(p: QPainter, name: str, color='#747888'):
    """Original stroke icons in a consistent 24 × 24 coordinate space."""
    p.setPen(QPen(QColor(color), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    if name in ('БПЛА', 'drone'):
        p.drawLine(7, 7, 17, 17); p.drawLine(7, 17, 17, 7)
        for x, y in ((6, 6), (18, 6), (6, 18), (18, 18)):
            p.drawEllipse(QPointF(x, y), 3.3, 3.3)
        p.drawRoundedRect(QRectF(9, 9, 6, 6), 2, 2)
    elif name in ('НРТК', 'ground'):
        p.drawRoundedRect(QRectF(5, 7, 14, 10), 2, 2)
        for x, y in ((6, 4), (15, 4), (6, 18), (15, 18)):
            p.drawRoundedRect(QRectF(x, y, 3, 3), 1, 1)
        p.drawLine(12, 8, 12, 4)
    elif name in ('БЭК', 'boat'):
        p.drawPolygon(QPolygonF([QPointF(3, 14), QPointF(7, 20), QPointF(17, 20), QPointF(21, 14), QPointF(12, 10)]))
        p.drawLine(8, 11, 8, 6); p.drawLine(8, 6, 16, 6); p.drawLine(16, 6, 16, 11)
        p.drawLine(12, 6, 12, 3)
    elif name == 'map':
        p.drawPolyline(QPolygonF([QPointF(3, 5), QPointF(9, 3), QPointF(15, 6), QPointF(21, 3), QPointF(21, 19), QPointF(15, 22), QPointF(9, 19), QPointF(3, 21), QPointF(3, 5)]))
        p.drawLine(9, 3, 9, 19); p.drawLine(15, 6, 15, 22)
    elif name == 'chart':
        p.drawLine(4, 3, 4, 20); p.drawLine(4, 20, 21, 20)
        p.drawPolyline(QPolygonF([QPointF(7, 15), QPointF(11, 10), QPointF(15, 13), QPointF(20, 6)]))
    elif name == 'sensor':
        for r in (4, 8): p.drawArc(QRectF(12-r, 12-r, 2*r, 2*r), 20*16, 140*16)
        p.drawLine(12, 12, 17, 6); p.drawEllipse(QPointF(12, 12), 1.5, 1.5)
        p.drawLine(5, 20, 12, 12); p.drawLine(19, 20, 12, 12)
    elif name == 'log':
        p.drawRoundedRect(QRectF(4, 3, 16, 18), 2, 2)
        for y in (8, 12, 16): p.drawLine(8, y, 16, y)
    elif name == 'camera':
        p.drawRoundedRect(QRectF(3, 6, 13, 12), 2, 2)
        p.drawPolygon(QPolygonF([QPointF(16, 10), QPointF(21, 7), QPointF(21, 17), QPointF(16, 14)]))
    elif name == 'settings':
        for y, x in ((6, 9), (12, 16), (18, 7)):
            p.drawLine(3, y, x-2, y); p.drawLine(x+2, y, 21, y); p.drawEllipse(QPointF(x, y), 2, 2)
    elif name == 'export':
        p.drawLine(12, 15, 12, 3); p.drawLine(8, 7, 12, 3); p.drawLine(12, 3, 16, 7)
        p.drawPolyline(QPolygonF([QPointF(4, 13), QPointF(4, 21), QPointF(20, 21), QPointF(20, 13)]))
    elif name == 'reset':
        p.drawArc(QRectF(4, 4, 16, 16), -45*16, 290*16)
        p.drawPolyline(QPolygonF([QPointF(3, 3), QPointF(3, 10), QPointF(10, 10)]))
    elif name == 'center':
        p.drawEllipse(QPointF(12, 12), 6, 6); p.drawEllipse(QPointF(12, 12), 1.8, 1.8)
        for a,b,c,d in ((12,2,12,5),(12,19,12,22),(2,12,5,12),(19,12,22,12)): p.drawLine(a,b,c,d)
    elif name == 'fullscreen':
        for points in (((3,9),(3,3),(9,3)),((15,3),(21,3),(21,9)),((21,15),(21,21),(15,21)),((9,21),(3,21),(3,15))):
            p.drawPolyline(QPolygonF([QPointF(*pt) for pt in points]))
    elif name == 'search':
        p.drawEllipse(QPointF(10, 10), 6, 6); p.drawLine(15,15,21,21)
    elif name == 'connect':
        p.drawArc(QRectF(4, 4, 16, 16), 130*16, 280*16); p.drawLine(12, 2, 12, 12)
    elif name == 'route':
        p.drawEllipse(QPointF(5,18),2,2); p.drawEllipse(QPointF(19,5),2,2)
        path=QPainterPath(QPointF(7,18));path.cubicTo(24,18,0,5,17,5);p.drawPath(path)
    elif name == 'stop':
        p.drawRoundedRect(QRectF(6,6,12,12),1,1)
    else:
        p.drawEllipse(QPointF(12,12),8,8); p.drawLine(12,7,12,13); p.drawPoint(12,17)


def icon(name, color='#747888', size=18):
    pix=QPixmap(size*2, size*2); pix.fill(Qt.GlobalColor.transparent); pix.setDevicePixelRatio(2)
    p=QPainter(pix); p.setRenderHint(QPainter.RenderHint.Antialiasing); p.scale(size/24,size/24)
    draw_symbol(p,name,color); p.end(); return QIcon(pix)


class PlatformDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save(); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect=QRectF(option.rect).adjusted(1,3,-1,-3)
        selected=bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setPen(QPen(QColor('#dad6f4' if selected else '#e6e7ec'),1))
        painter.setBrush(QColor('#ffffff' if selected else '#f7f8fa'))
        painter.drawRoundedRect(rect,8,8)
        if selected:
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor('#6257d5'))
            painter.drawRoundedRect(QRectF(rect.x()+1,rect.y()+16,3,rect.height()-32),1.5,1.5)
        data=index.data(Qt.ItemDataRole.UserRole+1) or {}
        x,y=rect.x()+13,rect.y()+13
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor('#eeecfb' if selected else '#eaeaf0'))
        painter.drawRoundedRect(QRectF(x,y,32,32),7,7)
        painter.save(); painter.translate(x+6,y+6); painter.scale(20/24,20/24)
        draw_symbol(painter,data.get('kind',''), '#6257d5' if selected else '#747888'); painter.restore()
        font=QFont(option.font); font.setPointSize(12); font.setWeight(QFont.Weight.DemiBold); painter.setFont(font); painter.setPen(QColor('#252733'))
        name=data.get('name','Платформа')
        painter.drawText(QRectF(x+42,y-1,rect.width()-70,20),Qt.AlignmentFlag.AlignLeft,painter.fontMetrics().elidedText(name,Qt.TextElideMode.ElideRight,int(rect.width()-70)))
        font.setPointSize(9);font.setWeight(QFont.Weight.Normal);painter.setFont(font);painter.setPen(QColor('#757986'))
        painter.drawText(QRectF(x+42,y+18,rect.width()-70,18),Qt.AlignmentFlag.AlignLeft,data.get('id',''))
        status=data.get('status','Отключено');color=data.get('color','#989ba7')
        painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor(color));painter.drawEllipse(QPointF(x+3,y+53),3,3)
        painter.setPen(QColor(color));painter.drawText(QRectF(x+13,y+44,rect.width()-32,18),Qt.AlignmentFlag.AlignLeft,status)
        painter.setPen(QColor('#757986'))
        painter.drawText(QRectF(x,y+67,rect.width()-25,18),Qt.AlignmentFlag.AlignLeft,data.get('metrics',''))
        painter.restore()

    def sizeHint(self, option, index): return QSize(205,112)


class Sparkline(QWidget):
    """A bounded trace of actual samples; unavailable intervals break the line."""
    def __init__(self, parent=None):
        super().__init__(parent); self.samples=deque(maxlen=150);self.setMinimumHeight(52)
        self.setAccessibleName('График измеренной скорости за последние 30 секунд')
    def set_samples(self, samples): self.samples=samples;self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r=QRectF(self.rect()).adjusted(1,6,-1,-8)
        p.setPen(QPen(QColor('#ecebf4'),1));p.drawLine(r.bottomLeft(),r.bottomRight())
        valid=[v for v in self.samples if v is not None]
        if len(valid)<2:
            p.setPen(QColor('#9295a1'));p.drawText(r,Qt.AlignmentFlag.AlignCenter,'Ожидание измерений');return
        peak=max(max(valid),0.2);path=QPainterPath();active=False
        for i,v in enumerate(self.samples):
            if v is None:active=False;continue
            point=QPointF(r.left()+r.width()*i/max(len(self.samples)-1,1),r.bottom()-r.height()*v/peak)
            if active:path.lineTo(point)
            else:path.moveTo(point);active=True
        p.setPen(QPen(QColor('#8177db'),1.8));p.drawPath(path)
