from app.domain.catalog import SeedListing, load_seed, rate_basis
from app.pricing.landed import ItemPrice


def test_load_seed_catalog() -> None:
    listings = load_seed()
    assert len(listings) == 28

    ids = [listing.id for listing in listings]
    assert len(set(ids)) == 28

    valid_platforms = {"amazon", "flipkart", "blinkit", "instamart", "zepto"}
    for listing in listings:
        assert listing.platform in valid_platforms
        pack = listing.pack
        assert pack.qty > 0
        assert pack.unit in ("g", "ml", "pc")


def test_wal_1_product_key() -> None:
    listings = load_seed()
    wal_1 = next(item for item in listings if item.id == "wal-1")
    assert wal_1.product_key == "nutraj_walnuts"


def test_seed_listing_item_price() -> None:
    listings = load_seed()
    stp_1 = next(item for item in listings if item.id == "stp-1")
    assert isinstance(stp_1, SeedListing)
    assert stp_1.item_price() == ItemPrice(listed=29200, mrp=36500, member_price=27700)


def test_rate_basis() -> None:
    assert rate_basis("dryfruits", "g") == (100, "100g")
    assert rate_basis("staples", "g") == (1000, "kg")
    assert rate_basis("cleaning", "ml") == (1000, "L")
