"""Смысл общих показателей и предупреждений, независимо от GUI и транспорта."""

from __future__ import annotations

import unittest

from operator_stub.adapters.mock import MockAdapter
from operator_stub.models import MISSION_PAUSED, PlatformInfo, Point, State, TelemetryField
from operator_stub.presentation import metric_value, profile_for, warnings_for
from operator_stub.service import OperatorService


def state_with_metrics(battery=80, link=90, *, connected=True) -> State:
    return State(
        PlatformInfo("test-1", "Тест", "НРТК"),
        connected=connected,
        telemetry_age_s=0,
        fields={
            "power": TelemetryField("power", "Любое название заряда", "%", battery, semantic="battery_percent"),
            "radio": TelemetryField("radio", "Любое название связи", "%", link, semantic="link_quality_percent"),
        },
    )


def warning_levels(state: State) -> dict[str, str]:
    return {warning.code: warning.level for warning in warnings_for(state)}


class PresentationTests(unittest.TestCase):
    def test_metric_uses_semantic_instead_of_sensor_name(self) -> None:
        state = state_with_metrics(77, 88)
        self.assertEqual(metric_value(state, "battery_percent"), 77)
        self.assertEqual(metric_value(state, "link_quality_percent"), 88)
        state.fields["looks_like_battery"] = TelemetryField("looks_like_battery", "Заряд батареи", "%", 1)
        del state.fields["power"]
        self.assertIsNone(metric_value(state, "battery_percent"))

    def test_missing_and_invalid_metric_values_stay_unknown(self) -> None:
        for value in (None, True, False, "20", "", float("nan"), float("inf"), -1, 101, 10**1000):
            with self.subTest(value_type=type(value).__name__, value=repr(value)[:40]):
                state = state_with_metrics(value, value)
                self.assertIsNone(metric_value(state, "battery_percent"))
                self.assertIsNone(metric_value(state, "link_quality_percent"))
                self.assertEqual(warning_levels(state), {"battery_unknown": "WARNING", "link_unknown": "WARNING"})
        empty = state_with_metrics()
        empty.fields.clear()
        self.assertEqual(warning_levels(empty), {"battery_unknown": "WARNING", "link_unknown": "WARNING"})

    def test_zero_percent_is_known_and_critical(self) -> None:
        state = state_with_metrics(0, 0)
        self.assertEqual(metric_value(state, "battery_percent"), 0)
        self.assertEqual(metric_value(state, "link_quality_percent"), 0)
        self.assertEqual(warning_levels(state), {"battery_low": "CRITICAL", "link_weak": "CRITICAL"})

    def test_duplicate_semantic_is_ambiguous_not_arbitrarily_selected(self) -> None:
        state = state_with_metrics()
        state.fields["another_power"] = TelemetryField("another_power", "Вторая батарея", "%", 15, semantic="battery_percent")
        self.assertIsNone(metric_value(state, "battery_percent"))
        self.assertEqual(warning_levels(state), {"battery_unknown": "WARNING"})

    def test_battery_thresholds_include_boundaries(self) -> None:
        for value, expected in ((20.01, {}), (20, {"battery_low": "WARNING"}), (10.01, {"battery_low": "WARNING"}), (10, {"battery_low": "CRITICAL"}), (100, {})):
            with self.subTest(battery=value):
                self.assertEqual(warning_levels(state_with_metrics(value)), expected)

    def test_link_thresholds_include_boundaries(self) -> None:
        for value, expected in ((30.01, {}), (30, {"link_weak": "WARNING"}), (10.01, {"link_weak": "WARNING"}), (10, {"link_weak": "CRITICAL"}), (100, {})):
            with self.subTest(link=value):
                self.assertEqual(warning_levels(state_with_metrics(link=value)), expected)

    def test_stale_warning_only_after_two_seconds_for_connected_source(self) -> None:
        state = state_with_metrics()
        for age in (None, 0, 2, True, "3", float("nan"), float("inf")):
            with self.subTest(age=age):
                state.telemetry_age_s = age
                self.assertNotIn("telemetry_stale", warning_levels(state))
        state.telemetry_age_s = 2.01
        self.assertEqual(warning_levels(state), {"telemetry_stale": "WARNING"})
        state.connected = False
        self.assertEqual(warning_levels(state), {"offline": "WARNING"})

    def test_offline_warning_does_not_present_old_metrics_as_active_faults(self) -> None:
        state = state_with_metrics(0, None, connected=False)
        state.telemetry_age_s = 100
        self.assertEqual(warning_levels(state), {"offline": "WARNING"})
        state.connected = True
        self.assertEqual(warning_levels(state), {"battery_low": "CRITICAL", "link_unknown": "WARNING", "telemetry_stale": "WARNING"})

    def test_paused_mission_is_visible_even_when_disconnected(self) -> None:
        state = state_with_metrics(connected=False)
        state.mission_status = MISSION_PAUSED
        self.assertEqual(warning_levels(state), {"offline": "WARNING", "mission_paused": "INFO"})

    def test_profiles_have_distinct_environments_and_explicit_limitations(self) -> None:
        profiles = [profile_for(kind) for kind in ("БПЛА", "НРТК", "БЭК")]
        self.assertEqual([profile.title for profile in profiles], ["БПЛА", "НРТК", "БЭК"])
        self.assertEqual(len({profile.environment for profile in profiles}), 3)
        for profile in profiles:
            self.assertTrue(profile.manual_hint)
            self.assertTrue(profile.limitation)
        fallback = profile_for("Будущий аппарат")
        self.assertEqual(fallback.title, "Платформа")
        self.assertIn("не определ", fallback.environment)

    def test_semantics_survive_adapter_connection_and_snapshot_export(self) -> None:
        service = OperatorService()
        for platform_id, state in service.platforms.items():
            service.connect(platform_id)
            with self.subTest(platform=platform_id):
                self.assertIsNotNone(metric_value(state, "battery_percent"))
                self.assertIsNotNone(metric_value(state, "link_quality_percent"))
                self.assertNotIn("battery_unknown", warning_levels(state))
                self.assertNotIn("link_unknown", warning_levels(state))
        service.tick(0.1)
        snapshot = service.export_snapshot()
        for platform in snapshot["platforms"]:
            self.assertTrue(platform["connected"])
            self.assertTrue(platform["description"])
            self.assertEqual(set(platform["capabilities"]), {"manual", "mission"})
            self.assertIn("battery_percent", {field["semantic"] for field in platform["fields"].values()})
            self.assertIn("link_quality_percent", {field["semantic"] for field in platform["fields"].values()})

    def test_core_semantics_validate_configuration(self) -> None:
        base = {
            "id": "custom", "name": "Тест", "kind": "НРТК",
            "telemetry_fields": [{"key": "power", "label": "Любое поле", "semantic": "battery_percent", "value": None}],
        }
        self.assertIsNone(MockAdapter(base).field_specs["power"].value)
        for invalid in (True, "5", -1, 101):
            with self.subTest(value=invalid):
                base["telemetry_fields"][0]["value"] = invalid
                with self.assertRaises(ValueError):
                    MockAdapter(base)

    def test_duplicate_core_semantics_and_out_of_range_wave_are_rejected(self) -> None:
        fields = [
            {"key": "power-a", "label": "Заряд", "semantic": "battery_percent", "value": 60},
            {"key": "power-b", "label": "Другой заряд", "semantic": "battery_percent", "value": 50},
        ]
        config = {"id": "custom", "name": "Тест", "kind": "НРТК", "telemetry_fields": fields}
        with self.assertRaises(ValueError):
            MockAdapter(config)
        fields.pop()
        fields[0]["demo"] = {"kind": "wave", "amplitude": 50, "period_s": 10}
        with self.assertRaises(ValueError):
            MockAdapter(config)

    def test_capabilities_restrict_commands_for_each_platform(self) -> None:
        for capabilities in ([], ["manual"], ["mission"]):
            with self.subTest(capabilities=capabilities):
                adapter = MockAdapter({
                    "id": "custom", "name": "Тест", "kind": "Будущий аппарат",
                    "description": "Свой набор возможностей", "capabilities": capabilities,
                })
                service = OperatorService(adapters=[adapter])
                service.connect("custom")
                service.set_route("custom", [Point(20, 20)])
                if "manual" in capabilities:
                    service.set_velocity("custom", 0.5, 0)
                    service.stop("custom")
                else:
                    with self.assertRaises(ValueError):
                        service.set_velocity("custom", 0.5, 0)
                if "mission" in capabilities:
                    service.start_mission("custom")
                    service.pause_mission("custom")
                    service.resume_mission("custom")
                else:
                    with self.assertRaises(ValueError):
                        service.start_mission("custom")
                service.stop("custom")
                service.cancel_mission("custom")


if __name__ == "__main__":
    unittest.main()
