"""Pre-built cross-platform bundles for Zero-Manual One-Click DealFinder."""

from sqlmodel import Session, select

from app.domain.catalog import all_listings
from app.domain.models import Need

DRYFRUITS_500G_NEEDS: tuple[tuple[str, str, str], ...] = (
    ("Cashews 500g", "cashews", "500g"),
    ("Almonds 500g", "almonds", "500g"),
    ("Walnuts 500g", "walnuts", "500g"),
    ("Pumpkin Seeds 500g", "pumpkin_seeds", "500g"),
    ("Sunflower Seeds 500g", "sunflower_seeds", "500g"),
    ("Chia Seeds 500g", "chia_seeds", "500g"),
    ("Flax Seeds 500g", "flax_seeds", "500g"),
    ("Dates 500g", "dates", "500g"),
)


def apply_dryfruits_500g_bundle(
    session: Session,
    household_id: int,
    list_id: int,
) -> tuple[int, list[str]]:
    existing_open_needs = session.exec(
        select(Need).where(
            Need.list_id == list_id,
            Need.status == "open",
        )
    ).all()
    existing_keys = {(n.family_key, n.quantity) for n in existing_open_needs}

    catalog = all_listings(session=session, household_id=household_id)
    available_families = {item.family_key for item in catalog}

    added_needs = 0
    for line_id, family_key, quantity in DRYFRUITS_500G_NEEDS:
        if (family_key, quantity) not in existing_keys:
            session.add(
                Need(
                    list_id=list_id,
                    line_id=line_id,
                    product_key=None,
                    family_key=family_key,
                    quantity=quantity,
                    qty=1,
                    status="open",
                )
            )
            existing_keys.add((family_key, quantity))
            added_needs += 1

    session.commit()

    unpriced_families = [
        family_key
        for _, family_key, _ in DRYFRUITS_500G_NEEDS
        if family_key not in available_families
    ]

    return added_needs, unpriced_families
