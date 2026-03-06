from decimal import Decimal

from django.test import SimpleTestCase

from core.utils_durations import _coerce_seconds, format_hms_ms, format_hms_seconds


class CoerceSecondsTests(SimpleTestCase):
    def test_none_returns_zero(self):
        self.assertEqual(_coerce_seconds(None), 0)

    def test_invalid_value_returns_zero(self):
        self.assertEqual(_coerce_seconds("not-a-number"), 0)

    def test_negative_value_returns_zero(self):
        self.assertEqual(_coerce_seconds(-5), 0)

    def test_rounds_to_nearest_second(self):
        self.assertEqual(_coerce_seconds(Decimal("1.6")), 2)


class FormatHmsSecondsTests(SimpleTestCase):
    def test_formats_zero_duration(self):
        self.assertEqual(format_hms_seconds(0), "00:00:00")

    def test_formats_hours_beyond_24(self):
        self.assertEqual(format_hms_seconds(90061), "25:01:01")


class FormatHmsMsTests(SimpleTestCase):
    def test_converts_milliseconds_to_hms(self):
        self.assertEqual(format_hms_ms(3723000), "01:02:03")

    def test_invalid_value_returns_zero_duration(self):
        self.assertEqual(format_hms_ms("oops"), "00:00:00")
