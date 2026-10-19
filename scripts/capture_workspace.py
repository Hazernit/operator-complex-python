"""Repeatable visual QA: saves real native Qt windows without hardware access."""
from __future__ import annotations
import os
from pathlib import Path
import sys

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import PySide6
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
from operator_stub.models import Point
from operator_stub.ui import OperatorWindow

ROOT=Path(__file__).resolve().parents[1]
QCoreApplication.addLibraryPath(str(Path(PySide6.__file__).parent/'Qt/plugins'))
app=QApplication.instance() or QApplication(['workspace-visual-qa'])
window=OperatorWindow();window.timer.stop();window.set_reduced_motion(True)
window.show();app.processEvents()
window._call('set_route',[Point(38,30),Point(38,45),Point(55,45)])
window.control_tabs.setCurrentIndex(1);window._mission_action('start_mission')
for _ in range(70):
    window.service.tick(.05)
    s=window.state;window.trails[window.selected_id].append((s.pose.x,s.pose.y))
window._refresh()
folder=ROOT/'output/screenshots';folder.mkdir(parents=True,exist_ok=True)
def capture(name,width=1440,height=900):
    window.resize(width,height);app.processEvents();window._refresh();app.processEvents()
    assert window.size().width()==width and window.size().height()==height,(name,window.size())
    assert window.grab().save(str(folder/name))
    print(name,width,height)
for width,height in [(1280,800),(1440,900),(1920,1080)]:capture(f'overview-{width}x{height}.png',width,height)
window._set_workspace('telemetry');capture('telemetry.png')
window.load_sensor_file(ROOT/'examples/lidar-room.txt');window._seek_recording(500);capture('sensors.png')
window._leave_replay();window._set_workspace('map');window._call('disconnect');capture('offline.png')
window._select_platform(next(pid for pid,s in window.service.platforms.items() if s.info.kind=='БПЛА'));window._set_workspace('camera');capture('camera-unconfigured.png')
window.close();app.processEvents()
