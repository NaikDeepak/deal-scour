import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.domain.models import CatalogProduct
from app.pricing.fee_schedules import Platform
from app.sources.autofill import _extract_family_and_category
from app.sources.urls import parse_product_url

_TARGET_SUFFIX_RE = re.compile(r"\s*\(target\s+[^)]*\)\s*$", re.IGNORECASE)


class CatalogSuggestion(BaseModel):
    platform: Platform
    sku: str
    url: str


class ImportSkippedItem(BaseModel):
    seed_product_id: str
    reason: str


class CatalogImportReport(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: list[ImportSkippedItem] = Field(default_factory=list)


def strip_target_suffix(raw_name: str) -> str:
    return _TARGET_SUFFIX_RE.sub("", raw_name.strip()).strip()


def weight_g_to_pack_label(weight_g: int) -> str:
    if weight_g >= 1000 and weight_g % 1000 == 0:
        return f"{weight_g // 1000}kg"
    return f"{weight_g}g"


def category_to_slug(category: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", category.strip().lower()).strip("_")
    return slug[:40] or "staples"


def infer_catalog_family_key(name: str, category: str) -> str:
    family_from_rules, _ = _extract_family_and_category(name)
    if family_from_rules:
        return family_from_rules[:40]
    return category_to_slug(category)


def import_catalog_csv(
    session: Session,
    household_id: int,
    csv_path: Path | str,
    now_dt: datetime | None = None,
) -> CatalogImportReport:
    path = Path(csv_path)
    now = now_dt or datetime.now(UTC)

    groups: dict[str, list[dict[str, str]]] = {}
    skipped: list[ImportSkippedItem] = []

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            seed_id = (row.get("seed_product_id") or "").strip()
            if not seed_id:
                skipped.append(
                    ImportSkippedItem(seed_product_id="", reason="Missing seed_product_id")
                )
                continue
            groups.setdefault(seed_id, []).append(row)

    created = 0
    updated = 0

    for seed_id, rows in groups.items():
        if len(seed_id) > 40:
            skipped.append(
                ImportSkippedItem(
                    seed_product_id=seed_id[:40],
                    reason="seed_product_id exceeds 40 characters",
                )
            )
            continue

        first = rows[0]
        raw_name = (first.get("product_name") or "").strip()
        name = strip_target_suffix(raw_name)
        if not name:
            skipped.append(
                ImportSkippedItem(seed_product_id=seed_id, reason="Empty product name")
            )
            continue
        if len(name) > 160:
            skipped.append(
                ImportSkippedItem(
                    seed_product_id=seed_id,
                    reason="Product name exceeds 160 characters",
                )
            )
            continue

        brand = (first.get("brand") or "").strip()
        if not brand:
            skipped.append(
                ImportSkippedItem(seed_product_id=seed_id, reason="Empty brand")
            )
            continue
        if len(brand) > 80:
            skipped.append(
                ImportSkippedItem(
                    seed_product_id=seed_id,
                    reason="Brand exceeds 80 characters",
                )
            )
            continue

        category = (first.get("category") or "").strip()
        if not category or len(category) > 80:
            skipped.append(
                ImportSkippedItem(
                    seed_product_id=seed_id,
                    reason="Invalid or overly long category",
                )
            )
            continue

        raw_weight = (first.get("target_pack_weight_g") or "").strip()
        try:
            weight_g = int(raw_weight)
        except ValueError:
            skipped.append(
                ImportSkippedItem(
                    seed_product_id=seed_id,
                    reason=f"Invalid target_pack_weight_g: '{raw_weight}'",
                )
            )
            continue
        if weight_g <= 0:
            skipped.append(
                ImportSkippedItem(
                    seed_product_id=seed_id,
                    reason="target_pack_weight_g must be positive",
                )
            )
            continue

        pack_label = weight_g_to_pack_label(weight_g)
        family_key = infer_catalog_family_key(name, category)

        suggestions: list[dict[str, str]] = []
        seen_suggestions: set[tuple[str, str]] = set()
        for r in rows:
            url_type = (r.get("url_type") or "").strip()
            raw_url = (r.get("url") or "").strip()
            if url_type == "Direct product URL" and raw_url:
                try:
                    ref = parse_product_url(raw_url)
                except ValueError:
                    continue
                key = (ref.platform, ref.sku)
                if key not in seen_suggestions:
                    seen_suggestions.add(key)
                    suggestions.append(
                        {
                            "platform": ref.platform,
                            "sku": ref.sku,
                            "url": ref.url,
                        }
                    )

        suggestions_json = json.dumps(suggestions)

        existing = session.exec(
            select(CatalogProduct).where(
                CatalogProduct.household_id == household_id,
                CatalogProduct.seed_product_id == seed_id,
            )
        ).first()

        if existing is not None:
            existing.name = name
            existing.brand = brand
            existing.category = category
            existing.family_key = family_key
            existing.pack_label = pack_label
            existing.target_pack_weight_g = weight_g
            existing.suggestions_json = suggestions_json
            existing.updated_at = now
            session.add(existing)
            updated += 1
        else:
            session.add(
                CatalogProduct(
                    household_id=household_id,
                    seed_product_id=seed_id,
                    name=name,
                    brand=brand,
                    category=category,
                    family_key=family_key,
                    pack_label=pack_label,
                    target_pack_weight_g=weight_g,
                    suggestions_json=suggestions_json,
                    created_at=now,
                    updated_at=now,
                )
            )
            created += 1

    session.commit()
    return CatalogImportReport(created=created, updated=updated, skipped=skipped)
