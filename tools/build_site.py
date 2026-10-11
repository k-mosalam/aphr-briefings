#!/usr/bin/env python3
"""Build static APHR website pages from event/product manifests."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from html import escape
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
_TEMPLATE_TOKEN = re.compile(r"{{\s*([a-z][a-z0-9_]*)\s*}}")
_TEMPLATE_LINE = re.compile(
    r"^[ \t]*{{\s*([a-z][a-z0-9_]*)\s*}}[ \t]*$", re.MULTILINE
)


def _render_brand_strip(asset_prefix: str = "") -> str:
    return f"""
<div class="brand-strip" role="group" aria-label="Research affiliations and supporters">
  <a class="brand-logo brand-logo-nsf-steer" href="https://www.steer.network/" target="_blank" rel="noopener" aria-label="Visit the StEER Network website">
    <img src="{asset_prefix}assets/images/nsf-steer.png" width="542" height="134" alt="National Science Foundation and StEER Network">
  </a>
  <a class="brand-logo brand-logo-peer" href="https://peer.berkeley.edu/" target="_blank" rel="noopener" aria-label="Visit the Pacific Earthquake Engineering Research Center website">
    <img src="{asset_prefix}assets/images/peer-logo.svg" width="95" height="96" alt="Pacific Earthquake Engineering Research Center">
  </a>
  <a class="brand-logo brand-logo-stairlab" href="https://stairlab.berkeley.edu/" target="_blank" rel="noopener" aria-label="Visit the STAIRLab website">
    <img src="{asset_prefix}assets/images/stairlab.png" width="1535" height="226" alt="STAIRLab">
  </a>
</div>
""".strip()


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _template(name: str, values: Dict[str, str]) -> str:
    text = (ROOT / "templates" / name).read_text(encoding="utf-8")

    def remove_empty_line(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in values and not values[key]:
            return ""
        return match.group(0)

    def replace_token(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise ValueError(f"Missing template value {key!r} for {name}")
        return values[key]

    text = _TEMPLATE_LINE.sub(remove_empty_line, text)
    return _TEMPLATE_TOKEN.sub(replace_token, text)


def _render_breadcrumb(crumbs: List[Dict[str, str]]) -> str:
    parts = []
    for index, crumb in enumerate(crumbs):
        if index:
            parts.append('<span class="crumb-separator">›</span>')

        label = escape(str(crumb["label"]))
        href = crumb.get("href")
        classes = ["crumb"]
        if crumb.get("optional"):
            classes.append("optional-crumb")
        if not href:
            classes.append("crumb-current")

        class_attr = " ".join(classes)
        if href:
            parts.append(
                f'<a class="{class_attr}" href="{escape(href, quote=True)}">{label}</a>'
            )
        else:
            parts.append(f'<span class="{class_attr}">{label}</span>')

    return '<nav class="global-breadcrumb" aria-label="Breadcrumb">' + "".join(parts) + "</nav>"


def _render_topbar(crumbs: List[Dict[str, str]]) -> str:
    return f"""
<div class="global-topbar">
  {_render_breadcrumb(crumbs)}
  <button type="button" class="content-menu-button" data-site-nav-open="site-content-drawer" aria-controls="site-content-drawer" aria-expanded="false" aria-label="Open contents" data-tooltip="Contents">
    <span class="hamburger" aria-hidden="true"><span></span></span>
  </button>
</div>
""".strip()


def _render_content_drawer(links: List[Dict[str, str]]) -> str:
    rendered_links = "\n".join(
        (
            f'<a href="{escape(link["href"], quote=True)}" data-site-nav-close>'
            f'{escape(link["label"])}</a>'
        )
        for link in links
    )
    return f"""
<div class="site-nav-shell" id="site-content-drawer" aria-hidden="true" inert>
  <div class="site-nav-backdrop" data-site-nav-close></div>
  <aside class="site-nav-panel" role="dialog" aria-modal="true" aria-labelledby="site-nav-title">
    <div class="site-nav-header">
      <h2 id="site-nav-title">Contents</h2>
      <button type="button" class="site-nav-close" data-site-nav-close aria-label="Close contents">&times;</button>
    </div>
    <nav class="site-toc-links">{rendered_links}</nav>
  </aside>
</div>
""".strip()


def _home_crumbs(home_href: str | None = None) -> List[Dict[str, str]]:
    return [
        {"label": "APHR Events", "href": home_href or ""},
    ]


def _clean_current_crumbs(crumbs: List[Dict[str, str]]) -> List[Dict[str, str]]:
    cleaned = []
    for crumb in crumbs:
        item = dict(crumb)
        if item.get("href") == "":
            item.pop("href")
        cleaned.append(item)
    return cleaned


def _product_type(value: str) -> str:
    labels = {
        "snapshot_briefing": "Snapshot briefing",
        "temporal_recon": "Temporal analysis",
    }
    return labels.get(value, value.replace("_", " ").title() if value else "Product")


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None


def _sort_datetime(value: Any) -> str:
    parsed = _parse_datetime(value)
    if parsed:
        return _normalize_aware_datetime(parsed).isoformat()
    return str(value or "")


def _format_month_day_year(value: datetime) -> str:
    return f"{value.strftime('%b')} {value.day}, {value.year}"


def _normalize_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc)
    return value


def _format_date(value: Any) -> str:
    parsed = _parse_datetime(value)
    if parsed:
        return _format_month_day_year(_normalize_aware_datetime(parsed))
    return str(value or "")


def _format_timeline_date(value: Any) -> str:
    parsed = _parse_datetime(value)
    if parsed:
        parsed = _normalize_aware_datetime(parsed)
        return f"{parsed.strftime('%b')}<span>{parsed.day}, {parsed.year}</span>"
    return escape(str(value or ""))


def _format_snapshot_timeline_date(value: Any) -> str:
    if not value:
        return "Time<span>unavailable</span>"
    return _format_timeline_date(value)


def _format_generated(value: Any) -> str:
    parsed = _parse_datetime(value)
    if not parsed:
        return str(value or "")
    parsed = _normalize_aware_datetime(parsed)
    if parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0:
        return _format_month_day_year(parsed)
    zone = " UTC" if parsed.tzinfo else ""
    return f"{_format_month_day_year(parsed)} {parsed.strftime('%H:%M')}{zone}"


def _compact_meta_bits(*values: str) -> str:
    return "\n".join(
        f"<span>{escape(value)}</span>" for value in values if value
    )


def _clean_event_meta_bit(value: str) -> str:
    cleaned = " ".join(value.split())
    cleaned = cleaned.replace(" local time", "")
    return cleaned.strip()


def _extract_event_meta(event: Dict[str, Any]) -> List[str]:
    meta = str(event.get("meta", ""))
    bits = []
    for bit in meta.split("·"):
        cleaned = _clean_event_meta_bit(bit)
        if cleaned:
            bits.append(cleaned)
    return bits[:3]


def _event_meta_text(event: Dict[str, Any]) -> str:
    bits = _extract_event_meta(event)
    if bits:
        return " · ".join(bits)

    fallback = []
    if event.get("event_date"):
        fallback.append(_format_date(event["event_date"]))
    if event.get("event_type"):
        fallback.append(str(event["event_type"]))
    return " · ".join(fallback)


def _product_counts(product: Dict[str, Any]) -> Dict[str, Any]:
    return product.get("counts", {}) or {}


def _product_type_key(product: Dict[str, Any]) -> str:
    return str(product.get("product_type", "")).strip().lower()


def _is_temporal_product(product: Dict[str, Any]) -> bool:
    product_type = _product_type_key(product)
    return product_type.startswith("temporal")


def _is_snapshot_product(product: Dict[str, Any]) -> bool:
    product_type = _product_type_key(product)
    return product_type.startswith("snapshot")


def _product_href(product: Dict[str, Any]) -> str:
    href = product.get("href")
    if href:
        return str(href)
    return f"products/{escape(str(product['slug']), quote=True)}/"


def _product_status_label(event: Dict[str, Any], product: Dict[str, Any]) -> str:
    label = _product_type(str(product.get("product_type", "")))
    if product.get("featured"):
        return label
    if product.get("slug") == event.get("latest_product_slug"):
        return "Latest " + label[:1].lower() + label[1:]
    return label


def _current_products(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    products = event.get("products", [])
    superseded = {product.get("supersedes") for product in products if product.get("supersedes")}
    return [product for product in products if product.get("slug") not in superseded]


def _display_product_title(product: Dict[str, Any], fallback: str = "") -> str:
    title = str(product.get("title") or fallback or product["slug"])
    if product.get("supersedes"):
        title = re.sub(r"\s*·\s*Revised\s*$", "", title, flags=re.IGNORECASE)
    return title


def reviewer_url(value: Any) -> str | None:
    """Allow only absolute web profile links, including for hand-edited metadata."""
    if not isinstance(value, str) or any(character.isspace() for character in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in ("https", "http") or not parsed.hostname:
            return None
    except ValueError:
        return None
    return value


def _latest_revision(event: Dict[str, Any], product: Dict[str, Any]) -> Dict[str, Any] | None:
    revisions = {item["supersedes"]: item for item in event.get("products", []) if item.get("supersedes")}
    latest = None
    slug = product["slug"]
    seen = {slug}
    while slug in revisions:
        latest = revisions[slug]
        slug = latest["slug"]
        if slug in seen:
            raise ValueError("Circular product revision history")
        seen.add(slug)
    return latest


def _render_expert_review(product: Dict[str, Any]) -> str:
    review = product.get("expert_review") or {}
    reviewers = review.get("reviewers", [])
    if not reviewers:
        return ""
    links = review.get("reviewer_links") or {}
    names = []
    for reviewer in reviewers:
        name = escape(str(reviewer))
        url = reviewer_url(links.get(reviewer))
        if url:
            name = f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{name}</a>'
        names.append(f"<li>{name}</li>")
    panel_id = "expert-review-" + escape(str(product["slug"]), quote=True)
    return (
        '<details class="expert-review" data-expert-review>'
        f'<summary class="expert-review-badge" aria-controls="{panel_id}">Expert reviewed</summary>'
        f'<div class="expert-review-panel" id="{panel_id}" role="group" aria-label="Domain expert reviewers">'
        '<div class="expert-review-popover"><p>Reviewed by</p><ul>'
        + "".join(names) + '</ul></div></div></details>'
    )


def _render_product_heading(event_title: str, product_title: str, badge: str) -> str:
    if not badge:
        return (
            '<h1 class="report-title">\n'
            f'          <span class="title-location">{escape(event_title)}</span>\n'
            f'          <span class="title-product">{escape(product_title)}</span>\n'
            '        </h1>'
        )
    return (
        f'<h1 class="report-title"><span class="title-location">{escape(event_title)}</span></h1>\n'
        '        <div class="product-subtitle-row">'
        f'<p class="title-product">{escape(product_title)}</p>{badge}</div>'
    )


def _review_script(asset_prefix: str) -> str:
    return f'\n  <script src="{asset_prefix}assets/js/review.js?v=20261011-review2"></script>'


def _render_product_redirect(product: Dict[str, Any], latest: Dict[str, Any]) -> str:
    href = "../" + escape(str(latest["slug"]), quote=True) + "/"
    title = escape(_display_product_title(product))
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'  <title>{title} · APHR</title>\n'
        f'  <link rel="canonical" href="{href}">\n'
        f'  <meta http-equiv="refresh" content="0; url={href}">\n'
        '</head>\n<body>\n'
        f'  <p><a href="{href}">Open briefing</a></p>\n'
        '</body>\n</html>\n'
    )


def _read_events() -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for event_file in sorted((ROOT / "events").glob("*/event.json")):
        event = _read_json(event_file)
        event.setdefault("slug", event_file.parent.name)
        event["_dir"] = event_file.parent
        event.setdefault("products", [])
        events.append(event)
    return events


def _event_sort_key(event: Dict[str, Any]) -> str:
    return _sort_datetime(event.get("event_date") or event.get("sort_date"))


def _product_sort_key(product: Dict[str, Any]) -> str:
    return _sort_datetime(
        product.get("snapshot_time")
        or product.get("generated_at")
        or product.get("title")
        or product.get("slug")
    )


def _render_home_timeline(events: Iterable[Dict[str, Any]]) -> str:
    items = []
    sorted_events = sorted(events, key=_event_sort_key, reverse=True)
    for index, event in enumerate(sorted_events):
        slug = event["slug"]
        title = escape(str(event.get("title", slug)))
        tag = str(event.get("tag", event.get("event_type", "APHR event")))
        event_type = str(event.get("event_type", "APHR event"))
        date = _format_date(event.get("event_date") or event.get("sort_date"))
        timeline_date = _format_timeline_date(event.get("event_date") or event.get("sort_date"))
        products = _current_products(event)
        snapshot_count = sum(1 for product in products if _is_snapshot_product(product))
        temporal_count = sum(1 for product in products if _is_temporal_product(product))
        other_count = len(products) - snapshot_count - temporal_count
        product_labels = []
        if snapshot_count:
            product_labels.append(
                f"{snapshot_count} snapshot"
                if snapshot_count == 1
                else f"{snapshot_count} snapshots"
            )
        if temporal_count:
            product_labels.append("Temporal analysis")
        if other_count:
            product_labels.append(
                f"{other_count} product" if other_count == 1 else f"{other_count} products"
            )
        product_label = " · ".join(product_labels)
        meta_bits = _extract_event_meta(event) or [date]
        if product_label:
            meta_bits.append(product_label)
        button = escape(str(event.get("button_label", "Open event briefing")))
        item_class = "timeline-item event-timeline-item"
        if index == 0:
            item_class += " is-latest"
        items.append(
            f"""
      <article class="{item_class}">
        <div class="timeline-index" aria-hidden="true">
          <div class="timeline-dot"></div>
          <div class="timeline-date">{timeline_date}</div>
        </div>
        <div class="timeline-body">
          <div class="timeline-kicker">{escape(event_type)} · {escape(tag)}</div>
          <h3 class="timeline-title">{title}</h3>
          <div class="timeline-meta">{_compact_meta_bits(*meta_bits)}</div>
          <a class="timeline-link" href="events/{escape(slug, quote=True)}/">{button}<span aria-hidden="true">&rarr;</span></a>
        </div>
      </article>
            """.strip()
        )
    return "\n\n".join(items)


def _render_product_timeline_item(event: Dict[str, Any], product: Dict[str, Any]) -> str:
    slug = str(product["slug"])
    title = escape(_display_product_title(product))
    badge = _render_expert_review(product)
    heading = f'<h3 class="timeline-title">{title}</h3>'
    if badge:
        heading = f'<div class="product-subtitle-row">{heading}{badge}</div>'
    snapshot_time = product.get("snapshot_time")
    generated_at = product.get("generated_at")
    stats = _product_counts(product)
    meta_bits = []
    if generated_at:
        meta_bits.append(f"Generated { _format_generated(generated_at) }")
    if stats.get("sources") is not None:
        meta_bits.append(f"Sources: {stats['sources']}")
    if stats.get("facts_cited") is not None and stats.get("facts_total") is not None:
        meta_bits.append(f"Facts cited: {stats['facts_cited']}/{stats['facts_total']}")
    timeline_date = _format_snapshot_timeline_date(snapshot_time)
    tag = _product_status_label(event, product)
    item_class = "timeline-item product-timeline-item"
    if slug == event.get("latest_product_slug"):
        item_class += " is-latest"
    return f"""
      <article class="{item_class}">
        <div class="timeline-index" aria-hidden="true">
          <div class="timeline-dot"></div>
          <div class="timeline-date">{timeline_date}</div>
        </div>
        <div class="timeline-body">
          <div class="timeline-kicker">{escape(tag)}</div>
          {heading}
          <div class="timeline-meta">{_compact_meta_bits(*meta_bits)}</div>
          <a class="timeline-link" href="{escape(_product_href(product), quote=True)}">Open snapshot<span aria-hidden="true">&rarr;</span></a>
        </div>
      </article>
    """.strip()


def _render_temporal_feature(event: Dict[str, Any], products: Iterable[Dict[str, Any]]) -> str:
    cards = []
    for product in sorted(products, key=_product_sort_key, reverse=True):
        slug = str(product["slug"])
        title = escape(_display_product_title(product))
        badge = _render_expert_review(product)
        heading = f'<h3>{title}</h3>'
        if badge:
            heading = f'<div class="product-subtitle-row">{heading}{badge}</div>'
        generated_at = product.get("generated_at")
        stats = _product_counts(product)
        meta_bits = []
        if generated_at:
            meta_bits.append(f"Generated { _format_generated(generated_at) }")
        if stats.get("snapshots") is not None:
            count = stats["snapshots"]
            meta_bits.append(f"{count} snapshot" if count == 1 else f"{count} snapshots")
        if stats.get("tracks") is not None:
            meta_bits.append(f"{stats['tracks']} temporal tracks")
        if stats.get("source_references") is not None:
            meta_bits.append(f"{stats['source_references']} sources")
        summary = escape(str(product.get("summary", "")))
        cards.append(
            f"""
        <article class="featured-product is-temporal">
          {heading}
          <div class="timeline-meta">{_compact_meta_bits(*meta_bits)}</div>
          {f'<p>{summary}</p>' if summary else ''}
          <a class="timeline-link" href="{escape(_product_href(product), quote=True)}">Open temporal analysis<span aria-hidden="true">&rarr;</span></a>
        </article>
            """.strip()
        )

    if not cards:
        return ""

    return f"""
      <section class="featured-product-section" id="temporal-analysis" aria-label="Temporal analysis">
        <div class="section-heading">
          <h2>Temporal analysis</h2>
        </div>
        <div class="featured-product-list">
          {"".join(cards)}
        </div>
      </section>
    """.strip()


def _render_snapshot_empty() -> str:
    return """
        <p class="timeline-empty">Snapshot products will appear here after they are published for this event.</p>
    """.strip()


def _render_product_meta(event: Dict[str, Any], manifest: Dict[str, Any]) -> str:
    pills = []
    if manifest.get("generated_at"):
        pills.append(f"Generated {_format_generated(manifest['generated_at'])}")
    counts = manifest.get("counts", {})
    if _is_temporal_product(manifest):
        if counts.get("snapshots") is not None:
            count = counts["snapshots"]
            pills.append(f"{count} snapshot" if count == 1 else f"{count} snapshots")
        if counts.get("tracks") is not None:
            pills.append(f"{counts['tracks']} temporal tracks")
        if counts.get("source_references") is not None:
            pills.append(f"{counts['source_references']} sources")
        return "\n          ".join(f"<span>{escape(str(pill))}</span>" for pill in pills)
    if counts.get("sources") is not None:
        pills.append(f"{counts['sources']} sources")
    if counts.get("facts_cited") is not None and counts.get("facts_total") is not None:
        pills.append(f"{counts['facts_cited']}/{counts['facts_total']} facts cited")
    return "\n          ".join(f"<span>{escape(str(pill))}</span>" for pill in pills)


def _product_toc(manifest: Dict[str, Any]) -> List[Dict[str, str]]:
    links = [{"label": "Overview", "href": "#product-overview"}]
    for section in manifest.get("sections", []):
        section_id = section.get("id")
        title = section.get("title")
        if section_id and title:
            links.append({"label": str(title), "href": f"#{section_id}"})
    return links


def _build_product_page(event: Dict[str, Any], product: Dict[str, Any]) -> None:
    if product.get("standalone"):
        print(f"PRESERVE standalone product page: {event['slug']}/{product['slug']}")
        return

    product_dir = Path(event["_dir"]) / "products" / str(product["slug"])
    latest = _latest_revision(event, product)
    if latest:
        _write(product_dir / "index.html", _render_product_redirect(product, latest))
        print(f"BUILT redirect {product_dir / 'index.html'}")
        return
    content_path = product_dir / "content.html"
    manifest_path = product_dir / "manifest.json"
    if not content_path.exists() or not manifest_path.exists():
        print(f"SKIP missing product bundle: {product_dir}")
        return

    content_html = content_path.read_text(encoding="utf-8")
    manifest = _read_json(manifest_path)
    product_title = _display_product_title(product, str(manifest.get("title") or ""))
    product_type = _product_type(str(manifest.get("product_type", "")))
    badge = _render_expert_review(product)
    page = _template(
        "product.html",
        {
            "page_title": escape(f"{product_title} · APHR"),
            "site_css_version": "20261011-review2" if badge else "20260815-closure",
            "topbar": _render_topbar(
                _clean_current_crumbs(
                    _home_crumbs("../../../../")
                    + [
                        {
                            "label": str(event.get("title", event["slug"])),
                            "href": "../../",
                        },
                        {"label": product_title},
                    ]
                )
            ),
            "content_drawer": _render_content_drawer(_product_toc(manifest)),
            "product_type": escape(product_type),
            "event_title": escape(str(event.get("title", manifest.get("event_title", "")))),
            "product_title": escape(product_title),
            "product_heading": _render_product_heading(str(event.get("title", manifest.get("event_title", ""))), product_title, badge),
            "review_script": _review_script("../../../../") if badge else "",
            "product_meta": _render_product_meta(event, manifest),
            "content_html": content_html,
        },
    )
    _write(product_dir / "index.html", page)
    print(f"BUILT {product_dir / 'index.html'}")


def _build_event_page(event: Dict[str, Any]) -> None:
    products = event.get("products", [])
    if not products:
        print(f"PRESERVE legacy event page: {event['slug']}")
        return

    current_products = _current_products(event)
    temporal_products = [product for product in current_products if _is_temporal_product(product)]
    snapshot_products = [product for product in current_products if _is_snapshot_product(product)]
    product_timeline = "\n\n".join(
        _render_product_timeline_item(event, product)
        for product in sorted(snapshot_products, key=_product_sort_key, reverse=True)
    )
    if not product_timeline:
        product_timeline = _render_snapshot_empty()

    drawer_links = [{"label": "Event Overview", "href": "#event-overview"}]
    if temporal_products:
        drawer_links.append({"label": "Temporal Analysis", "href": "#temporal-analysis"})
    drawer_links.append({"label": "Snapshots", "href": "#snapshots"})

    page = _template(
        "event.html",
        {
            "page_title": escape(str(event.get("title", event["slug"])) + " · APHR"),
            "site_css_version": "20261011-review2" if any(product.get("expert_review") for product in current_products) else "20260815-closure",
            "review_script": _review_script("../../") if any(product.get("expert_review") for product in current_products) else "",
            "topbar": _render_topbar(
                _clean_current_crumbs(
                    _home_crumbs("../../")
                    + [{"label": str(event.get("title", event["slug"]))}]
                )
            ),
            "content_drawer": _render_content_drawer(drawer_links),
            "event_type": escape(str(event.get("event_type", "APHR event"))),
            "event_title": escape(str(event.get("title", event["slug"]))),
            "event_description": escape(_event_meta_text(event)),
            "temporal_feature": _render_temporal_feature(event, temporal_products),
            "product_timeline": product_timeline,
        },
    )
    _write(Path(event["_dir"]) / "index.html", page)
    print(f"BUILT {Path(event['_dir']) / 'index.html'}")


def build_site() -> None:
    events = _read_events()
    if not events:
        raise RuntimeError("No events/*/event.json files found.")

    home = _template(
        "home.html",
        {
            "page_title": "APHR Events",
            "topbar": _render_topbar(
                _clean_current_crumbs(
                    [
                        {"label": "APHR Events"},
                    ]
                )
            ),
            "content_drawer": _render_content_drawer(
                [
                    {"label": "Overview", "href": "#overview"},
                    {"label": "Events", "href": "#events"},
                    {"label": "Acknowledgments", "href": "#acknowledgments"},
                ]
            ),
            "brand_strip": _render_brand_strip(),
            "event_timeline": _render_home_timeline(events),
        },
    )
    _write(ROOT / "index.html", home)
    print(f"BUILT {ROOT / 'index.html'}")

    for event in events:
        for product in event.get("products", []):
            _build_product_page(event, product)
        _build_event_page(event)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    build_site()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
