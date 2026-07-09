"""Unit tests for coordinate parsing (DMS + decimal + URL dispatch)."""

import pytest

from parser_universal.normalizers.coord_canonical import (
    RE_DECIMAL_PAIR,
    extract_coord_pairs,
    parse_url_to_coords,
    _dms_to_decimal,
)


def test_decimal_pair_basic():
    text = "55.7558, 37.6173"
    pairs = extract_coord_pairs(text)
    assert len(pairs) == 1
    assert pairs[0] == (pytest.approx(55.7558), pytest.approx(37.6173))


def test_dms_pair():
    # 55°07'23.4"N 37°39'15.6"E
    text = '55\u00b007\'23.4"N 37\u00b039\'15.6"E'
    pairs = extract_coord_pairs(text)
    assert len(pairs) == 1
    lat, lon = pairs[0]
    assert 55.0 < lat < 56.0
    assert 37.0 < lon < 38.0


def test_dms_southern_hemisphere_flips():
    # 33°55'44.0"S → negative decimal
    val = _dms_to_decimal("33", "55", "44.0", "S")
    assert val < 0
    assert -34.0 < val < -33.0


def test_dedup_consecutive_pairs():
    text = "55.7558, 37.6173 55.7558, 37.6173 55.7700, 37.6500"
    pairs = extract_coord_pairs(text)
    # Should be 2 unique pairs, not 3.
    assert len(pairs) == 2


def test_invalid_decimal_skipped():
    # lat > 90 → skip
    text = "200.000, 37.6173"
    pairs = extract_coord_pairs(text)
    assert len(pairs) == 0


def test_regex_match_unit_test_smoke():
    m = RE_DECIMAL_PAIR.search("55.7558, 37.6173")
    assert m is not None


# === URL dispatch ===

def test_yandex_lon_lat_order():
    # Yandex uses lon,lat → must be flipped to (lat, lon) on output
    url = "https://yandex.ru/maps/?ll=37.6173,55.7558"
    pts = parse_url_to_coords(url)
    assert pts == [(pytest.approx(55.7558), pytest.approx(37.6173))]


def test_google_lat_lon_order():
    url = "https://maps.google.com/?q=55.7558,37.6173"
    pts = parse_url_to_coords(url)
    assert pts == [(pytest.approx(55.7558), pytest.approx(37.6173))]


def test_google_at_path():
    url = "https://www.google.com/maps/@55.7558,37.6173,15z"
    pts = parse_url_to_coords(url)
    assert pts == [(pytest.approx(55.7558), pytest.approx(37.6173))]


def test_osm_mlat_mlon():
    url = "https://www.openstreetmap.org/?mlat=55.7558&mlon=37.6173"
    pts = parse_url_to_coords(url)
    assert pts == [(pytest.approx(55.7558), pytest.approx(37.6173))]


def test_brouter_lon_lat_order():
    url = "https://brouter.de/brouter/#lonlats=27.5,53.9;27.6,53.8&profile=river"
    pts = parse_url_to_coords(url)
    assert len(pts) == 2
    assert pts[0] == (pytest.approx(53.9), pytest.approx(27.5))
    assert pts[1] == (pytest.approx(53.8), pytest.approx(27.6))


def test_unknown_url_returns_empty():
    url = "https://example.com/some/path"
    assert parse_url_to_coords(url) == []
