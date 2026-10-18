import pytest

from app.core.money import format_inr, pct_of, rupees


def test_rupees_valid() -> None:
    assert rupees("289") == 28900
    assert rupees("289.5") == 28950
    assert rupees("289.50") == 28950
    assert rupees(289) == 28900
    assert rupees("1,250") == 125000
    assert rupees("-50") == -5000
    assert rupees("0") == 0
    assert rupees(0) == 0


def test_rupees_invalid() -> None:
    with pytest.raises(TypeError):
        rupees(289.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        rupees(True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        rupees("1.234")
    with pytest.raises(ValueError):
        rupees("")
    with pytest.raises(ValueError):
        rupees("abc")
    with pytest.raises(ValueError):
        rupees("  ")


def test_format_inr_valid() -> None:
    assert format_inr(125000) == "₹1,250"
    assert format_inr(12500000) == "₹1,25,000"
    assert format_inr(1234567800) == "₹1,23,45,678"
    assert format_inr(28950) == "₹289.50"
    assert format_inr(5) == "₹0.05"
    assert format_inr(0) == "₹0"
    assert format_inr(-5000) == "-₹50"
    assert format_inr(-28950) == "-₹289.50"


def test_format_inr_invalid() -> None:
    with pytest.raises(TypeError):
        format_inr(289.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        format_inr(True)  # type: ignore[arg-type]


def test_pct_of_valid() -> None:
    assert pct_of(180000, 1000) == 18000
    assert pct_of(999, 1000) == 99
    assert pct_of(100000, 0) == 0
    assert pct_of(0, 1000) == 0
    # Negative paise floored towards zero
    assert pct_of(-180000, 1000) == -18000
    assert pct_of(-999, 1000) == -99


def test_pct_of_invalid() -> None:
    with pytest.raises(ValueError):
        pct_of(100, -1)
    with pytest.raises(TypeError):
        pct_of(100.0, 1000)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        pct_of(100, 10.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        pct_of(True, 1000)  # type: ignore[arg-type]
