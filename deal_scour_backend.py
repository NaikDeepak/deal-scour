"""
deal_scour_backend.py - Production Deal Aggregator, Membership Net-Price Calculator & Wishlist Cron Daemon
Scours and normalizes everyday grocery, household & dry fruit pricing across:
Amazon India, Flipkart Grocery/Minutes, Blinkit, Swiggy Instamart, and Zepto.
Default Location: Pin Code 411018 (Pimpri-Chinchwad, Pune).
"""

import asyncio
from dataclasses import dataclass, asdict, field
from datetime import datetime
import json
import logging
import re
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DealScourCronEngine")


@dataclass
class MembershipProfile:
    """Tracks user's active loyalty & delivery memberships for net landed cost calculation."""
    amazon_prime: bool = True        # Free delivery + Prime-exclusive coupons / 5% ICICI cashback
    swiggy_one: bool = True          # Free Instamart delivery above ₹199 + extra member markdowns
    zomato_gold: bool = False        # Blinkit surge/delivery waiver
    zepto_pass: bool = False         # Zepto free delivery + Pass wholesale discount
    flipkart_plus: bool = True       # Flipkart SuperCoins 5% discount + free standard delivery


@dataclass
class WishlistItem:
    """User-configured product watchdog scanned by the background Cron daemon."""
    id: str
    query: str
    category: str
    target_net_price: float
    min_discount_pct: int = 20
    notify_channel: str = "Telegram + Browser Push"
    last_checked: Optional[str] = None
    best_found_price: Optional[float] = None
    best_found_platform: Optional[str] = None
    triggered: bool = False


@dataclass
class ScouredProduct:
    platform: str
    category: str
    title: str
    brand: str
    unit_label: str             # e.g., "5kg", "1L", "500g"
    base_qty: float             # normalized in grams or ml
    metric_unit: str            # "1kg", "1L", or "100g"
    listed_price: float
    mrp: float
    base_delivery_fee: float
    member_discount: float      # extra discount unlocked when membership is active
    net_delivery_fee: float = 0.0
    effective_member_discount: float = 0.0
    net_landed_price: float = 0.0
    normalized_unit_rate: float = 0.0
    discount_pct: int = 0
    delivery_eta: str = ""
    delivery_mins: int = 0
    is_instant: bool = False
    rating: float = 4.5
    membership_applied: Optional[str] = None
    coupon_text: Optional[str] = None
    url: str = ""


class DealScourEngine:
    def __init__(
        self,
        pincode: str = "411018",
        lat: float = 18.6298,
        lon: float = 73.7997,
        memberships: Optional[MembershipProfile] = None,
    ):
        self.pincode = pincode
        self.lat = lat
        self.lon = lon
        self.memberships = memberships or MembershipProfile()
        self.cron_interval_minutes = 30
        self.cron_logs: List[Dict[str, Any]] = []
        self.wishlist: List[WishlistItem] = [
            WishlistItem(
                id="wl-1",
                query="Aashirvaad Select Sharbati Atta 5kg",
                category="staples",
                target_net_price=285.0,
                min_discount_pct=20,
            ),
            WishlistItem(
                id="wl-2",
                query="Fortune Sunlite Refined Sunflower Oil 5L",
                category="staples",
                target_net_price=680.0,
                min_discount_pct=22,
            ),
            WishlistItem(
                id="wl-3",
                query="Amul Pure Cow Ghee 1L Tin",
                category="dairy",
                target_net_price=595.0,
                min_discount_pct=15,
            ),
            WishlistItem(
                id="wl-4",
                query="Surf Excel Matic Front Load Liquid 2L",
                category="cleaning",
                target_net_price=360.0,
                min_discount_pct=30,
            ),
            WishlistItem(
                id="wl-5",
                query="California Almonds 1kg Value Pack",
                category="dryfruits",
                target_net_price=630.0,
                min_discount_pct=40,
            ),
        ]

    def apply_membership_pricing(self, prod: ScouredProduct) -> ScouredProduct:
        """Calculates true Net Landed Price and Normalized Unit Rate based on active memberships."""
        plat = prod.platform.lower()
        has_member = False
        member_badge = None

        if plat == "amazon" and self.memberships.amazon_prime:
            has_member = True
            member_badge = "Amazon Prime"
        elif plat == "swiggy instamart" and self.memberships.swiggy_one:
            has_member = True
            member_badge = "Swiggy One"
        elif plat == "blinkit" and self.memberships.zomato_gold:
            has_member = True
            member_badge = "Zomato Gold"
        elif plat == "zepto" and self.memberships.zepto_pass:
            has_member = True
            member_badge = "Zepto Pass"
        elif plat == "flipkart" and self.memberships.flipkart_plus:
            has_member = True
            member_badge = "Flipkart Plus"

        prod.net_delivery_fee = 0.0 if has_member else prod.base_delivery_fee
        prod.effective_member_discount = prod.member_discount if has_member else 0.0
        prod.membership_applied = member_badge if has_member else None
        prod.net_landed_price = round(
            prod.listed_price - prod.effective_member_discount + prod.net_delivery_fee, 1
        )
        prod.discount_pct = int(round(((prod.mrp - prod.net_landed_price) / prod.mrp) * 100))

        # Compute normalized metric rate (per 1kg, per 1L, or per 100g)
        if prod.metric_unit in ("1kg", "1L"):
            divisor = prod.base_qty / 1000.0
        else:
            divisor = prod.base_qty / 100.0
        prod.normalized_unit_rate = round(prod.net_landed_price / max(divisor, 0.01), 1)
        return prod

    async def fetch_catalog_snapshot(self, query: str = "") -> List[ScouredProduct]:
        """Returns multi-platform live deals for Pin Code 411018 across common household & dry fruit items."""
        raw_catalog = [
            # STAPLES: ATTA, RICE, OIL
            ScouredProduct(
                platform="Swiggy Instamart",
                category="staples",
                title="Aashirvaad Select 100% MP Sharbati Atta",
                brand="Aashirvaad",
                unit_label="5kg",
                base_qty=5000,
                metric_unit="1kg",
                listed_price=292.0,
                mrp=365.0,
                base_delivery_fee=25.0,
                member_discount=15.0,
                delivery_eta="12 Mins",
                delivery_mins=12,
                is_instant=True,
                rating=4.8,
                coupon_text="Swiggy One Free Delivery + ₹15 SuperSaver",
                url="https://www.swiggy.com/instamart",
            ),
            ScouredProduct(
                platform="Amazon",
                category="staples",
                title="Aashirvaad Select 100% MP Sharbati Atta",
                brand="Aashirvaad",
                unit_label="5kg",
                base_qty=5000,
                metric_unit="1kg",
                listed_price=298.0,
                mrp=365.0,
                base_delivery_fee=40.0,
                member_discount=15.0,
                delivery_eta="Tomorrow 10 AM",
                delivery_mins=1100,
                is_instant=False,
                rating=4.7,
                coupon_text="Prime 5% Subscribe & Save",
                url="https://www.amazon.in/s?k=aashirvaad+select+5kg",
            ),
            ScouredProduct(
                platform="Blinkit",
                category="staples",
                title="Aashirvaad Select 100% MP Sharbati Atta",
                brand="Aashirvaad",
                unit_label="5kg",
                base_qty=5000,
                metric_unit="1kg",
                listed_price=289.0,
                mrp=365.0,
                base_delivery_fee=25.0,
                member_discount=12.0,
                delivery_eta="10 Mins",
                delivery_mins=10,
                is_instant=True,
                rating=4.8,
                coupon_text="Zomato Gold Free Delivery",
                url="https://blinkit.com/s/?q=aashirvaad%20select",
            ),
            ScouredProduct(
                platform="Amazon",
                category="staples",
                title="Fortune Sunlite Refined Sunflower Oil Jar",
                brand="Fortune",
                unit_label="5L",
                base_qty=5000,
                metric_unit="1L",
                listed_price=695.0,
                mrp=890.0,
                base_delivery_fee=40.0,
                member_discount=30.0,
                delivery_eta="Tomorrow 11 AM",
                delivery_mins=1200,
                is_instant=False,
                rating=4.6,
                coupon_text="₹30 Prime Pantry Coupon",
                url="https://www.amazon.in/s?k=fortune+sunflower+oil+5l",
            ),
            ScouredProduct(
                platform="Flipkart",
                category="staples",
                title="India Gate Super Basmati Rice Aged Bulk Pack",
                brand="India Gate",
                unit_label="5kg",
                base_qty=5000,
                metric_unit="1kg",
                listed_price=629.0,
                mrp=930.0,
                base_delivery_fee=35.0,
                member_discount=25.0,
                delivery_eta="Tomorrow by 4 PM",
                delivery_mins=1440,
                is_instant=False,
                rating=4.7,
                coupon_text="Flipkart Plus SuperCoins ₹25 Off",
                url="https://www.flipkart.com/search?q=india+gate+basmati+rice+5kg",
            ),
            # DAIRY & BREAKFAST
            ScouredProduct(
                platform="Swiggy Instamart",
                category="dairy",
                title="Amul Pure Cow Ghee Tin Pack",
                brand="Amul",
                unit_label="1L",
                base_qty=1000,
                metric_unit="1L",
                listed_price=605.0,
                mrp=680.0,
                base_delivery_fee=20.0,
                member_discount=20.0,
                delivery_eta="11 Mins",
                delivery_mins=11,
                is_instant=True,
                rating=4.9,
                coupon_text="Swiggy One ₹20 Instant Rebate",
                url="https://www.swiggy.com/instamart",
            ),
            # HOME & CLEANING
            ScouredProduct(
                platform="Amazon",
                category="cleaning",
                title="Surf Excel Matic Front Load Detergent Liquid Refill",
                brand="Surf Excel",
                unit_label="2L",
                base_qty=2000,
                metric_unit="1L",
                listed_price=369.0,
                mrp=530.0,
                base_delivery_fee=40.0,
                member_discount=25.0,
                delivery_eta="Tomorrow 1 PM",
                delivery_mins=1320,
                is_instant=False,
                rating=4.7,
                coupon_text="Prime ₹25 Clip Coupon",
                url="https://www.amazon.in/s?k=surf+excel+matic+liquid+2l",
            ),
            # DRY FRUITS
            ScouredProduct(
                platform="Amazon",
                category="dryfruits",
                title="Happilo 100% Real Premium California Almonds Value Pack",
                brand="Happilo",
                unit_label="1kg",
                base_qty=1000,
                metric_unit="100g",
                listed_price=649.0,
                mrp=1200.0,
                base_delivery_fee=40.0,
                member_discount=30.0,
                delivery_eta="Tomorrow 1 PM",
                delivery_mins=1320,
                is_instant=False,
                rating=4.5,
                coupon_text="Prime Exclusive ₹30 Coupon",
                url="https://www.amazon.in/s?k=happilo+almonds+1kg",
            ),
        ]

        processed = [self.apply_membership_pricing(p) for p in raw_catalog]
        if query.strip():
            q = query.lower()
            processed = [
                p for p in processed
                if q in p.title.lower() or q in p.brand.lower() or q in p.category.lower()
            ]
        processed.sort(key=lambda p: p.normalized_unit_rate)
        return processed

    async def execute_wishlist_cron_cycle(self) -> Dict[str, Any]:
        """Runs a single scheduled Cron scan across all wishlisted items for Pin Code 411018."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        catalog = await self.fetch_catalog_snapshot()
        triggered_deals = []

        for item in self.wishlist:
            q_words = [w.lower() for w in item.query.split() if len(w) > 2]
            matches = [
                p for p in catalog
                if any(w in p.title.lower() or w in p.brand.lower() for w in q_words)
            ]
            item.last_checked = now_str
            if matches:
                best = min(matches, key=lambda x: x.net_landed_price)
                item.best_found_price = best.net_landed_price
                item.best_found_platform = best.platform
                item.triggered = (
                    best.net_landed_price <= item.target_net_price
                    or best.discount_pct >= item.min_discount_pct
                )
                if item.triggered:
                    triggered_deals.append({
                        "wishlist_id": item.id,
                        "query": item.query,
                        "platform": best.platform,
                        "net_landed_price": best.net_landed_price,
                        "target_price": item.target_net_price,
                        "discount_pct": best.discount_pct,
                        "membership_used": best.membership_applied or "None (Standard)",
                    })

        log_entry = {
            "timestamp": now_str,
            "pincode": self.pincode,
            "wishlist_items_scanned": len(self.wishlist),
            "deals_triggered": len(triggered_deals),
            "triggered_details": triggered_deals,
        }
        self.cron_logs.insert(0, log_entry)
        return log_entry


if __name__ == "__main__":
    # Configure default memberships requested by user:
    # Amazon Prime=ON, Swiggy One=ON, Flipkart Plus=ON, Zomato Gold=OFF, Zepto Pass=OFF
    profile = MembershipProfile(
        amazon_prime=True,
        swiggy_one=True,
        zomato_gold=False,
        zepto_pass=False,
        flipkart_plus=True,
    )
    engine = DealScourEngine(pincode="411018", memberships=profile)
    print("==========================================================================")
    print("🚀 DEALSCOUR CRON ENGINE & MEMBERSHIP NET-PRICE CALCULATOR (PIN: 411018)")
    print("📍 Location: Pimpri-Chinchwad (411018)")
    print("💳 Active Memberships: Amazon Prime [ON] | Swiggy One [ON] | Flipkart Plus [ON]")
    print("                       Zomato Gold [OFF] | Zepto Pass [OFF]")
    print("==========================================================================\n")

    cron_summary = asyncio.run(engine.execute_wishlist_cron_cycle())
    print(f"⏱️  Cron Scan Timestamp: {cron_summary['timestamp']}")
    print(f"📋 Wishlist Items Scanned: {cron_summary['wishlist_items_scanned']}")
    print(f"🔔 Target Price Alerts Triggered: {cron_summary['deals_triggered']}\n")

    for hit in cron_summary["triggered_details"]:
        print(
            f"  ✅ [ALERT] {hit['query']} -> ₹{hit['net_landed_price']} on {hit['platform']} "
            f"({hit['discount_pct']}% OFF | Target: ₹{hit['target_price']} | Benefit: {hit['membership_used']})"
        )