"""Tests for parsers_hybrid/_media_extract.py — pure-Python EXIF/QuickTime GPS extractor.

Activation: opt-in via BENZ_MEDIA_GEO_ENABLED=1 in telethon_parser.py.
These tests cover synthetic JPEG + MP4 fixtures built inline (no real Telegram data).
"""
from __future__ import annotations

import struct
from datetime import datetime, timezone


from parser_universal.media.exif import (
    _parse_iso6709,
    compute_confidence,
    extract_gps_from_jpeg,
    extract_gps_from_media,
    extract_gps_from_quicktime,
)


# ── JPEG EXIF fixture builders ────────────────────────────────────────────────

def _build_jpeg_with_exif_gps(
    lat_deg: int = 50,
    lat_min: int = 27,
    lat_sec_num: int = 0,
    lat_sec_den: int = 1,
    lat_ref: bytes = b"N",
    lon_deg: int = 30,
    lon_min: int = 0,
    lon_sec_num: int = 0,
    lon_sec_den: int = 1,
    lon_ref: bytes = b"E",
    byte_order: str = "<",
    datetime_str: str | None = "2026:07:27 12:00:00",
) -> bytes:
    """Build synthetic JPEG with valid EXIF GPS IFD."""
    bom = byte_order
    ifd0_num = 2 if datetime_str else 1
    has_exif = datetime_str is not None
    gps_ifd_offset = 8 + 2 + ifd0_num * 12 + 4
    exif_ifd_offset = gps_ifd_offset + 2 + 4 * 12
    exif_ifd_size = (2 + 1 * 12) if has_exif else 0
    data_offset = exif_ifd_offset + exif_ifd_size
    lat_data_offset = data_offset
    lon_data_offset = data_offset + 24
    dt_data_offset = lon_data_offset + 24

    tiff = bytearray()
    bom_bytes = b"II" if bom == "<" else b"MM"
    tiff += bom_bytes + struct.pack(bom + "H", 0x002A) + struct.pack(bom + "I", 8)

    # IFD0
    tiff += struct.pack(bom + "H", ifd0_num)
    tiff += struct.pack(bom + "HHI", 0x8825, 4, 1) + struct.pack(bom + "I", gps_ifd_offset)
    if has_exif:
        tiff += struct.pack(bom + "HHI", 0x8769, 4, 1) + struct.pack(bom + "I", exif_ifd_offset)
    tiff += struct.pack(bom + "I", 0)

    # GPS IFD
    tiff += struct.pack(bom + "H", 4)
    tiff += struct.pack(bom + "HHI", 0x0001, 2, 1) + (lat_ref + b"\x00\x00\x00")[:4]
    tiff += struct.pack(bom + "HHI", 0x0002, 5, 3) + struct.pack(bom + "I", lat_data_offset)
    tiff += struct.pack(bom + "HHI", 0x0003, 2, 1) + (lon_ref + b"\x00\x00\x00")[:4]
    tiff += struct.pack(bom + "HHI", 0x0004, 5, 3) + struct.pack(bom + "I", lon_data_offset)

    # EXIF IFD
    if has_exif:
        tiff += struct.pack(bom + "H", 1)
        tiff += struct.pack(bom + "HHI", 0x9003, 2, len(datetime_str) + 1) + struct.pack(bom + "I", dt_data_offset)

    # Data
    tiff += struct.pack(bom + "IIIIII", lat_deg, 1, lat_min, 1, lat_sec_num, lat_sec_den)
    tiff += struct.pack(bom + "IIIIII", lon_deg, 1, lon_min, 1, lon_sec_num, lon_sec_den)
    if has_exif:
        tiff += datetime_str.encode("ascii") + b"\x00"

    # Wrap in JPEG
    jpeg = bytearray()
    jpeg += b"\xff\xd8"
    app1_payload = b"Exif\x00\x00" + bytes(tiff)
    app1_length = 2 + len(app1_payload)
    jpeg += b"\xff\xe1" + struct.pack(">H", app1_length) + app1_payload
    jpeg += b"\xff\xd9"
    return bytes(jpeg)


def _build_jpeg_without_exif() -> bytes:
    """JPEG with SOI + EOI only (no APP1/EXIF)."""
    return b"\xff\xd8\xff\xd9"


def _build_jpeg_with_xmp() -> bytes:
    """JPEG with APP1 but XMP instead of EXIF."""
    jpeg = bytearray(b"\xff\xd8")
    xmp_payload = b"http://ns.adobe.com/xap/1.0/"
    app1_length = 2 + len(xmp_payload)
    jpeg += b"\xff\xe1" + struct.pack(">H", app1_length) + xmp_payload
    jpeg += b"\xff\xd9"
    return bytes(jpeg)


# ── Tests: extract_gps_from_jpeg ──────────────────────────────────────────────

def test_jpeg_with_exif_kyiv_coordinates():
    """Kyiv 50°27'0\" N, 30°00'0\" E → lat=50.45, lon=30.0."""
    jpeg = _build_jpeg_with_exif_gps()
    result = extract_gps_from_jpeg(jpeg)
    assert result is not None
    assert abs(result["lat"] - 50.45) < 0.001
    assert abs(result["lon"] - 30.0) < 0.001
    assert result["source"] == "exif_gps"
    assert result["datetime"] == datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
    assert result["raw"]["lat_ref"] == "N"
    assert result["raw"]["lon_ref"] == "E"
    assert result["raw"]["byte_order"] == "LE"


def test_jpeg_with_exif_southern_hemisphere():
    """S/-S hemisphere yields negative latitude."""
    jpeg = _build_jpeg_with_exif_gps(lat_deg=33, lat_min=52, lat_ref=b"S")
    result = extract_gps_from_jpeg(jpeg)
    assert result is not None
    assert result["lat"] < 0  # south is negative
    assert abs(result["lat"] - (-33 - 52 / 60.0)) < 0.001


def test_jpeg_with_exif_western_hemisphere():
    """W/-W hemisphere yields negative longitude."""
    jpeg = _build_jpeg_with_exif_gps(lon_deg=97, lon_min=30, lon_ref=b"W")
    result = extract_gps_from_jpeg(jpeg)
    assert result is not None
    assert result["lon"] < 0
    assert abs(result["lon"] - (-97 - 30 / 60.0)) < 0.001


def test_jpeg_with_exif_big_endian():
    """MM byte order (big-endian) is also supported."""
    jpeg = _build_jpeg_with_exif_gps(byte_order=">")
    result = extract_gps_from_jpeg(jpeg)
    assert result is not None
    assert abs(result["lat"] - 50.45) < 0.001
    assert result["raw"]["byte_order"] == "BE"


def test_jpeg_with_exif_no_datetime():
    """Missing DateTimeOriginal → datetime is None."""
    jpeg = _build_jpeg_with_exif_gps(datetime_str=None)
    result = extract_gps_from_jpeg(jpeg)
    assert result is not None
    assert result["datetime"] is None


def test_jpeg_without_exif_returns_none():
    jpeg = _build_jpeg_without_exif()
    assert extract_gps_from_jpeg(jpeg) is None


def test_jpeg_with_xmp_not_exif_returns_none():
    jpeg = _build_jpeg_with_xmp()
    assert extract_gps_from_jpeg(jpeg) is None


def test_non_jpeg_returns_none():
    """ZIP magic bytes — not a JPEG, must return None."""
    assert extract_gps_from_jpeg(b"PK\x03\x04" + b"\x00" * 100) is None


def test_jpeg_truncated_returns_none():
    """Truncated JPEG (less than 4 bytes) returns None."""
    assert extract_gps_from_jpeg(b"\xff\xd8") is None


def test_jpeg_with_corrupt_exif_returns_none():
    """APP1 with EXIF header but corrupt TIFF body returns None (no raise)."""
    jpeg = bytearray(b"\xff\xd8")
    bad_app1 = b"Exif\x00\x00" + b"corrupt" * 10
    jpeg += b"\xff\xe1" + struct.pack(">H", 2 + len(bad_app1)) + bad_app1
    jpeg += b"\xff\xd9"
    assert extract_gps_from_jpeg(bytes(jpeg)) is None


# ── Tests: extract_gps_from_quicktime ─────────────────────────────────────────

def test_quicktime_iso6709_positive_lon():
    mp4 = b"\x00" * 32 + b"com.apple.quicktime.location.ISO+49.2345+028.4567/"
    result = extract_gps_from_quicktime(mp4)
    assert result is not None
    assert abs(result["lat"] - 49.2345) < 0.0001
    assert abs(result["lon"] - 28.4567) < 0.0001
    assert result["source"] == "quicktime_location"
    assert result["datetime"] is None


def test_quicktime_iso6709_negative_lon():
    result = _parse_iso6709("+49.2345-028.4567/")
    assert result is not None
    assert result["lon"] == -28.4567


def test_quicktime_iso6709_negative_lat():
    result = _parse_iso6709("-33.8688+151.2093/")
    assert result is not None
    assert result["lat"] == -33.8688
    assert result["lon"] == 151.2093


def test_quicktime_iso6709_with_altitude():
    """ISO 6709 may include altitude (3 components)."""
    result = _parse_iso6709("+49.2345+028.4567+150.0/")
    assert result is not None
    assert result["lat"] == 49.2345
    assert result["lon"] == 28.4567


def test_quicktime_missing_atom_returns_none():
    """No com.apple.quicktime.location.ISO atom → None."""
    mp4 = b"\x00" * 1000 + b"some_other_atom"
    assert extract_gps_from_quicktime(mp4) is None


def test_quicktime_empty_returns_none():
    assert extract_gps_from_quicktime(b"") is None


def test_iso6709_no_sign_returns_none():
    """ISO 6709 requires leading sign on lat. No sign → None."""
    assert _parse_iso6709("49.2345+028.4567/") is None


# ── Tests: extract_gps_from_media (dispatcher) ───────────────────────────────

def test_dispatcher_jpeg():
    jpeg = _build_jpeg_with_exif_gps()
    assert extract_gps_from_media(jpeg, "image/jpeg") is not None
    assert extract_gps_from_media(jpeg, "image/jpg") is not None


def test_dispatcher_mp4():
    mp4 = b"\x00" * 32 + b"com.apple.quicktime.location.ISO+49.0+028.0/"
    assert extract_gps_from_media(mp4, "video/mp4") is not None
    assert extract_gps_from_media(mp4, "video/quicktime") is not None
    assert extract_gps_from_media(mp4, "video/mov") is not None


def test_dispatcher_unsupported_mime():
    jpeg = _build_jpeg_with_exif_gps()
    assert extract_gps_from_media(jpeg, "image/png") is None
    assert extract_gps_from_media(jpeg, "text/plain") is None
    assert extract_gps_from_media(jpeg, "") is None


def test_dispatcher_mime_with_charset():
    """image/jpeg; charset=utf-8 should still match."""
    jpeg = _build_jpeg_with_exif_gps()
    assert extract_gps_from_media(jpeg, "image/jpeg; charset=utf-8") is not None


def test_dispatcher_empty_data():
    assert extract_gps_from_media(b"", "image/jpeg") is None
    assert extract_gps_from_media(b"", "video/mp4") is None


# ── Tests: compute_confidence ────────────────────────────────────────────────

def test_confidence_within_24h_returns_high():
    posted = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
    media_geo = {"datetime": datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)}
    assert compute_confidence(media_geo, posted) == 0.9


def test_confidence_within_threshold_12h():
    posted = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
    media_geo = {"datetime": datetime(2026, 7, 27, 18, 0, 0, tzinfo=timezone.utc)}
    assert compute_confidence(media_geo, posted) == 0.9


def test_confidence_outside_24h_returns_low():
    posted = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
    media_geo = {"datetime": datetime(2020, 1, 1, tzinfo=timezone.utc)}
    assert compute_confidence(media_geo, posted) == 0.5


def test_confidence_missing_exif_dt_returns_low():
    posted = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
    assert compute_confidence({"datetime": None}, posted) == 0.5


def test_confidence_missing_posted_at_returns_low():
    media_geo = {"datetime": datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)}
    assert compute_confidence(media_geo, None) == 0.5


def test_confidence_none_media_returns_zero():
    assert compute_confidence(None, None) == 0.0


def test_confidence_threshold_configurable():
    """threshold_hours param allows tighter/wider window."""
    posted = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
    media_geo = {"datetime": datetime(2026, 7, 27, 13, 30, 0, tzinfo=timezone.utc)}
    # Default 24h → within threshold → 0.9
    assert compute_confidence(media_geo, posted) == 0.9
    # Threshold 1h → outside → 0.5
    assert compute_confidence(media_geo, posted, threshold_hours=1) == 0.5