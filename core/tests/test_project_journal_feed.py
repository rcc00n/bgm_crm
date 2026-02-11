from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import ProjectJournalCategory, ProjectJournalEntry


class ProjectJournalFeedTests(TestCase):
    def _entry(
        self,
        *,
        title: str,
        featured: bool = False,
        status: str = ProjectJournalEntry.Status.PUBLISHED,
        published_at=None,
        tags: str = "",
        categories=None,
        before: bool = True,
        after: bool = True,
    ) -> ProjectJournalEntry:
        entry = ProjectJournalEntry.objects.create(
            title=title,
            slug="",
            excerpt=f"Summary for {title}",
            body="",
            tags=tags,
            featured=featured,
            status=status,
            published_at=published_at,
            before_gallery=[{"url": "https://example.com/before.jpg", "alt": "Before"}] if before else [],
            after_gallery=[{"url": "https://example.com/after.jpg", "alt": "After"}] if after else [],
        )
        if categories:
            entry.categories.set(categories)
        return entry

    def test_feed_renders(self):
        self._entry(title="Build A")
        res = self.client.get(reverse("project-journal"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Build A")

    def test_search_filter(self):
        self._entry(title="Diesel Swap")
        self._entry(title="Suspension Refresh")
        res = self.client.get(reverse("project-journal"), {"q": "diesel"})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Diesel Swap")
        self.assertNotContains(res, "Suspension Refresh")

    def test_category_filter(self):
        fab = ProjectJournalCategory.objects.create(name="Fabrication", slug="fabrication")
        sus = ProjectJournalCategory.objects.create(name="Suspension", slug="suspension")
        self._entry(title="Fab Build", categories=[fab])
        self._entry(title="Sus Build", categories=[sus])

        res = self.client.get(reverse("project-journal"), {"cat": "fabrication"})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Fab Build")
        self.assertNotContains(res, "Sus Build")

    def test_sort_featured_default(self):
        now = timezone.now()
        featured = self._entry(title="Pinned", featured=True, published_at=now - timedelta(days=2))
        newest = self._entry(title="Newest", featured=False, published_at=now - timedelta(hours=1))

        # Default sort: featured-first.
        res = self.client.get(reverse("project-journal"))
        self.assertEqual(res.status_code, 200)
        html = res.content.decode("utf-8")
        # Use stable card anchors to avoid accidental matches in filter UI labels.
        self.assertLess(html.find(f'id="build-{featured.slug}"'), html.find(f'id="build-{newest.slug}"'))

    def test_sort_newest(self):
        now = timezone.now()
        older = self._entry(title="Older", published_at=now - timedelta(days=2))
        newer = self._entry(title="Newer", published_at=now - timedelta(hours=2))

        res = self.client.get(reverse("project-journal"), {"sort": "newest"})
        self.assertEqual(res.status_code, 200)
        html = res.content.decode("utf-8")
        self.assertLess(html.find(newer.title), html.find(older.title))

    def test_fragment_page(self):
        for i in range(9):
            self._entry(title=f"Build {i}")
        res = self.client.get(reverse("project-journal"), {"page": 2, "fragment": 1})
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, "<html")
        self.assertContains(res, 'data-feed-next')

    def test_detail_page_published(self):
        entry = self._entry(title="Detail Build")
        res = self.client.get(reverse("project-journal-post", kwargs={"slug": entry.slug}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Detail Build")

    def test_detail_page_draft_404(self):
        draft = self._entry(title="Draft Build", status=ProjectJournalEntry.Status.DRAFT)
        res = self.client.get(reverse("project-journal-post", kwargs={"slug": draft.slug}))
        self.assertEqual(res.status_code, 404)

    def test_is_publishable_requires_before_and_after(self):
        ok = self._entry(title="OK", before=True, after=True, status=ProjectJournalEntry.Status.DRAFT)
        missing = self._entry(title="Missing After", before=True, after=False, status=ProjectJournalEntry.Status.DRAFT)
        self.assertTrue(ok.is_publishable())
        self.assertFalse(missing.is_publishable())
