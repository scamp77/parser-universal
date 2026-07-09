"""Unit tests for enrichers/coords.py — OSM coord order quirks + GeoJSON parsing.

Critical rule (benz durable): `center` uses [LAT, LON], placemarks use
{'LON':..., 'LAT':...}. This module canonicalizes both to (lat, lon).

GeoJSON LineString uses [lon, lat] per RFC 7946.
"""

from parser_universal.enrichers.coords import (
    canonicalize_osm_coords,
    parse_geojson_linestring,
)


def test_center_dict_canonical():
    elem = {"center": {"lat": 50.5, "lon": 30.5}}
    assert canonicalize_osm_coords(elem) == (50.5, 30.5)


def test_flat_lat_lon_node():
    elem = {"lat": 49.8, "lon": 24.0}
    assert canonicalize_osm_coords(elem) == (49.8, 24.0)


def test_center_preferred_over_flat():
    """If BOTH `center` and `lat`/`lon` exist (way with out center), prefer center."""
    elem = {"center": {"lat": 50.5, "lon": 30.5}, "lat": 0.0, "lon": 0.0}
    assert canonicalize_osm_coords(elem) == (50.5, 30.5)


def test_no_coords_returns_none():
    assert canonicalize_osm_coords({}) is None
    assert canonicalize_osm_coords({"type": "way", "tags": {}}) is None


def test_invalid_lat_skipped():
    elem = {"center": {"lat": 200.0, "lon": 30.0}}
    # lat out of range → falls through to flat, also invalid.
    assert canonicalize_osm_coords(elem) is None


def test_partial_center_dict_falls_through():
    """If center dict is missing 'lat' or 'lon', try flat lat/lon."""
    elem = {"center": {"lat": 50.5}, "lon": 30.0}
    # flat is incomplete; but flat lat is missing too. Both fail.
    # Try: "lat" key top-level missing → keyerror on elem['lat'].
    assert canonicalize_osm_coords(elem) is None


def test_partial_center_dict_with_flat_fallback():
    elem = {"center": {"lat": 50.5}, "lat": 49.8, "lon": 24.0}
    # center incomplete → falls to flat → (49.8, 24.0)
    assert canonicalize_osm_coords(elem) == (49.8, 24.0)


# === GeoJSON parsing ===

def test_geojson_linestring_basic():
    # GeoJSON: coordinates = [[lon, lat], ...]
    coords = [[30.5, 50.5], [30.6, 50.6]]
    out = parse_geojson_linestring(coords)
    assert out == [(50.5, 30.5), (50.6, 30.6)]


def test_geojson_empty_returns_empty():
    assert parse_geojson_linestring([]) == []


def test_geojson_skips_out_of_range():
    coords = [[30.5, 50.5], [200.0, 30.0], [30.7, 50.7]]
    out = parse_geojson_linestring(coords)
    # First and third kept, middle dropped.
    assert len(out) == 2
    assert out[0] == (50.5, 30.5)
    assert out[1] == (50.7, 30.7)


def test_geojson_skips_malformed_tuples():
    coords = [[30.5, 50.5], "garbage", [30.7], [30.8, 50.8]]
    out = parse_geojson_linestring(coords)
    # [30.7] is len=1 → skipped; "garbage" skipped
    assert len(out) == 2


def test_classify_quality_bench_marks():
    """Mirror sup-app/app/importers/brouter.py:52."""
    from parser_universal.enrichers.brouter import classify_track_quality

    assert classify_track_quality(0) == "unknown"
    assert classify_track_quality(-5) == "unknown"
    assert classify_track_quality(2) == "placeholder"
    assert classify_track_quality(10) == "sparse"
    assert classify_track_quality(11) == "real"
    assert classify_track_quality(150) == "real"
