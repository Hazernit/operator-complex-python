"""Keyboard controls through actual Qt events, including a Russian layout."""
from __future__ import annotations

import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

try:
    import PySide6
    from PySide6.QtCore import QCoreApplication, QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (
        QApplication, QComboBox, QDialog, QDoubleSpinBox, QLineEdit,
        QPlainTextEdit, QTextEdit, QVBoxLayout,
    )
except ImportError:
    QT_AVAILABLE = False
else:
    QT_AVAILABLE = True
    from operator_stub.models import Point
    from operator_stub.ui import OperatorWindow


@unittest.skipUnless(QT_AVAILABLE, 'Для проверок GUI нужен PySide6-Essentials')
class KeyboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plugins = Path(PySide6.__file__).parent / 'Qt' / 'plugins'
        if plugins.is_dir():
            QCoreApplication.addLibraryPath(str(plugins))
        cls.app = QApplication.instance() or QApplication(['keyboard-tests'])

    def setUp(self):
        self.window = OperatorWindow()
        self.window.timer.stop()
        self.window.show()
        self.window.telemetry.setFocus()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()

    def event(self, kind, key, text='', repeat=False, modifiers=Qt.KeyboardModifier.NoModifier):
        event = QKeyEvent(kind, key, modifiers, text, repeat)
        self.app.sendEvent(self.window.telemetry, event)
        return event

    def test_wasd_works_immediately_without_space(self):
        self.assertTrue(self.window.keyboard_checkbox.isChecked())
        QTest.keyPress(self.window.telemetry, Qt.Key.Key_W)
        self.assertGreater(self.window.state.desired_forward, 0)
        QTest.keyRelease(self.window.telemetry, Qt.Key.Key_W)
        self.assertEqual(self.window.state.desired_forward, 0)
        self.assertEqual(self.window._keys, set())

    def test_russian_unicode_keys_and_text_are_supported(self):
        cases = [('ц', 'desired_forward', 1), ('ы', 'desired_forward', -1),
                 ('ф', 'desired_turn', 1), ('в', 'desired_turn', -1)]
        for letter, attribute, direction in cases:
            for uppercase in (False, True):
                text = letter.upper() if uppercase else letter
                with self.subTest(text=text):
                    self.event(QEvent.Type.KeyPress, ord(text.upper()), text)
                    self.assertGreater(getattr(self.window.state, attribute) * direction, 0)
                    self.event(QEvent.Type.KeyRelease, ord(text.upper()), text)
                    self.assertEqual(getattr(self.window.state, attribute), 0)
        self.event(QEvent.Type.KeyPress, Qt.Key.Key_unknown, 'ц')
        self.assertGreater(self.window.state.desired_forward, 0)
        self.event(QEvent.Type.KeyRelease, Qt.Key.Key_unknown, 'ц')
        self.assertEqual(self.window.state.desired_forward, 0)

    def test_simultaneous_keys_and_opposing_axes(self):
        QTest.keyPress(self.window.telemetry, Qt.Key.Key_W)
        QTest.keyPress(self.window.telemetry, Qt.Key.Key_D)
        self.assertGreater(self.window.state.desired_forward, 0)
        self.assertLess(self.window.state.desired_turn, 0)
        QTest.keyPress(self.window.telemetry, Qt.Key.Key_S)
        self.assertEqual(self.window.state.desired_forward, 0)
        QTest.keyRelease(self.window.telemetry, Qt.Key.Key_S)
        self.assertGreater(self.window.state.desired_forward, 0)
        QTest.keyRelease(self.window.telemetry, Qt.Key.Key_W)
        self.assertEqual(self.window.state.desired_forward, 0)
        self.assertLess(self.window.state.desired_turn, 0)
        QTest.keyRelease(self.window.telemetry, Qt.Key.Key_D)
        self.assertEqual(self.window.state.desired_turn, 0)

    def test_arrow_and_letter_for_same_axis_can_be_released_independently(self):
        QTest.keyPress(self.window.telemetry, Qt.Key.Key_W)
        QTest.keyPress(self.window.telemetry, Qt.Key.Key_Up)
        QTest.keyRelease(self.window.telemetry, Qt.Key.Key_W)
        self.assertGreater(self.window.state.desired_forward, 0)
        QTest.keyRelease(self.window.telemetry, Qt.Key.Key_Up)
        self.assertEqual(self.window.state.desired_forward, 0)

    def test_auto_repeat_release_does_not_interrupt_held_key(self):
        QTest.keyPress(self.window.telemetry, Qt.Key.Key_W)
        self.event(QEvent.Type.KeyRelease, Qt.Key.Key_W, 'w', repeat=True)
        self.assertGreater(self.window.state.desired_forward, 0)
        self.event(QEvent.Type.KeyPress, Qt.Key.Key_W, 'w', repeat=True)
        self.assertGreater(self.window.state.desired_forward, 0)
        QTest.keyRelease(self.window.telemetry, Qt.Key.Key_W)
        self.assertEqual(self.window.state.desired_forward, 0)

    def test_space_and_escape_stop_and_clear_input(self):
        for stop_key in (Qt.Key.Key_Space, Qt.Key.Key_Escape):
            with self.subTest(stop_key=stop_key):
                QTest.keyPress(self.window.telemetry, Qt.Key.Key_W)
                QTest.keyClick(self.window.telemetry, stop_key)
                self.assertEqual(self.window.state.desired_forward, 0)
                self.assertEqual(self.window._keys, set())

    def test_space_and_escape_stop_mission_while_manual_keyboard_is_disabled(self):
        for stop_key in (Qt.Key.Key_Space, Qt.Key.Key_Escape):
            with self.subTest(stop_key=stop_key):
                if self.window.state.mission_status == 'PAUSED':
                    self.window.service.cancel_mission(self.window.selected_id)
                pose = self.window.state.pose
                self.window.service.set_route(self.window.selected_id, [Point(pose.x + 5, pose.y)])
                self.window.service.start_mission(self.window.selected_id)
                self.window._refresh()
                self.assertFalse(self.window.keyboard_checkbox.isEnabled())
                self.assertTrue(self.window.keyboard_checkbox.isChecked())
                QTest.keyPress(self.window.telemetry, Qt.Key.Key_W)
                self.assertEqual(self.window._keys, set())
                QTest.keyClick(self.window.telemetry, stop_key)
                self.assertEqual(self.window.state.mission_status, 'PAUSED')

    def test_disable_keyboard_clears_input_and_preserves_widget_navigation(self):
        QTest.keyPress(self.window.telemetry, Qt.Key.Key_W)
        self.window.keyboard_checkbox.setChecked(False)
        self.assertEqual(self.window.state.desired_forward, 0)
        self.assertEqual(self.window._keys, set())
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
        self.assertFalse(self.window.eventFilter(self.window.telemetry, event))
        QTest.keyPress(self.window.telemetry, Qt.Key.Key_W)
        self.assertEqual(self.window.state.desired_forward, 0)

    def test_editors_accept_text_without_driving_and_focus_transition_releases(self):
        widgets = [QLineEdit(self.window), QTextEdit(self.window), QPlainTextEdit(self.window),
                   QDoubleSpinBox(self.window), QComboBox(self.window)]
        widgets[-1].setEditable(True)
        for widget in widgets:
            with self.subTest(widget=type(widget).__name__):
                self.window.telemetry.setFocus()
                QTest.keyPress(self.window.telemetry, Qt.Key.Key_W)
                self.assertGreater(self.window.state.desired_forward, 0)
                widget.show()
                widget.setFocus()
                self.app.processEvents()
                self.assertEqual(self.window.state.desired_forward, 0)
                event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_W, Qt.KeyboardModifier.NoModifier, 'w')
                self.assertFalse(self.window.eventFilter(widget, event))
                self.app.sendEvent(widget, event)
                self.assertEqual(self.window.state.desired_forward, 0)
                widget.hide()
        self.assertEqual(widgets[0].text(), 'w')

    def test_parented_dialog_and_its_child_are_excluded(self):
        dialog = QDialog(self.window)
        layout = QVBoxLayout(dialog)
        text = QLineEdit()
        layout.addWidget(text)
        dialog.show()
        text.setFocus()
        self.app.processEvents()
        for watched in (dialog, text):
            event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_W, Qt.KeyboardModifier.NoModifier, 'w')
            self.assertFalse(self.window.eventFilter(watched, event))
        QTest.keyClicks(text, 'wasd')
        self.assertEqual(text.text(), 'wasd')
        self.assertEqual(self.window.state.desired_forward, 0)
        dialog.close()

    def test_readonly_log_accepts_control_keys(self):
        self.window.log.setFocus()
        self.app.processEvents()
        QTest.keyPress(self.window.log, Qt.Key.Key_W)
        self.assertGreater(self.window.state.desired_forward, 0)
        QTest.keyRelease(self.window.log, Qt.Key.Key_W)
        self.assertEqual(self.window.state.desired_forward, 0)

    def test_control_shortcuts_do_not_start_motion(self):
        self.event(QEvent.Type.KeyPress, Qt.Key.Key_W, 'w', modifiers=Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.window.state.desired_forward, 0)
        self.assertEqual(self.window._keys, set())

    def test_switching_platform_releases_previous_platform(self):
        previous = self.window.state
        QTest.keyPress(self.window.telemetry, Qt.Key.Key_W)
        other = next(platform_id for platform_id in self.window.service.platforms if platform_id != self.window.selected_id)
        self.window._select_platform(other)
        self.assertEqual(previous.desired_forward, 0)
        self.assertEqual(self.window.state.desired_forward, 0)
        self.assertEqual(self.window._keys, set())

    def test_window_activation_loss_releases_input(self):
        QTest.keyPress(self.window.telemetry, Qt.Key.Key_W)
        with patch.object(self.window, 'isActiveWindow', return_value=False):
            self.window.changeEvent(QEvent(QEvent.Type.ActivationChange))
        self.assertEqual(self.window.state.desired_forward, 0)
        self.assertEqual(self.window._keys, set())

    def test_native_macos_virtual_key_fallback_only_with_native_data(self):
        with patch('operator_stub.ui.sys.platform', 'darwin'):
            synthetic = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_unknown, Qt.KeyboardModifier.NoModifier)
            self.assertIsNone(self.window._control_key(synthetic))
            native = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_unknown, Qt.KeyboardModifier.NoModifier,
                               0, 13, 0, '')
            self.assertEqual(self.window._control_key(native), Qt.Key.Key_W)


if __name__ == '__main__':
    unittest.main()
