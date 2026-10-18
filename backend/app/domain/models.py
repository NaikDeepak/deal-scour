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
