from dataclasses import FrozenInstanceError

import pytest

from app.pricing.units import Pack, default_basis, parse_pack, unit_rate


def test_parse_pack_valid() -> None:
    assert parse_pack("5kg") == Pack(5000, "g")
    assert parse_pack("5 Kg") == Pack(5000, "g")
    assert parse_pack("500g") == Pack(500, "g")
    assert parse_pack("500 gm") == Pack(500, "g")
    assert parse_pack("1.5kg") == Pack(1500, "g")
    assert parse_pack("1L") == Pack(1000, "ml")
    assert parse_pack("1 l") == Pack(1000, "ml")
    assert parse_pack("1 ltr") == Pack(1000, "ml")
    assert parse_pack("1 litre") == Pack(1000, "ml")
    assert parse_pack("750ml") == Pack(750, "ml")
    assert parse_pack("2 x 500g") == Pack(1000, "g")
    assert parse_pack("2x500g") == Pack(1000, "g")
    assert parse_pack("6 pcs") == Pack(6, "pc")
    assert parse_pack("6 pc") == Pack(6, "pc")
    assert parse_pack("pack of 6") == Pack(6, "pc")


def test_parse_pack_invalid() -> None:
    with pytest.raises(ValueError):
        parse_pack("")
    with pytest.raises(ValueError):
        parse_pack("   ")
    with pytest.raises(ValueError):
        parse_pack("big")
    with pytest.raises(ValueError):
        parse_pack("0kg")
    with pytest.raises(ValueError):
        parse_pack("-5kg")
    with pytest.raises(ValueError):
        parse_pack("0 pc")


def test_default_basis() -> None:
    assert default_basis("g") == (1000, "kg")
    assert default_basis("ml") == (1000, "L")
    assert default_basis("pc") == (1, "pc")


def test_unit_rate_calculations() -> None:
    assert unit_rate(28900, Pack(5000, "g")) == 5780
    assert unit_rate(61900, Pack(1000, "g"), 100) == 6190
    assert unit_rate(66500, Pack(5000, "ml")) == 13300


def test_unit_rate_rounding_half_up() -> None:
    assert unit_rate(1001, Pack(2000, "g")) == 501
    assert unit_rate(100, Pack(3, "pc")) == 33


def test_unit_rate_errors() -> None:
    with pytest.raises(TypeError):
        unit_rate(289.5, Pack(5000, "g"))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        unit_rate(1000, Pack(5000, "g"), basis_qty=0)
    with pytest.raises(ValueError):
        unit_rate(1000, Pack(5000, "g"), basis_qty=-10)


def test_pack_immutability() -> None:
    p = Pack(500, "g")
    with pytest.raises(FrozenInstanceError):
        p.qty = 600  # type: ignore[misc]
