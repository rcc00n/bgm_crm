import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from core.admin import HomePageCopyAdminForm
from core.models import HeroImage, HomePageCopy, ProjectJournalEntry


def make_test_image(name: str, color: tuple[int, int, int]) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), color=color).save(buffer, format="PNG")
    buffer.seek(0)
    return SimpleUploadedFile(name, buffer.read(), content_type="image/png")


class HomePageGalleryItemsTests(TestCase):
    def setUp(self):
        self.home_copy = HomePageCopy.get_solo()

    def _published_entry(self, title: str) -> ProjectJournalEntry:
        return ProjectJournalEntry.objects.create(
            title=title,
            excerpt=f"{title} excerpt",
            body="",
            cover_image=make_test_image(f"{title.lower().replace(' ', '-')}.png", (10, 40, 90)),
            before_gallery=[{"url": "https://example.com/before.jpg", "alt": "Before"}],
            after_gallery=[{"url": "https://example.com/after.jpg", "alt": "After"}],
            status=ProjectJournalEntry.Status.PUBLISHED,
            result_highlight=f"{title} result",
        )

    def test_home_page_prefers_custom_gallery_slot_over_project_journal_cover(self):
        self._published_entry("Journal Build")
        HeroImage.objects.create(
            location=HeroImage.Location.HOME_GALLERY_A,
            image=make_test_image("home-gallery-a.png", (180, 30, 30)),
            title="Homepage Custom Card",
            alt_text="Homepage custom alt",
            caption="Homepage custom caption",
            is_active=True,
        )

        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)

        gallery_items = response.context["home_gallery_items"]
        self.assertEqual(gallery_items[0]["title"], "Homepage Custom Card")
        self.assertEqual(gallery_items[0]["caption"], "Homepage custom caption")
        self.assertEqual(gallery_items[0]["alt"], "Homepage custom alt")
        self.assertEqual(gallery_items[1]["title"], "Journal Build")

    def test_home_page_falls_back_to_project_journal_when_custom_slot_is_empty(self):
        self._published_entry("Fallback Journal Build")

        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)

        gallery_items = response.context["home_gallery_items"]
        self.assertEqual(gallery_items[0]["title"], "Fallback Journal Build")
        self.assertEqual(gallery_items[0]["caption"], "Fallback Journal Build result")

    def test_home_page_uses_text_overrides_from_gallery_slot_without_custom_image(self):
        self._published_entry("Journal Build")
        HeroImage.objects.create(
            location=HeroImage.Location.HOME_GALLERY_A,
            title="Homepage Override Title",
            alt_text="Homepage override alt",
            caption="Homepage override caption",
            is_active=False,
        )

        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)

        gallery_items = response.context["home_gallery_items"]
        self.assertEqual(gallery_items[0]["title"], "Homepage Override Title")
        self.assertEqual(gallery_items[0]["caption"], "Homepage override caption")
        self.assertEqual(gallery_items[0]["alt"], "Homepage override alt")
        self.assertIsNone(gallery_items[0]["image"])
        self.assertTrue(gallery_items[0]["src"].endswith("/static/img/hero-home.jpg"))

    def test_home_page_copy_form_saves_gallery_assets(self):
        form = HomePageCopyAdminForm(instance=self.home_copy)
        form.cleaned_data = {
            "home_gallery_1_image": make_test_image("admin-gallery-card.png", (20, 120, 180)),
            "home_gallery_1_alt_text": "Admin managed alt",
            "home_gallery_1_title": "Admin managed card",
            "home_gallery_1_caption": "Admin managed caption",
            "home_gallery_2_image": None,
            "home_gallery_2_alt_text": "",
            "home_gallery_2_title": "",
            "home_gallery_2_caption": "",
            "home_gallery_3_image": None,
            "home_gallery_3_alt_text": "",
            "home_gallery_3_title": "",
            "home_gallery_3_caption": "",
            "home_gallery_4_image": None,
            "home_gallery_4_alt_text": "",
            "home_gallery_4_title": "",
            "home_gallery_4_caption": "",
        }

        form.save_gallery_assets()

        asset = HeroImage.objects.get(location=HeroImage.Location.HOME_GALLERY_A)
        self.assertEqual(asset.title, "Admin managed card")
        self.assertEqual(asset.alt_text, "Admin managed alt")
        self.assertEqual(asset.caption, "Admin managed caption")
        self.assertTrue(asset.is_active)
        self.assertTrue(bool(asset.image))
