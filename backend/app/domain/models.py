from datetime import UTC, date, datetime

from sqlalchemy import Index, UniqueConstraint, text
from sqlmodel import Field, SQLModel


class Household(SQLModel, table=True):
    __tablename__ = "household"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    pincode: str = Field(min_length=6, max_length=6)


class ShoppingList(SQLModel, table=True):
    __tablename__ = "shopping_list"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id")
    name: str = Field(min_length=1, max_length=60)
    kind: str  # "quick" | "monthly" | "event"
    archived: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class Need(SQLModel, table=True):
    __tablename__ = "need"
    __table_args__ = (
        UniqueConstraint("list_id", "line_id", name="uq_need_list_line"),
    )

    id: int | None = Field(default=None, primary_key=True)
    list_id: int = Field(foreign_key="shopping_list.id", ondelete="CASCADE")
    line_id: str = Field(min_length=1, max_length=80)
    product_key: str | None = Field(default=None)
    family_key: str | None = Field(default=None)
    quantity: str | None = Field(default=None)
    qty: int = Field(default=1, ge=1, le=99)
    need_by_minutes: int | None = Field(default=None)
    lock_platform: str | None = Field(default=None)
    status: str = Field(default="open")  # "open" | "planned" | "bought" | "dropped"
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class Offer(SQLModel, table=True):
    __tablename__ = "offer"
    __table_args__ = (
        Index(
            "ix_offer_household_code_active",
            "household_id",
            "code",
            unique=True,
            sqlite_where=text("archived = 0"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id")
    code: str = Field(min_length=1, max_length=20)
    platform: str
    kind: str
    min_order_paise: int = Field(default=0)
    value_paise: int = Field(default=0)
    rate_bp: int = Field(default=0)
    cap_paise: int | None = Field(default=None)
    tiers_json: str = Field(default="[]")
    uses_left: int = Field(default=1)
    stack_group: str = Field(default="platform_coupon")
    value_type: str = Field(default="cash")
    multiplier_bp: int | None = Field(default=None)
    eligible_categories_json: str | None = Field(default=None)
    valid_to: date | None = Field(default=None)
    note: str | None = Field(default=None, max_length=200)
    archived: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class PlanRun(SQLModel, table=True):
    __tablename__ = "plan_run"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id")
    list_id: int | None = Field(default=None, foreign_key="shopping_list.id")
    request_json: str
    response_json: str
    accepted_label: str | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class Basket(SQLModel, table=True):
    __tablename__ = "basket"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id")
    plan_run_id: int = Field(foreign_key="plan_run.id")
    platform: str
    status: str = Field(default="ready")  # "ready" | "pending" | "placed" | "settled" | "released"
    target_offer_code: str | None = Field(default=None)
    threshold_paise: int | None = Field(default=None)
    shortfall_paise: int | None = Field(default=None)
    planned_net_paise: int
    offer_value_expected_paise: int = Field(default=0)
    offers_json: str = Field(default="[]")
    actual_paid_paise: int | None = Field(default=None)
    offer_value_received_paise: int | None = Field(default=None)
    placed_at: datetime | None = Field(default=None)
    settled_at: datetime | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class BasketLine(SQLModel, table=True):
    __tablename__ = "basket_line"

    id: int | None = Field(default=None, primary_key=True)
    basket_id: int = Field(foreign_key="basket.id", ondelete="CASCADE")
    need_id: int | None = Field(default=None, foreign_key="need.id")
    listing_id: str
    line_id: str
    title: str
    pack_label: str
    packs: int = Field(default=1)
    unit_price_paise: int
    line_total_paise: int
    is_filler: bool = Field(default=False)


class PriceObservation(SQLModel, table=True):
    __tablename__ = "price_observation"
    __table_args__ = (
        Index(
            "ix_price_observation_household_listing_observed",
            "household_id",
            "listing_id",
            "observed_at",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id")
    listing_id: str
    listed_paise: int
    mrp_paise: int
    member_price_paise: int | None = Field(default=None)
    in_stock: bool = Field(default=True)
    eta_minutes: int | None = Field(default=None)
    source: str = Field(default="manual")
    note: str | None = Field(default=None, max_length=120)
    observed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class AppUser(SQLModel, table=True):
    __tablename__ = "app_user"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    name: str | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class HouseholdMember(SQLModel, table=True):
    __tablename__ = "household_member"
    __table_args__ = (
        Index(
            "ix_household_member_unique_owner",
            "household_id",
            unique=True,
            sqlite_where=text("role = 'owner'"),
        ),
    )

    household_id: int = Field(foreign_key="household.id", primary_key=True)
    user_id: int = Field(foreign_key="app_user.id", primary_key=True)
    role: str = Field(...)  # "owner" | "member"


class LoginCode(SQLModel, table=True):
    __tablename__ = "login_code"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True)
    code_hash: str
    expires_at: datetime
    attempts: int = Field(default=0)
    used_at: datetime | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class AuthSession(SQLModel, table=True):
    __tablename__ = "auth_session"

    id: int | None = Field(default=None, primary_key=True)
    token_hash: str = Field(unique=True, index=True)
    user_id: int = Field(foreign_key="app_user.id", index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
    expires_at: datetime
    last_seen_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class Invite(SQLModel, table=True):
    __tablename__ = "invite"

    id: int | None = Field(default=None, primary_key=True)
    code_hash: str = Field(unique=True, index=True)
    household_id: int = Field(foreign_key="household.id", index=True)
    created_by: int = Field(foreign_key="app_user.id")
    expires_at: datetime
    used_by: int | None = Field(default=None, foreign_key="app_user.id")
    used_at: datetime | None = Field(default=None)


class CustomListing(SQLModel, table=True):
    __tablename__ = "custom_listing"
    __table_args__ = (
        Index(
            "ix_custom_listing_household_platform_sku_active",
            "household_id",
            "platform",
            "sku",
            unique=True,
            sqlite_where=text("archived = 0"),
        ),
        Index(
            "ix_custom_listing_household_product_key",
            "household_id",
            "product_key",
            unique=True,
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id")
    listing_id: str = Field(unique=True, index=True)
    platform: str
    sku: str
    url: str
    title: str = Field(min_length=1, max_length=120)
    brand: str = Field(min_length=1, max_length=40)
    pack_label: str
    category: str = Field(min_length=1, max_length=30)
    product_key: str = Field(min_length=1, max_length=60, index=True)
    family_key: str = Field(min_length=1, max_length=40, index=True)
    icon: str = Field(default="🛒")
    archived: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class SourceStatus(SQLModel, table=True):
    __tablename__ = "source_status"

    platform: str = Field(primary_key=True)
    consecutive_failures: int = Field(default=0)
    disabled_until: datetime | None = Field(default=None)
    last_success_at: datetime | None = Field(default=None)
    last_error: str | None = Field(default=None, max_length=200)


class ListingWatch(SQLModel, table=True):
    __tablename__ = "listing_watch"
    __table_args__ = (
        UniqueConstraint("household_id", "listing_id", name="uq_listing_watch_household_listing"),
    )

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id", index=True)
    listing_id: str = Field(index=True)
    target_paise: int | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class LlmUsage(SQLModel, table=True):
    __tablename__ = "llm_usage"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int | None = Field(default=None, foreign_key="household.id", index=True)
    provider: str = Field(default="gemini")
    model: str = Field(default="gemini-3.8-flash")
    prompt_tokens: int = Field(default=0)
    response_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    cost_paise: int = Field(default=0)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        index=True,
    )


class CatalogProduct(SQLModel, table=True):
    __tablename__ = "catalog_product"
    __table_args__ = (
        UniqueConstraint("household_id", "seed_product_id", name="uq_catalog_product_household_seed_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id", index=True)
    seed_product_id: str = Field(min_length=1, max_length=40, index=True)
    name: str = Field(min_length=1, max_length=160)
    brand: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=80)
    family_key: str = Field(min_length=1, max_length=40, index=True)
    pack_label: str = Field(min_length=1, max_length=20)
    target_pack_weight_g: int = Field(ge=1)
    suggestions_json: str = Field(default="[]")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class RadarChannel(SQLModel, table=True):
    __tablename__ = "radar_channel"
    __table_args__ = (
        UniqueConstraint("household_id", "peer_id", name="uq_radar_channel_household_peer"),
    )

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id", index=True)
    peer_id: str = Field(min_length=1, max_length=60, index=True)
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class RadarKeyword(SQLModel, table=True):
    __tablename__ = "radar_keyword"
    __table_args__ = (
        UniqueConstraint("household_id", "keyword", name="uq_radar_keyword_household_kw"),
    )

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id", index=True)
    keyword: str = Field(min_length=1, max_length=80)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )


class RadarPost(SQLModel, table=True):
    __tablename__ = "radar_post"
    __table_args__ = (
        UniqueConstraint(
            "household_id",
            "peer_id",
            "message_id",
            name="uq_radar_post_household_peer_msg",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id", index=True)
    peer_id: str = Field(min_length=1, max_length=60, index=True)
    message_id: str = Field(min_length=1, max_length=80)
    text: str = Field(max_length=2000)
    posted_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
    verdict: str = Field(default="pending", index=True)
    reasons_json: str = Field(default="[]")
    platform: str | None = Field(default=None)
    sku: str | None = Field(default=None)
    listing_id: str | None = Field(default=None)
    product_url: str | None = Field(default=None)
    title: str | None = Field(default=None)
    pack_label: str | None = Field(default=None)
    family_key: str | None = Field(default=None)
    posted_paise: int | None = Field(default=None)
    live_paise: int | None = Field(default=None)
    # pending -> done | too_old. Ingest only stores; app.radar.process fills in the verdict.
    status: str = Field(default="pending", index=True)
    pairs_json: str = Field(default="[]")  # parsed (price, link) pairs, resolved later
    page_fetches: int = Field(default=0)  # untracked page fetches this post used (daily budget)
    processed_at: datetime | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        index=True,
    )


class RadarAlert(SQLModel, table=True):
    __tablename__ = "radar_alert"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id", index=True)
    post_id: int | None = Field(default=None, foreign_key="radar_post.id")
    product_key: str = Field(index=True)
    platform: str
    sku: str
    title: str
    url: str
    price_paise: int
    reasons_json: str = Field(default="[]")
    telegram_status: str = Field(default="pending", index=True)
    scheduled_for: datetime | None = Field(default=None, index=True)
    sent_at: datetime | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        index=True,
    )


class RadarExtensionToken(SQLModel, table=True):
    __tablename__ = "radar_extension_token"

    id: int | None = Field(default=None, primary_key=True)
    household_id: int = Field(foreign_key="household.id", index=True)
    token_hash: str = Field(unique=True, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
    last_used_at: datetime | None = Field(default=None)
    revoked: bool = Field(default=False)





