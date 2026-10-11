from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TOOLS = REPOSITORY_ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import build_site  # noqa: E402
import publish_product  # noqa: E402


class BuildSiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        shutil.copytree(REPOSITORY_ROOT / "templates", self.root / "templates")
        self.original_root = build_site.ROOT
        build_site.ROOT = self.root

    def tearDown(self) -> None:
        build_site.ROOT = self.original_root
        self.temporary_directory.cleanup()

    def test_new_snapshot_only_event_builds_clean_pages(self) -> None:
        event_slug = "example-event-2026"
        product_slug = "snapshot-20260802"
        event_dir = self.root / "events" / event_slug
        product_dir = event_dir / "products" / product_slug
        product_dir.mkdir(parents=True)

        event = {
            "schema_version": "1.0",
            "slug": event_slug,
            "title": "Example Event",
            "event_type": "Earthquake",
            "event_date": "2026-08-02",
            "products": [
                {
                    "slug": product_slug,
                    "title": "Snapshot briefing",
                    "product_type": "snapshot_briefing",
                    "generated_at": "2026-08-02T08:00:00+01:00",
                    "counts": {"sources": 3},
                    "manifest_path": f"products/{product_slug}/manifest.json",
                }
            ],
            "latest_product_slug": product_slug,
        }
        (event_dir / "event.json").write_text(
            json.dumps(event), encoding="utf-8"
        )
        (product_dir / "content.html").write_text(
            '<section id="summary"><h2>Summary</h2></section>\n',
            encoding="utf-8",
        )
        (product_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "product_type": "snapshot_briefing",
                    "generated_at": "2026-08-02T08:00:00+01:00",
                    "counts": {"sources": 3},
                    "sections": [{"id": "summary", "title": "Summary"}],
                }
            ),
            encoding="utf-8",
        )

        build_site.build_site()

        event_page = (event_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("Time<span>unavailable</span>", event_page)
        self.assertIn("Generated Aug 2, 2026 07:00 UTC", event_page)
        for page in self.root.rglob("index.html"):
            html = page.read_text(encoding="utf-8")
            self.assertNotRegex(html, r"{{\s*[a-z][a-z0-9_]*\s*}}")
            for line_number, line in enumerate(html.splitlines(), start=1):
                self.assertEqual(
                    line,
                    line.rstrip(),
                    f"trailing whitespace in {page}:{line_number}",
                )

    def test_template_rejects_missing_values(self) -> None:
        template = self.root / "templates" / "incomplete.html"
        template.write_text("{{ known }} {{ missing }}\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "missing"):
            build_site._template("incomplete.html", {"known": "value"})

    def test_aware_datetimes_are_displayed_in_utc(self) -> None:
        value = "2026-08-01T23:30:00-07:00"
        self.assertEqual(
            build_site._format_timeline_date(value),
            "Aug<span>2, 2026</span>",
        )
        self.assertEqual(
            build_site._format_generated(value),
            "Aug 2, 2026 06:30 UTC",
        )
        self.assertEqual(
            build_site._sort_datetime(value),
            "2026-08-02T06:30:00+00:00",
        )


class PublishProductTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "site"
        (self.root / "events").mkdir(parents=True)
        self.original_root = publish_product.ROOT
        publish_product.ROOT = self.root
        self.original_build_root = build_site.ROOT
        build_site.ROOT = self.root
        shutil.copytree(REPOSITORY_ROOT / "templates", self.root / "templates")

    def tearDown(self) -> None:
        publish_product.ROOT = self.original_root
        build_site.ROOT = self.original_build_root
        self.temporary_directory.cleanup()

    def make_bundle(self, name="bundle", **metadata) -> Path:
        bundle = Path(self.temporary_directory.name) / name
        bundle.mkdir()
        (bundle / "content.html").write_text("<p>Evidence-grounded report.</p>\n", encoding="utf-8")
        manifest = {
            "product_type": "snapshot_briefing",
            "event_date": "2026-10-09",
            "generated_at": "2026-10-11T18:00:00Z",
            "snapshot": {"snapshot_time": "2026-10-11T17:00:00Z"},
            "counts": {"sources": 3},
            **metadata,
        }
        (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (bundle / "assets").mkdir()
        (bundle / "assets" / "figure.svg").write_text("<svg></svg>", encoding="utf-8")
        return bundle

    def publish_bundle(self, bundle: Path, slug: str, *options: str) -> Path:
        args = publish_product._parse_args([
            "--bundle", str(bundle), "--event-slug", "example-event",
            "--product-slug", slug, *options,
        ])
        return publish_product.publish(args)

    def site_files(self) -> dict[str, bytes]:
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

    def test_review_is_explicit_and_not_inferred_from_bundle(self) -> None:
        bundle = self.make_bundle(expert_review={"reviewers": ["Invented reviewer"]})
        product = self.publish_bundle(bundle, "initial", "--build")
        event = json.loads((product.parent.parent / "event.json").read_text())
        self.assertNotIn("expert_review", event["products"][0])
        self.assertNotIn("Expert reviewed", (product / "index.html").read_text())
        self.assertNotIn("review.js", (product / "index.html").read_text())
        self.assertNotIn("Invented reviewer", (product / "index.html").read_text())

        reviewed = self.publish_bundle(bundle, "reviewed-first-release", "--expert-reviewer", "Selim", "--build")
        html = (reviewed / "index.html").read_text()
        self.assertIn('data-expert-review><summary', html)
        self.assertIn("Expert reviewed</summary>", html)
        self.assertIn("<li>Selim</li>", html)
        self.assertIn("review.js", html)
        self.assertNotIn("Revised following", html)

    def test_revision_preserves_bundles_and_redirects_old_pages(self) -> None:
        bundle = self.make_bundle()
        original = self.publish_bundle(bundle, "original", "--build")
        unrelated = self.publish_bundle(bundle, "other-snapshot", "--build")
        unrelated_page = (unrelated / "index.html").read_bytes()
        original_bundle = {str(path.relative_to(original)): path.read_bytes() for path in original.rglob("*") if path.is_file() and path.name != "index.html"}
        revised = self.publish_bundle(
            bundle, "refined-v1", "--supersedes", "original",
            "--product-title", "Snapshot briefing · Oct 11, 2026 17:00 UTC · Revised",
            "--expert-reviewer", "Selim <Expert>", "--expert-reviewer", "A & B",
            "--expert-reviewer-url", "Selim <Expert>=https://example.org/profile?a=1&b=2",
            "--review-note", '<script>alert("review")</script>', "--build",
        )
        event = json.loads((revised.parent.parent / "event.json").read_text())
        self.assertEqual(len(event["products"]), 3)
        self.assertEqual(event["latest_product_slug"], "refined-v1")
        revision_entry = next(item for item in event["products"] if item["slug"] == "refined-v1")
        self.assertEqual(revision_entry["expert_review"]["reviewers"], ["Selim <Expert>", "A & B"])
        revised_html = (revised / "index.html").read_text()
        self.assertIn("Selim &lt;Expert&gt;</a>", revised_html)
        self.assertIn("<li>A &amp; B</li>", revised_html)
        self.assertIn('href="https://example.org/profile?a=1&amp;b=2"', revised_html)
        self.assertNotIn('role="tooltip"', revised_html)
        self.assertNotIn("· Revised", revised_html)
        self.assertNotIn('<script>alert("review")</script>', revised_html)
        self.assertNotIn('href="../original/"', revised_html)
        original_html = (original / "index.html").read_text()
        self.assertIn('rel="canonical" href="../refined-v1/"', original_html)
        self.assertIn('http-equiv="refresh" content="0; url=../refined-v1/"', original_html)
        self.assertIn('href="../refined-v1/">Open briefing', original_html)
        event_html = (revised.parent.parent / "index.html").read_text()
        self.assertEqual(event_html.count('class="timeline-item product-timeline-item'), 2)
        self.assertNotIn('href="products/original/"', event_html)
        self.assertNotIn("Previous version", event_html)
        self.assertNotIn("Revised", event_html)
        self.assertIn("2 snapshots", (self.root / "index.html").read_text())
        self.assertIn("site.css?v=20261011-review2", revised_html)
        self.assertIn("site.css?v=20261011-review2", event_html)
        self.assertEqual(unrelated_page, (unrelated / "index.html").read_bytes())
        self.assertEqual(original_bundle, {str(path.relative_to(original)): path.read_bytes() for path in original.rglob("*") if path.is_file() and path.name != "index.html"})
        self.assertNotIn("expert_review", json.loads((revised / "manifest.json").read_text()))

        # Repeated imports cannot silently change editorial metadata or bundles.
        before = self.site_files()
        with self.assertRaises((ValueError, FileExistsError)):
            self.publish_bundle(bundle, "refined-v1", "--supersedes", "original", "--expert-reviewer", "Someone else")
        self.assertEqual(before, self.site_files())

        self.publish_bundle(bundle, "refined-v2", "--supersedes", "refined-v1", "--expert-reviewer", "Selim", "--build")
        self.assertIn('href="../refined-v2/"', (original / "index.html").read_text())
        self.assertIn('href="../refined-v2/"', (revised / "index.html").read_text())

    def test_invalid_review_metadata_creates_no_publication_files(self) -> None:
        bundle = self.make_bundle()
        self.publish_bundle(bundle, "original")
        before = self.site_files()
        cases = [
            ("--expert-reviewer", "  "),
            ("--review-note", "No reviewer"),
            ("--expert-reviewer", "Selim", "--review-note", " "),
            ("--expert-reviewer", "Selim", "--expert-reviewer-url", "Selim=javascript:alert(1)"),
            ("--expert-reviewer", "Selim", "--expert-reviewer-url", "Other=https://example.org"),
            ("--expert-reviewer", "Selim", "--expert-reviewer-url", "Selim=//example.org"),
            ("--expert-reviewer", "Selim", "--expert-reviewer-url", "Selim=https://exam ple.org"),
            ("--expert-reviewer", "Selim", "--expert-reviewer-url", "Selim=https://[invalid"),
            ("--supersedes", "missing-in-this-event"),
            ("--supersedes", "revision"),
            ("--supersedes", "../another-event/original"),
        ]
        for options in cases:
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    self.publish_bundle(bundle, "revision", *options)
                self.assertEqual(before, self.site_files())
        for name, metadata in [
            ("later", {"snapshot": {"snapshot_time": "2026-10-12T17:00:00Z"}}),
            ("different-type", {"product_type": "temporal_recon"}),
        ]:
            with self.subTest(name=name):
                mismatched = self.make_bundle(name, **metadata)
                with self.assertRaises(ValueError):
                    self.publish_bundle(mismatched, "revision", "--supersedes", "original")
                self.assertEqual(before, self.site_files())

    def test_update_review_changes_only_editorial_metadata(self) -> None:
        bundle = self.make_bundle()
        product_dir = self.publish_bundle(bundle, "initial", "--build")
        before = self.site_files()
        event_path = product_dir.parent.parent / "event.json"
        original_event = json.loads(event_path.read_text())
        args = publish_product._parse_args([
            "--update-review", "--event-slug", "example-event", "--product-slug", "initial",
            "--expert-reviewer", "Mehmet Selim Gunay", "--expert-reviewer", "Khalid M. Mosalam",
            "--expert-reviewer-url", "Mehmet Selim Gunay=https://scholar.google.com/citations?user=wlpfjKUAAAAJ&hl=en",
        ])
        publish_product.publish(args)
        changed = [name for name, data in before.items() if self.site_files()[name] != data]
        self.assertEqual(changed, ["events/example-event/event.json"])
        updated_event = json.loads(event_path.read_text())
        review = updated_event["products"][0].pop("expert_review")
        self.assertEqual(review["reviewers"], ["Mehmet Selim Gunay", "Khalid M. Mosalam"])
        self.assertEqual(set(review["reviewer_links"]), {"Mehmet Selim Gunay"})
        self.assertEqual(updated_event, original_event)
        before_invalid = self.site_files()
        args.expert_reviewer_url = ["Mehmet Selim Gunay=data:text/html,unsafe"]
        with self.assertRaises(ValueError):
            publish_product.publish(args)
        self.assertEqual(before_invalid, self.site_files())

    def test_update_review_rejects_unrelated_changes(self) -> None:
        bundle = self.make_bundle()
        self.publish_bundle(bundle, "initial")
        before = self.site_files()
        for options in [
            ["--bundle", str(bundle)], ["--supersedes", "initial"],
            ["--product-title", "Changed"], ["--event-type", "Earthquake"],
            ["--set-latest"], ["--event-date", "2026-01-01"],
        ]:
            with self.subTest(options=options):
                args = publish_product._parse_args([
                    "--update-review", "--event-slug", "example-event", "--product-slug", "initial",
                    "--expert-reviewer", "Selim", *options,
                ])
                with self.assertRaises(ValueError):
                    publish_product.publish(args)
                self.assertEqual(before, self.site_files())

    def test_bad_hand_edited_profile_url_is_not_rendered_as_link(self) -> None:
        html = build_site._render_expert_review({
            "slug": "snapshot", "expert_review": {
                "reviewers": ["Selim <Expert>"],
                "reviewer_links": {"Selim <Expert>": "javascript:alert(1)"},
            },
        })
        self.assertIn("<li>Selim &lt;Expert&gt;</li>", html)
        self.assertIn("<details", html)
        self.assertNotIn("href=", html)

    def test_product_destination_rejects_unsafe_slugs(self) -> None:
        for slug in ("../outside", "/tmp/outside", "Uppercase", "two--hyphens"):
            with self.subTest(slug=slug):
                with self.assertRaises(ValueError):
                    publish_product._product_destination(slug, "snapshot-20260802")
                with self.assertRaises(ValueError):
                    publish_product._product_destination("safe-event", slug)

    def test_product_destination_rejects_symlink_escape(self) -> None:
        outside = Path(self.temporary_directory.name) / "outside"
        outside.mkdir()
        (self.root / "events" / "escaped-event").symlink_to(
            outside, target_is_directory=True
        )

        with self.assertRaisesRegex(ValueError, "escapes"):
            publish_product._product_destination(
                "escaped-event", "snapshot-20260802"
            )

    def test_copy_bundle_never_replaces_existing_product(self) -> None:
        bundle = Path(self.temporary_directory.name) / "bundle"
        bundle.mkdir()
        (bundle / "content.html").write_text("new\n", encoding="utf-8")
        (bundle / "manifest.json").write_text("{}\n", encoding="utf-8")
        destination = self.root / "events" / "event" / "products" / "snapshot"
        destination.mkdir(parents=True)
        sentinel = destination / "content.html"
        sentinel.write_text("original\n", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            publish_product._copy_bundle(bundle, destination)

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "original\n")


if __name__ == "__main__":
    unittest.main()
