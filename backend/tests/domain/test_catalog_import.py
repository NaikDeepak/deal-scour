import json
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.domain.catalog_import import import_catalog_csv
from app.domain.models import CatalogProduct, Household
from app.jobs.import_catalog import run_import_cli

SAMPLE_CSV = Path(__file__).parent.parent / "fixtures" / "catalog_sample.csv"


@pytest.fixture
def mem_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Household(id=1, name="Home", pincode="411018"))
        s.commit()
        yield s


# Case 1 & Case 3: Import catalog_sample.csv -> 3 products created, name has no "(target ...)",
# pack 600g/1kg, family from rules (toor_dal, almonds) or category slug (dal_pulses).
# Direct-product-URL row becomes a suggestion; search-URL row doesn't.
def test_case_1_and_3_import_catalog_sample_csv(mem_session: Session) -> None:
    report = import_catalog_csv(mem_session, household_id=1, csv_path=SAMPLE_CSV)
    assert report.created == 3
    assert report.updated == 0
    assert report.skipped == []

    rows = mem_session.exec(
        select(CatalogProduct)
        .where(CatalogProduct.household_id == 1)
        .order_by(CatalogProduct.seed_product_id)
    ).all()
    assert len(rows) == 3

    by_seed = {r.seed_product_id: r for r in rows}

    dal = by_seed["DS-0001"]
    assert dal.name == "Tata Sampann Toor/Arhar Dal"
    assert "(target" not in dal.name
    assert dal.brand == "Tata Sampann"
    assert dal.category == "Dal & Pulses"
    assert dal.pack_label == "600g"
    assert dal.target_pack_weight_g == 600
    assert dal.family_key == "toor_dal"
    dal_suggestions = json.loads(dal.suggestions_json)
    assert len(dal_suggestions) == 1
    assert dal_suggestions[0] == {
        "platform": "blinkit",
        "sku": "551910",
        "url": "https://blinkit.com/prn/tata-sampann-unpolished-toor-dal/prid/551910",
    }

    almonds = by_seed["DF-0001"]
    assert almonds.name == "Happilo California Almonds"
    assert "(target" not in almonds.name
    assert almonds.brand == "Happilo"
    assert almonds.category == "Almonds"
    assert almonds.pack_label == "1kg"
    assert almonds.target_pack_weight_g == 1000
    assert almonds.family_key == "almonds"
    assert json.loads(almonds.suggestions_json) == []

    kulthi = by_seed["DS-0050"]
    assert kulthi.name == "Organic Tattva Kulthi Horse Gram"
    assert "(target" not in kulthi.name
    assert kulthi.pack_label == "600g"
    assert kulthi.family_key == "dal_pulses"
    assert json.loads(kulthi.suggestions_json) == []


# Case 2: Re-import -> 0 created, 3 updated.
# A row with an empty name or a 300-char name -> skipped with a reason; the others still import.
def test_case_2_reimport_upsert_and_skip_invalid_rows(mem_session: Session, tmp_path: Path) -> None:
    first = import_catalog_csv(mem_session, household_id=1, csv_path=SAMPLE_CSV)
    assert first.created == 3
    assert first.updated == 0

    second = import_catalog_csv(mem_session, household_id=1, csv_path=SAMPLE_CSV)
    assert second.created == 0
    assert second.updated == 3
    assert second.skipped == []

    # Build a CSV with valid rows plus an empty-name product and a 300-char-name product
    long_name = "A" * 300
    mixed_csv = tmp_path / "mixed.csv"
    sample_text = SAMPLE_CSV.read_text(encoding="utf-8")
    extra_rows = (
        "BAD-EMPTY,,SomeBrand,Dal & Pulses,500,Blinkit,"
        "https://blinkit.com/s/?q=x,Search URL (discovery),,500,411018,note\n"
        f"BAD-LONG,{long_name},SomeBrand,Dal & Pulses,500,Blinkit,"
        "https://blinkit.com/s/?q=x,Search URL (discovery),,500,411018,note\n"
    )
    mixed_csv.write_text(sample_text + extra_rows, encoding="utf-8")

    third = import_catalog_csv(mem_session, household_id=1, csv_path=mixed_csv)
    assert third.created == 0
    assert third.updated == 3
    assert len(third.skipped) == 2
    skipped_ids = {s.seed_product_id for s in third.skipped}
    assert skipped_ids == {"BAD-EMPTY", "BAD-LONG"}
    assert all(s.reason for s in third.skipped)


def test_import_catalog_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = tmp_path / "cli_test.db"
    engine = create_engine(f"sqlite:///{db_file}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Household(id=1, name="Home", pincode="411018"))
        s.commit()

    monkeypatch.setattr("app.jobs.import_catalog.get_engine", lambda: engine)
    report = run_import_cli([str(SAMPLE_CSV), "--household", "1"])
    assert report.created == 3
    assert report.updated == 0
    engine.dispose()


# The real CSVs are saved with a UTF-8 byte-order mark; the first header must still be read.
def test_import_csv_with_byte_order_mark(mem_session: Session, tmp_path: Path) -> None:
    bom_csv = tmp_path / "bom.csv"
    bom_csv.write_bytes(b"\xef\xbb\xbf" + SAMPLE_CSV.read_bytes().lstrip(b"\xef\xbb\xbf"))
    report = import_catalog_csv(mem_session, household_id=1, csv_path=bom_csv)
    assert report.created == 3
    assert report.skipped == []
