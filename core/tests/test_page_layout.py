from django.test import SimpleTestCase

from core.models import HomePageCopy
from core.services.page_layout import build_layout_styles, normalize_layout_overrides


class NormalizeLayoutOverridesTests(SimpleTestCase):
    def test_wraps_flat_payload_into_desktop_mode(self):
        self.assertEqual(
            normalize_layout_overrides({"hero_title": {"x": 12, "y": -8}}),
            {
                "desktop": {"hero_title": {"x": 12, "y": -8}},
                "mobile": {},
            },
        )

    def test_parses_nested_json_string(self):
        self.assertEqual(
            normalize_layout_overrides(
                '{"desktop":{"hero_title":{"x":4}},"mobile":{"hero_title":{"y":2}}}'
            ),
            {
                "desktop": {"hero_title": {"x": 4}},
                "mobile": {"hero_title": {"y": 2}},
            },
        )


class BuildLayoutStylesTests(SimpleTestCase):
    def test_builds_desktop_and_mobile_css_for_known_homepage_sections(self):
        css = build_layout_styles(
            HomePageCopy,
            {
                "desktop": {
                    "hero_title": {"x": "3.6", "y": "-1.6"},
                    "hero_cta": {"x": 0, "y": 0},
                },
                "mobile": {
                    "hero_title": {"x": 0, "y": 5},
                },
            },
        )

        self.assertEqual(
            css,
            ".hero__title{transform:translate3d(4px,-2px,0);}\n"
            "@media (max-width: 768px){.hero__title{transform:translate3d(0px,5px,0);}}",
        )
