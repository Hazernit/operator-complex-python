"""Регрессии числовых крайних случаев конфигурируемой тестовой телеметрии."""

import json
import math
import unittest

from operator_stub.adapters.mock import MockAdapter
from operator_stub.service import OperatorService


def wave_config(value=1.0, amplitude=0.5, period=20.0):
    return {
        "id": "numeric-test", "name": "Числовая заглушка", "kind": "НРТК",
        "telemetry_fields": [{
            "key": "sample", "label": "Тестовое поле", "value": value,
            "demo": {"kind": "wave", "amplitude": amplitude, "period_s": period},
        }],
    }


class MockExtremeTests(unittest.TestCase):
    def test_tiny_period_does_not_overflow_phase(self):
        for period in (1e-320, 5e-324):
            with self.subTest(period=period):
                service = OperatorService(adapters=[MockAdapter(wave_config(period=period))])
                service.connect("numeric-test")
                for _ in range(3):
                    service.tick(0.1)
                    value = service.platforms["numeric-test"].fields["sample"].value
                    self.assertTrue(math.isfinite(value))
                    self.assertGreaterEqual(value, 0.5)
                    self.assertLessEqual(value, 1.5)
                json.dumps(service.export_snapshot(), allow_nan=False)

    def test_unrepresentable_wave_range_is_rejected(self):
        for value in (1e308, -1e308):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "диапазон.*слишком велик"):
                    MockAdapter(wave_config(value=value, amplitude=1e308))

    def test_oversized_integer_has_a_readable_validation_error(self):
        with self.assertRaisesRegex(ValueError, "число слишком велико"):
            MockAdapter(wave_config(value=10 ** 1000))

    def test_large_finite_wave_values_remain_json_serializable(self):
        service = OperatorService(adapters=[MockAdapter(wave_config(value=0, amplitude=1e308))])
        service.connect("numeric-test")
        for _ in range(5):
            service.tick(1.0)
            self.assertTrue(math.isfinite(service.platforms["numeric-test"].fields["sample"].value))
            json.dumps(service.export_snapshot(), allow_nan=False)


if __name__ == "__main__":
    unittest.main()
