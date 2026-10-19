"""Проверки поведения заглушки без Qt и реального оборудования."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from operator_stub.models import (
    MISSION_COMPLETED,
    MISSION_PAUSED,
    MISSION_RUNNING,
    Point,
    TEST_DATA_SOURCE,
)
from operator_stub.service import OperatorService


def example_config() -> dict:
    return {
        "schema_version": 1,
        "platforms": [
            {
                "id": "custom-01",
                "name": "Произвольная платформа",
                "kind": "НРТК",
                "initial_pose": {"x": 20, "y": 20, "heading": 0},
                "telemetry_fields": [
                    {"key": "unknown_sensor", "label": "Новый датчик", "unit": "ед.", "value": 42},
                    {"key": "status_text", "label": "Новый статус", "value": "готов"},
                ],
            }
        ],
    }


class OperatorServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = OperatorService()
        self.platform_id = next(iter(self.service.platforms))

    def load_config(self, config: dict) -> OperatorService:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "platforms.json"
            path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            return OperatorService(path)

    def test_all_platform_types_are_test_sources_and_initially_offline(self) -> None:
        self.assertEqual({state.info.kind for state in self.service.platforms.values()}, {"БПЛА", "НРТК", "БЭК"})
        for state in self.service.platforms.values():
            with self.subTest(platform=state.info.id):
                self.assertEqual(state.info.source, TEST_DATA_SOURCE)
                self.assertFalse(state.connected)
                self.assertEqual(state.speed, 0)

    def test_unconfigured_sensor_names_can_be_loaded(self) -> None:
        service = self.load_config(example_config())
        service.connect("custom-01")
        state = service.platforms["custom-01"]
        self.assertEqual(set(state.fields), {"unknown_sensor", "status_text"})
        self.assertEqual(state.fields["unknown_sensor"].label, "Новый датчик")
        self.assertEqual(state.fields["unknown_sensor"].unit, "ед.")
        self.assertEqual(state.fields["unknown_sensor"].value, 42)
        self.assertEqual(state.fields["status_text"].value, "готов")

    def test_example_configuration_is_loadable(self) -> None:
        path = Path(__file__).resolve().parents[1] / "config" / "demo_platforms.json"
        service = OperatorService(path)
        self.assertEqual(len(service.platforms), 3)
        for platform_id in service.platforms:
            service.connect(platform_id)
        service.tick(0.1)
        self.assertTrue(all(state.connected for state in service.platforms.values()))

    def test_offline_platform_does_not_accept_motion_or_mission_start(self) -> None:
        with self.assertRaises(ValueError):
            self.service.set_velocity(self.platform_id, 0.5, 0)
        with self.assertRaises(ValueError):
            self.service.start_mission(self.platform_id)

    def test_disconnect_clears_motion_and_reconnect_does_not_resume_it(self) -> None:
        self.service.connect(self.platform_id)
        self.service.set_velocity(self.platform_id, 0.5, 0)
        self.service.tick(0.1)
        self.service.disconnect(self.platform_id)
        state = self.service.platforms[self.platform_id]
        position = (state.pose.x, state.pose.y, state.pose.heading)
        self.assertEqual(state.speed, 0)
        self.assertEqual((state.desired_forward, state.desired_turn), (0, 0))
        self.service.tick(0.1)
        self.assertEqual((state.pose.x, state.pose.y, state.pose.heading), position)
        self.service.connect(self.platform_id)
        self.service.tick(0.1)
        self.assertEqual((state.pose.x, state.pose.y, state.pose.heading), position)
        self.assertEqual(state.speed, 0)

    def test_expired_manual_command_stops_without_new_input(self) -> None:
        self.service.connect(self.platform_id)
        self.service.set_velocity(self.platform_id, 0.5, 0)
        self.service.tick(1.0)
        state = self.service.platforms[self.platform_id]
        position = (state.pose.x, state.pose.y, state.pose.heading)
        self.assertEqual(state.speed, 0)
        self.service.tick(1.0)
        self.assertEqual((state.pose.x, state.pose.y, state.pose.heading), position)

    def test_motion_of_one_platform_does_not_move_another(self) -> None:
        first_id, second_id = list(self.service.platforms)[:2]
        self.service.connect(first_id)
        self.service.connect(second_id)
        first = self.service.platforms[first_id]
        second = self.service.platforms[second_id]
        first_position = (first.pose.x, first.pose.y)
        second_position = (second.pose.x, second.pose.y)
        self.service.set_velocity(first_id, 0.5, 0)
        self.service.tick(0.1)
        self.assertNotEqual((first.pose.x, first.pose.y), first_position)
        self.assertEqual((second.pose.x, second.pose.y), second_position)

    def test_pause_holds_position_and_resume_completes_route(self) -> None:
        service = self.load_config(example_config())
        platform_id = "custom-01"
        service.connect(platform_id)
        service.set_route(platform_id, [Point(24, 20)])
        service.start_mission(platform_id)
        service.tick(0.1)
        service.pause_mission(platform_id)
        state = service.platforms[platform_id]
        self.assertEqual(state.mission_status, MISSION_PAUSED)
        position = (state.pose.x, state.pose.y)
        for _ in range(5):
            service.tick(0.1)
        self.assertEqual((state.pose.x, state.pose.y), position)
        service.resume_mission(platform_id)
        for _ in range(300):
            service.tick(0.1)
            if state.mission_status == MISSION_COMPLETED:
                break
        self.assertEqual(state.mission_status, MISSION_COMPLETED)
        self.assertEqual(state.speed, 0)
        self.assertAlmostEqual(state.pose.x, 24, delta=0.6)
        self.assertAlmostEqual(state.pose.y, 20, delta=0.6)

    def test_mission_does_not_restart_after_disconnect(self) -> None:
        self.service.connect(self.platform_id)
        state = self.service.platforms[self.platform_id]
        target_x = 90 if state.pose.x < 50 else 10
        self.service.set_route(self.platform_id, [Point(target_x, state.pose.y)])
        self.service.start_mission(self.platform_id)
        self.service.tick(0.1)
        self.service.disconnect(self.platform_id)
        self.service.connect(self.platform_id)
        position = (state.pose.x, state.pose.y)
        self.service.tick(0.1)
        self.assertNotEqual(state.mission_status, MISSION_RUNNING)
        self.assertEqual((state.pose.x, state.pose.y), position)

    def test_cancel_and_stop_prevent_further_movement(self) -> None:
        self.service.connect(self.platform_id)
        state = self.service.platforms[self.platform_id]
        self.service.set_route(self.platform_id, [Point(50, 35)])
        self.service.start_mission(self.platform_id)
        self.service.cancel_mission(self.platform_id)
        position = (state.pose.x, state.pose.y)
        self.service.tick(0.1)
        self.assertEqual((state.pose.x, state.pose.y), position)
        self.service.set_velocity(self.platform_id, 0.5, 0.2)
        self.service.stop(self.platform_id)
        self.service.tick(0.1)
        self.assertEqual((state.pose.x, state.pose.y), position)
        self.assertEqual(state.speed, 0)

    def test_invalid_route_is_rejected_without_replacing_existing_route(self) -> None:
        valid = [Point(10, 10), Point(20, 20)]
        self.service.set_route(self.platform_id, valid)
        for point in (Point(float("nan"), 1), Point(1, float("inf")), Point(-1, 1), Point(1, 71)):
            with self.subTest(point=point):
                with self.assertRaises(ValueError):
                    self.service.set_route(self.platform_id, [point])
                self.assertEqual(self.service.platforms[self.platform_id].route, valid)

    def test_invalid_manual_input_is_rejected(self) -> None:
        self.service.connect(self.platform_id)
        for forward, turn in ((float("nan"), 0), (0, float("inf")), (1.1, 0), (0, -1.1)):
            with self.subTest(forward=forward, turn=turn):
                with self.assertRaises(ValueError):
                    self.service.set_velocity(self.platform_id, forward, turn)

    def test_invalid_configuration_is_rejected(self) -> None:
        duplicate_id = example_config()
        duplicate_id["platforms"].append(dict(duplicate_id["platforms"][0]))
        nonfinite_pose = example_config()
        nonfinite_pose["platforms"][0]["initial_pose"]["x"] = float("inf")
        bad_period = example_config()
        bad_period["platforms"][0]["telemetry_fields"][0]["demo"] = {"kind": "wave", "period_s": 0}
        duplicate_field = example_config()
        duplicate_field["platforms"][0]["telemetry_fields"].append(dict(duplicate_field["platforms"][0]["telemetry_fields"][0]))
        unknown_version = example_config()
        unknown_version["schema_version"] = 99
        for config in (duplicate_id, nonfinite_pose, bad_period, duplicate_field, unknown_version):
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    self.load_config(config)


if __name__ == "__main__":
    unittest.main()
