#!/usr/bin/env python3
"""Publish an APHR web bundle into this static website."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List

from build_site import build_site, reviewer_url

ROOT = Path(__file__).resolve().parents[1]
_SLUG_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", help="Directory with content.html and manifest.json; required unless --update-review is used.")
    parser.add_argument("--event-slug", required=True, help="Website event slug.")
    parser.add_argument("--product-slug", required=True, help="Website product slug.")
    parser.add_argument("--event-title", default=None, help="Display title for the event.")
    parser.add_argument("--event-date", default=None, help="Display/sort date for the event.")
    parser.add_argument("--event-type", default=None, help="Event type label (default: Earthquake).")
    parser.add_argument("--event-meta", default=None, help="Short metadata line for homepage card.")
    parser.add_argument("--event-description", default=None, help="Event page and homepage description.")
    parser.add_argument("--event-tag", default=None, help="Homepage tag for this event.")
    parser.add_argument("--product-title", default=None, help="Display title for this product.")
    parser.add_argument("--product-summary", default=None, help="Short product-card summary.")
    parser.add_argument("--expert-reviewer", action="append", default=[], help="Domain expert whose feedback was incorporated; repeat for multiple reviewers.")
    parser.add_argument("--expert-reviewer-url", action="append", default=[], metavar="NAME=URL", help="Optional HTTP(S) profile for a named reviewer; repeat for multiple reviewers.")
    parser.add_argument("--review-note", default=None, help="Optional plain-text note about the expert-informed revision.")
    parser.add_argument("--update-review", action="store_true", help="Replace expert-review metadata on an existing product without importing a bundle.")
    parser.add_argument("--supersedes", default=None, help="Existing product slug revised by this product, within the same event.")
    parser.add_argument("--set-latest", action="store_true", help="Make this the latest product.")
    parser.add_argument("--build", action="store_true", help="Rebuild static pages after publishing.")
    args = parser.parse_args(argv)
    if not args.update_review and not args.bundle:
        parser.error("--bundle is required unless --update-review is used")
    return args


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _validate_slug(value: str, label: str) -> str:
    if not _SLUG_PATTERN.fullmatch(value):
        raise ValueError(
            f"{label} must contain lowercase letters, digits, and single hyphens"
        )
    return value


def _resolve_descendant(root: Path, *parts: str) -> Path:
    resolved_root = root.resolve()
    candidate = resolved_root.joinpath(*parts).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"Publication path escapes {resolved_root}: {candidate}") from exc
    return candidate


def _product_destination(event_slug: str, product_slug: str) -> tuple[Path, Path]:
    event_slug = _validate_slug(event_slug, "event_slug")
    product_slug = _validate_slug(product_slug, "product_slug")
    events_root = _resolve_descendant(ROOT, "events")
    event_dir = _resolve_descendant(events_root, event_slug)
    product_dir = _resolve_descendant(event_dir, "products", product_slug)
    return event_dir, product_dir


def _copy_bundle(bundle_dir: Path, destination: Path) -> None:
    if not (bundle_dir / "content.html").exists():
        raise FileNotFoundError(f"Missing content.html in bundle: {bundle_dir}")
    if not (bundle_dir / "manifest.json").exists():
        raise FileNotFoundError(f"Missing manifest.json in bundle: {bundle_dir}")
    if destination.exists():
        raise FileExistsError(
            f"Product directory exists: {destination}. Publish corrections under a new slug."
        )

    destination.mkdir(parents=True)
    shutil.copy2(bundle_dir / "content.html", destination / "content.html")
    shutil.copy2(bundle_dir / "manifest.json", destination / "manifest.json")
    if (bundle_dir / "assets").exists():
        shutil.copytree(bundle_dir / "assets", destination / "assets")


def _format_product_type(value: str) -> str:
    labels = {
        "snapshot_briefing": "Snapshot briefing",
        "temporal_recon": "Temporal analysis",
    }
    return labels.get(value, value.replace("_", " ").title() if value else "Product")


def _is_temporal_product(manifest: Dict[str, Any]) -> bool:
    return str(manifest.get("product_type", "")).strip().lower().startswith("temporal")


def _is_snapshot_product(manifest: Dict[str, Any]) -> bool:
    return str(manifest.get("product_type", "")).strip().lower().startswith("snapshot")


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _format_month_day_year(value: datetime) -> str:
    return f"{value.strftime('%b')} {value.day}, {value.year}"


def _normalize_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    return value


def _format_datetime_label(value: Any) -> str:
    parsed = _parse_datetime(value)
    if not parsed:
        return str(value or "")
    parsed = _normalize_aware_datetime(parsed)
    if parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0:
        return _format_month_day_year(parsed)
    zone = " UTC" if parsed.tzinfo else ""
    return f"{_format_month_day_year(parsed)} {parsed.strftime('%H:%M')}{zone}"


def _sort_datetime(value: Any) -> str:
    parsed = _parse_datetime(value)
    if parsed:
        return _normalize_aware_datetime(parsed).isoformat()
    return str(value or "")


def _snapshot_time(manifest: Dict[str, Any]) -> str:
    return str((manifest.get("snapshot") or {}).get("snapshot_time") or "")


def _product_sort_key(product: Dict[str, Any]) -> str:
    return _sort_datetime(
        product.get("snapshot_time")
        or product.get("generated_at")
        or product.get("title")
        or product.get("slug")
    )


def _default_product_title(manifest: Dict[str, Any], product_slug: str) -> str:
    if _is_snapshot_product(manifest) and _snapshot_time(manifest):
        return f"Snapshot briefing · {_format_datetime_label(_snapshot_time(manifest))}"
    return str(manifest.get("title") or product_slug)


def _should_set_latest_snapshot(
    event: Dict[str, Any], product: Dict[str, Any], explicit: bool
) -> bool:
    if explicit:
        return True
    if not _is_snapshot_product(product):
        return False

    latest_slug = event.get("latest_product_slug")
    if not latest_slug:
        return True

    latest_product = next(
        (
            item
            for item in event.get("products", [])
            if item.get("slug") == latest_slug
        ),
        None,
    )
    if not latest_product or not _is_snapshot_product(latest_product):
        return True
    return _product_sort_key(product) >= _product_sort_key(latest_product)


def _default_event_meta(manifest: Dict[str, Any], event_date: str) -> str:
    counts = manifest.get("counts", {})
    bits: List[str] = []
    if event_date:
        bits.append(event_date)
    if counts.get("sources") is not None:
        bits.append(f"{counts['sources']} sources")
    if counts.get("facts_cited") is not None and counts.get("facts_total") is not None:
        bits.append(f"{counts['facts_cited']}/{counts['facts_total']} facts cited")
    return " · ".join(bits)


def _default_product_summary(manifest: Dict[str, Any]) -> str:
    counts = manifest.get("counts", {})
    if _is_temporal_product(manifest):
        summary_bits = []
        if counts.get("snapshots") is not None:
            count = counts["snapshots"]
            summary_bits.append(f"{count} snapshot" if count == 1 else f"{count} snapshots")
        if counts.get("tracks") is not None:
            summary_bits.append(f"{counts['tracks']} temporal tracks")
        if counts.get("source_references") is not None:
            summary_bits.append(f"{counts['source_references']} sources")
        if summary_bits:
            return "Aggregated APHR temporal analysis built from " + ", ".join(summary_bits) + "."
        return "Aggregated APHR temporal analysis built from multiple snapshot briefings."

    source_count = counts.get("sources")
    fact_count = counts.get("facts_cited")
    total_facts = counts.get("facts_total")
    if source_count is not None and fact_count is not None and total_facts is not None:
        return (
            "Website-ready APHR snapshot briefing with "
            f"{source_count} sources and {fact_count}/{total_facts} cited facts."
        )
    return "Website-ready APHR product generated from a report bundle."


def _upsert_product(products: List[Dict[str, Any]], product: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [item for item in products if item.get("slug") != product["slug"]] + [product]


def _review_metadata(
    args: argparse.Namespace, event: Dict[str, Any], manifest: Dict[str, Any]
) -> Dict[str, Any]:
    """Validate explicit editorial metadata before creating publication files."""
    metadata: Dict[str, Any] = {}
    reviewers = [name.strip() for name in getattr(args, "expert_reviewer", [])]
    if any(not name for name in reviewers):
        raise ValueError("expert-reviewer must not be empty")
    note = getattr(args, "review_note", None)
    if note is not None and (not reviewers or not note.strip()):
        raise ValueError("review-note requires an expert-reviewer and nonempty text")
    if reviewers:
        metadata["expert_review"] = {"reviewers": list(dict.fromkeys(reviewers))}
        if note is not None:
            metadata["expert_review"]["note"] = note.strip()
    links = {}
    for item in getattr(args, "expert_reviewer_url", []):
        name, separator, url = item.partition("=")
        name = name.strip()
        if not separator or name not in reviewers or not reviewer_url(url):
            raise ValueError("expert-reviewer-url must be NAME=HTTP(S)_URL for an explicitly named reviewer")
        if name in links and links[name] != url:
            raise ValueError("A reviewer must have only one profile URL")
        links[name] = url
    if links:
        metadata["expert_review"]["reviewer_links"] = links

    supersedes = getattr(args, "supersedes", None)
    if supersedes is not None:
        _validate_slug(supersedes, "supersedes")
        if supersedes == args.product_slug:
            raise ValueError("A product cannot supersede itself")
        products = event.get("products", [])
        original = next((item for item in products if item.get("slug") == supersedes), None)
        if original is None:
            raise ValueError("supersedes must name an existing product in this event")
        if any(item.get("supersedes") == supersedes for item in products):
            raise ValueError("This product already has a revision; supersede its latest revision instead")
        if original.get("product_type") != manifest.get("product_type"):
            raise ValueError("A revision must retain the original product type")
        original_time = original.get("snapshot_time")
        revision_time = _snapshot_time(manifest)
        if _is_snapshot_product(manifest) and _sort_datetime(original_time) != _sort_datetime(revision_time):
            raise ValueError("A revision must retain the original snapshot time")
        metadata["supersedes"] = supersedes
    return metadata


def _update_review(args: argparse.Namespace) -> Path:
    forbidden = (
        "bundle", "supersedes", "event_title", "event_date", "event_type",
        "event_meta", "event_description", "event_tag", "product_title",
        "product_summary", "set_latest",
    )
    if any(getattr(args, name, None) is not None and getattr(args, name) is not False for name in forbidden):
        raise ValueError("update-review accepts only event/product slugs, reviewer metadata, and --build")
    event_dir, product_dir = _product_destination(args.event_slug, args.product_slug)
    event_path = event_dir / "event.json"
    if not event_path.exists() or not product_dir.is_dir():
        raise ValueError("update-review requires an existing product")
    event = _read_json(event_path)
    product = next((item for item in event.get("products", []) if item.get("slug") == args.product_slug), None)
    if product is None:
        raise ValueError("update-review requires an existing product in this event")
    metadata = _review_metadata(args, event, {})
    if "expert_review" not in metadata:
        raise ValueError("update-review requires at least one expert-reviewer")
    product["expert_review"] = metadata["expert_review"]
    _write_json(event_path, event)
    if args.build:
        build_site()
    return product_dir


def publish(args: argparse.Namespace) -> Path:
    if getattr(args, "update_review", False):
        return _update_review(args)
    bundle_dir = Path(args.bundle)
    source_manifest = _read_json(bundle_dir / "manifest.json")

    event_dir, product_dir = _product_destination(
        args.event_slug, args.product_slug
    )
    event_json_path = event_dir / "event.json"
    event = _read_json(event_json_path) if event_json_path.exists() else {}
    review_metadata = _review_metadata(args, event, source_manifest)
    _copy_bundle(bundle_dir, product_dir)

    manifest_path = product_dir / "manifest.json"
    manifest = _read_json(manifest_path)
    manifest["event_slug"] = args.event_slug
    manifest["product_slug"] = args.product_slug
    if args.event_title:
        manifest["event_title"] = args.event_title
    if args.event_date:
        manifest["event_date"] = args.event_date
    if args.product_title:
        manifest["title"] = args.product_title
    _write_json(manifest_path, manifest)

    event_date = args.event_date or manifest.get("event_date") or source_manifest.get("event_date") or ""
    event_title = (
        args.event_title
        or event.get("title")
        or manifest.get("event_title")
        or args.event_slug
    )
    event.update(
        {
            "schema_version": "1.0",
            "slug": args.event_slug,
            "title": event_title,
            "event_type": args.event_type or "Earthquake",
            "event_date": event_date,
            "tag": args.event_tag or event.get("tag") or _format_product_type(manifest.get("product_type", "")),
            "meta": args.event_meta or event.get("meta") or _default_event_meta(manifest, event_date),
            "description": args.event_description
            or event.get("description")
            or f"Automated APHR products for {event_title}.",
        }
    )

    product = {
        "slug": args.product_slug,
        "title": args.product_title or _default_product_title(manifest, args.product_slug),
        "product_type": manifest.get("product_type", ""),
        "generated_at": manifest.get("generated_at"),
        "counts": manifest.get("counts", {}),
        "summary": args.product_summary or _default_product_summary(manifest),
        "manifest_path": f"products/{args.product_slug}/manifest.json",
    }
    snapshot_time = _snapshot_time(manifest)
    if snapshot_time:
        product["snapshot_time"] = snapshot_time
    if _is_temporal_product(manifest):
        product["featured"] = True
    product.update(review_metadata)

    event["products"] = _upsert_product(event.get("products", []), product)
    if _should_set_latest_snapshot(event, product, args.set_latest):
        event["latest_product_slug"] = args.product_slug
    _write_json(event_json_path, event)

    if args.build:
        build_site()

    return product_dir


def main(argv=None) -> int:
    args = _parse_args(argv)
    product_dir = publish(args)
    print("=" * 72)
    print("REVIEW METADATA UPDATED" if args.update_review else "PRODUCT PUBLISHED")
    print(f"  product: {product_dir}")
    print(f"  event:   {ROOT / 'events' / args.event_slug / 'event.json'}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
