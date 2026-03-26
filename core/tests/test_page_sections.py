from django.test import SimpleTestCase

from core.services.page_sections import _normalize_layout_overrides


class NormalizePageSectionLayoutOverridesTests(SimpleTestCase):
    def test_wraps_flat_payload_into_desktop_mode_and_defaults_mobile(self):
        self.assertEqual(
            _normalize_layout_overrides({"x": "4.6", "y": "-2.4", "w": "6.2"}),
            {
                "desktop": {"x": 5, "y": -2, "w": 6},
                "mobile": {"x": 0, "y": 0, "w": None},
            },
        )

    def test_normalizes_nested_modes_and_drops_invalid_widths(self):
        self.assertEqual(
            _normalize_layout_overrides(
                {
                    "desktop": {"x": "1.6", "y": "2.2", "w": "0"},
                    "mobile": {"x": "3", "y": "4.9", "w": "bad"},
                }
            ),
            {
                "desktop": {"x": 2, "y": 2, "w": None},
                "mobile": {"x": 3, "y": 5, "w": None},
            },
        )

    def test_invalid_payload_uses_empty_defaults(self):
        self.assertEqual(
            _normalize_layout_overrides("not-a-dict"),
            {
                "desktop": {"x": 0, "y": 0, "w": None},
                "mobile": {"x": 0, "y": 0, "w": None},
            },
        )
