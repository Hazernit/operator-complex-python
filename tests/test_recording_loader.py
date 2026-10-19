"""Real background parsing, request isolation, and an active GUI event loop."""
from __future__ import annotations

from copy import deepcopy
import gc
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import weakref

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

try:
    import PySide6
    from PySide6.QtCore import QCoreApplication, QThreadPool, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:
    QT_AVAILABLE = False
else:
    QT_AVAILABLE = True
    from operator_stub import recording_loader
    from operator_stub.recording_loader import RecordingLoader

from operator_stub.playback import RecordingPlayer
from operator_stub.sensor_data import load_recording
from operator_stub.service import OperatorService


HEADER = 'time_s,type,x_m,y_m,heading_deg,angle_deg,range_m\n'


@unittest.skipUnless(QT_AVAILABLE, 'Для фоновой загрузки нужен PySide6-Essentials')
class RecordingLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plugins = Path(PySide6.__file__).parent / 'Qt' / 'plugins'
        if plugins.is_dir():
            QCoreApplication.addLibraryPath(str(plugins))
        cls.app = QApplication.instance() or QApplication(['recording-loader-tests'])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.valid = Path(self.folder.name) / 'valid.txt'
        self.valid.write_text(HEADER + '10,pose,1,2,0,,\n10,lidar,,,,0,5\n'
                              '12,pose,3,2,0,,\n', encoding='utf-8')
        self.invalid = Path(self.folder.name) / 'invalid.txt'
        self.invalid.write_text(HEADER + '0,lidar,,,,0,5\n', encoding='utf-8')
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(2)
        self.loader = RecordingLoader(pool=self.pool)
        self.successes = []
        self.failures = []
        self.loader.success.connect(lambda *args: self.successes.append(args))
        self.loader.failure.connect(lambda *args: self.failures.append(args))

    def tearDown(self):
        self.pool.waitForDone(10000)
        self.app.processEvents()
        self.folder.cleanup()

    def wait_for_completion(self, timeout=10):
        deadline = time.monotonic() + timeout
        while self.loader.is_loading and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(1)
        self.app.processEvents()
        self.assertFalse(self.loader.is_loading, 'Рабочая задача не завершилась вовремя')

    def test_real_worker_returns_paused_validated_player_and_retains_signals(self):
        request_id = self.loader.start(self.valid, 'ground-1')
        self.assertEqual(self.loader.pending_request_ids, (request_id,))
        signals = weakref.ref(self.loader._jobs[request_id].signals)
        gc.collect()
        self.assertIsNotNone(signals())
        self.wait_for_completion()
        self.assertFalse(self.failures)
        self.assertEqual(len(self.successes), 1)
        result_id, platform_id, player = self.successes[0]
        self.assertEqual((result_id, platform_id), (request_id, 'ground-1'))
        self.assertIsInstance(player, RecordingPlayer)
        self.assertEqual(player.time_s, 10)
        self.assertEqual(player.recording.duration, 2)
        self.assertFalse(player.playing)
        self.assertEqual(player.frame.readings[0].range_m, 5)

    def test_invalid_file_reports_failure_without_touching_existing_state(self):
        current_player = RecordingPlayer(load_recording(self.valid))
        current_player.seek(11)
        current_player.playing = True
        before_player = deepcopy(current_player.__dict__)
        service = OperatorService()
        selected = next(iter(service.platforms))
        service.connect(selected)
        service.set_velocity(selected, 0.5, 0)
        before_state, before_events = deepcopy(service.platforms), tuple(service.events)
        request_id = self.loader.start(self.invalid, selected)
        self.wait_for_completion()
        self.assertFalse(self.successes)
        self.assertEqual(len(self.failures), 1)
        result_id, platform_id, message = self.failures[0]
        self.assertEqual((result_id, platform_id), (request_id, selected))
        self.assertIn('Нужны строки pose', message)
        self.assertEqual(current_player.__dict__, before_player)
        self.assertEqual(service.platforms, before_state)
        self.assertEqual(tuple(service.events), before_events)

    def test_requests_keep_their_original_platform_and_result_identity(self):
        good_id = self.loader.start(self.valid, 'first-platform')
        bad_id = self.loader.start(self.invalid, 'second-platform')
        self.assertNotEqual(good_id, bad_id)
        self.wait_for_completion()
        self.assertEqual(self.successes[0][:2], (good_id, 'first-platform'))
        self.assertEqual(self.failures[0][:2], (bad_id, 'second-platform'))
        self.assertEqual(self.loader.pending_request_ids, ())

    def test_large_real_import_runs_off_gui_thread_while_gui_timer_keeps_ticking(self):
        large = Path(self.folder.name) / 'large.txt'
        # 80,000 rows / 16,000 frames: close to the real parser's supported caps.
        with large.open('w', encoding='utf-8') as stream:
            stream.write(HEADER)
            for index in range(16000):
                stream.write(f'{index},pose,{index / 100:g},{index / 200:g},0,,\n')
                for angle in (0, 90, 180, 270):
                    stream.write(f'{index},lidar,,,,{angle},5\n')
        gui_thread = threading.get_ident()
        parse_threads, result_threads, gui_ticks = [], [], []
        self.loader.success.connect(lambda *_: result_threads.append(threading.get_ident()))
        heartbeat = QTimer()
        heartbeat.setInterval(1)
        heartbeat.timeout.connect(lambda: gui_ticks.append(self.loader.is_loading))

        def observed_real_parse(path):
            # Observe the actual parser's execution thread; no data is mocked.
            parse_threads.append(threading.get_ident())
            return load_recording(path)

        heartbeat.start()
        try:
            with patch.object(recording_loader, 'load_recording', observed_real_parse):
                self.loader.start(large, 'large-source')
                # CI Linux runners can parse 80,000 rows more slowly than local machines.
                # Keep the entire workload and event-loop assertions; allow a realistic wall-clock budget.
                self.wait_for_completion(timeout=45)
        finally:
            heartbeat.stop()
        self.assertFalse(self.failures)
        self.assertEqual(len(self.successes[0][2].recording.frames), 16000)
        self.assertEqual(len(parse_threads), 1)
        self.assertNotEqual(parse_threads[0], gui_thread)
        self.assertEqual(result_threads, [gui_thread])
        self.assertIn(True, gui_ticks, 'GUI должен обрабатывать события до конца импорта')


if __name__ == '__main__':
    unittest.main()
