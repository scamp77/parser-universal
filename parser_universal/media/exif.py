"""Media geo extraction — EXIF GPS from JPEG, QuickTime ISO 6709 from MP4/MOV.

Why: Telegram strips EXIF for "Send as Photo" but preserves bytes for "Send as
File" uploads. This module extracts GPS coordinates from those preserved
files. Pure-Python (no Pillow/piexif deps) to avoid the PR-grade decision of
adding image libraries to benz.

Activation: opt-in via ``BENZ_MEDIA_GEO_ENABLED=1`` env var in
``telethon_parser.py`` (off by default).

Returns dict shape::

    {
        'lat': float,
        'lon': float,
        'source': 'exif_gps' | 'quicktime_location',
        'datetime': datetime | None,   # capture time if available
        'confidence': 0.9 | 0.5,        # 0.9 if datetime matches posted_at ±24h, else 0.5
        'raw': dict,                    # raw EXIF/QuickTime dict for traceability
    }

DMS conversion: degrees + minutes/60 + seconds/3600; sign by reference char
(N/E/S/W). ISO 6709 QuickTime: ``+DD.DDDD-DD.DDDD/+DDD.DDDD-DD.DDDD/``.

Non-goals (intentional):
- Real-time ``target_incidents`` creation (cron-only via
  ``cron_fuel_reports_to_incidents.sh``).
- Backfill of historical ``fuel_reports.media_files`` (45h wall time, FloodWait risk).
- OCR on map images (separate ``_image_ocr.py`` PR3).
- URL extraction from captions (separate ``_map_url.py`` PR2).
"""
from __future__ import annotations

import struct
from datetime import datetime, timezone
from typing import Any

# JPEG markers
EXIF_HEADER = b"Exif\x00\x00"

# EXIF tag IDs we care about
GPS_IFD_TAG = 0x8825
TAG_EXIF_IFD = 0x8769
TAG_GPS_LATITUDE_REF = 0x0001
TAG_GPS_LATITUDE = 0x0002
TAG_GPS_LONGITUDE_REF = 0x0003
TAG_GPS_LONGITUDE = 0x0004
TAG_DATETIME_ORIGINAL = 0x9003

# Type sizes in bytes (per EXIF spec §4.6)
_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8, 11: 4, 12: 8}

# QuickTime atom types we look for
QT_LOCATION_ATOM = b"com.apple.quicktime.location.ISO"


def _rational(num_bytes: bytes, byte_order_mark: str) -> tuple[int, int]:
    """Parse 8 bytes as EXIF RATIONAL (num:4 + den:4) → (num, den)."""
    num, den = struct.unpack(byte_order_mark + "II", num_bytes)
    return num, den


def _dms_to_decimal(d_rat: bytes, m_rat: bytes, s_rat: bytes, ref: str, bom: str) -> float:
    """Three EXIF RATIONALs (DMS) + ref char → signed decimal degrees."""
    d_num, d_den = _rational(d_rat, bom)
    m_num, m_den = _rational(m_rat, bom)
    s_num, s_den = _rational(s_rat, bom)
    val = (d_num / d_den) + (m_num / m_den) / 60.0 + (s_num / s_den) / 3600.0
    if ref.upper() in ("S", "W"):
        val = -val
    return val


def _parse_exif_datetime(s: str | None) -> datetime | None:
    """EXIF DateTime: 'YYYY:MM:DD HH:MM:SS' (no timezone) → UTC."""
    if not s:
        return None
    s = s.strip("\x00 ").strip()
    if len(s) < 19:
        return None
    try:
        dt = datetime.strptime(s[:19], "%Y:%m:%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _read_ifd_entry(
    data: bytes, entry_offset: int, bom: str
) -> tuple[int, int, int, int, bytes]:
    """Read one IFD entry (12 bytes).

    Returns (tag, type_id, count, value_field_size, raw_value_bytes).
    raw_value_bytes is the inline value if it fits in 4 bytes, else the
    pointed-to payload (resolved relative to TIFF header start).
    """
    tag, type_id, count = struct.unpack(bom + "HHI", data[entry_offset : entry_offset + 8])
    type_size = _TYPE_SIZE.get(type_id, 0)
    total_size = type_size * count
    value_field = data[entry_offset + 8 : entry_offset + 12]
    if total_size <= 4:
        # value fits inline (e.g. ASCII <=4 chars)
        return tag, type_id, count, total_size, value_field[: max(total_size, 0)]
    (offset,) = struct.unpack(bom + "I", value_field)
    return tag, type_id, count, total_size, data[offset : offset + total_size]


def _parse_tiff_header(data: bytes) -> tuple[str, int] | None:
    """Identify byte order + IFD0 offset. Returns (bom, ifd0_offset) or None."""
    if len(data) < 8:
        return None
    bom_bytes = data[:2]
    if bom_bytes == b"II":
        bom = "<"
    elif bom_bytes == b"MM":
        bom = ">"
    else:
        return None
    magic = struct.unpack(bom + "H", data[2:4])[0]
    if magic != 0x002A:
        return None
    ifd0_offset = struct.unpack(bom + "I", data[4:8])[0]
    return bom, ifd0_offset


def _extract_gps_from_tiff(tiff_data: bytes) -> dict[str, Any] | None:
    """Parse TIFF body (from JPEG APP1) and extract GPS + DateTimeOriginal."""
    parsed = _parse_tiff_header(tiff_data)
    if parsed is None:
        return None
    bom, ifd0_offset = parsed

    if ifd0_offset + 2 > len(tiff_data):
        return None
    (num_entries,) = struct.unpack(bom + "H", tiff_data[ifd0_offset : ifd0_offset + 2])

    gps_offset = None
    exif_offset = None
    for i in range(num_entries):
        entry_offset = ifd0_offset + 2 + i * 12
        tag, _, _, _, _ = _read_ifd_entry(tiff_data, entry_offset, bom)
        if tag == GPS_IFD_TAG:
            gps_offset = struct.unpack(bom + "I", tiff_data[entry_offset + 8 : entry_offset + 12])[0]
        elif tag == TAG_EXIF_IFD:
            exif_offset = struct.unpack(bom + "I", tiff_data[entry_offset + 8 : entry_offset + 12])[0]
        if gps_offset is not None and exif_offset is not None:
            break

    if gps_offset is None or gps_offset >= len(tiff_data) or gps_offset + 2 > len(tiff_data):
        return None

# Parse GPS IFD
    (gps_num_entries,) = struct.unpack(bom + "H", tiff_data[gps_offset : gps_offset + 2])
    gps_entries_start = gps_offset + 2
    # Sanity check exif_offset points to valid IFD (must have at least 2 bytes for num_entries)
    if exif_offset is not None and (exif_offset + 2 > len(tiff_data) or exif_offset < gps_entries_start + gps_num_entries * 12):
        exif_offset = None
    lat_ref = b"N"
    lon_ref = b"E"
    for i in range(gps_num_entries):
        entry_offset = gps_entries_start + i * 12
        tag, type_id, count, _, raw = _read_ifd_entry(tiff_data, entry_offset, bom)
        if tag == TAG_GPS_LATITUDE and type_id == 5 and count == 3:
            lat_rats = raw  # 24 bytes: 3×RATIONAL
        elif tag == TAG_GPS_LONGITUDE and type_id == 5 and count == 3:
            lon_rats = raw
        elif tag == TAG_GPS_LATITUDE_REF and type_id == 2 and count >= 1:
            lat_ref = raw[:1]
        elif tag == TAG_GPS_LONGITUDE_REF and type_id == 2 and count >= 1:
            lon_ref = raw[:1]

    if lat_rats is None or lon_rats is None:
        return None

    try:
        lat = _dms_to_decimal(lat_rats[0:8], lat_rats[8:16], lat_rats[16:24], lat_ref.decode("ascii", errors="replace"), bom)
        lon = _dms_to_decimal(lon_rats[0:8], lon_rats[8:16], lon_rats[16:24], lon_ref.decode("ascii", errors="replace"), bom)
    except (struct.error, ValueError):
        return None

    # Parse EXIF IFD for DateTimeOriginal
    exif_dt_raw = None
    if exif_offset is not None and 0 < exif_offset < len(tiff_data) - 2 and exif_offset + 2 <= len(tiff_data):
        (exif_num_entries,) = struct.unpack(bom + "H", tiff_data[exif_offset : exif_offset + 2])
        exif_entries_start = exif_offset + 2
        for i in range(exif_num_entries):
            entry_offset = exif_entries_start + i * 12
            tag, type_id, count, _, raw = _read_ifd_entry(tiff_data, entry_offset, bom)
            if tag == TAG_DATETIME_ORIGINAL and type_id == 2 and count >= 1:
                exif_dt_raw = raw[:count].rstrip(b"\x00").decode("ascii", errors="replace")
                break

    return {
        "lat": lat,
        "lon": lon,
        "source": "exif_gps",
        "datetime": _parse_exif_datetime(exif_dt_raw),
        "datetime_raw": exif_dt_raw,
        "raw": {
            "lat_ref": lat_ref.decode("ascii", errors="replace"),
            "lon_ref": lon_ref.decode("ascii", errors="replace"),
            "byte_order": "LE" if bom == "<" else "BE",
        },
    }


def extract_gps_from_jpeg(data: bytes) -> dict[str, Any] | None:
    """Extract GPS coordinates from JPEG EXIF. Returns dict or None.

    Pure-Python JPEG APP1 reader. No Pillow/piexif dep. Handles both
    byte orders (II/MM). Returns None on malformed input or no GPS.
    """
    if len(data) < 4 or data[:2] != b"\xFF\xD8":
        return None

    i = 2
    while i < len(data) - 10:
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xD9:  # EOI
            return None
        if marker < 0xC0:  # markers without payload (RST, SOI, EOI, TEM)
            i += 2
            continue
        # Standalone markers (SOF, SOS, etc.) without length field
        if marker in (0xC0, 0xC4, 0xDA):
            # Not worth deep parsing — bail
            return None
        if marker != 0xE1:
            # Skip segment: marker(2) + length(2) + payload(length-2)
            seg_length = struct.unpack(">H", data[i + 2 : i + 4])[0]
            if seg_length < 2:
                return None
            i += 2 + seg_length
            continue
        # APP1 — check for EXIF header
        if data[i + 4 : i + 10] == EXIF_HEADER:
            seg_length = struct.unpack(">H", data[i + 2 : i + 4])[0]
            tiff_start = i + 10
            tiff_end = i + 2 + seg_length
            tiff_data = data[tiff_start:tiff_end]
            return _extract_gps_from_tiff(tiff_data)
        # APP1 but not EXIF (e.g. XMP) — skip
        seg_length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        if seg_length < 2:
            return None
        i += 2 + seg_length
    return None


def extract_gps_from_quicktime(data: bytes) -> dict[str, Any] | None:
    """Extract GPS from MP4/MOV QuickTime ``com.apple.quicktime.location.ISO`` atom.

    ISO 6709 format: ``+DD.DDDD-DD.DDDD/+DDD.DDDD-DD.DDDD/``
    (lat±lon±alt; sign char immediately after digit; trailing /).
    """
    if not data:
        return None
    idx = data.find(QT_LOCATION_ATOM)
    if idx < 0:
        return None
    iso_start = idx + len(QT_LOCATION_ATOM)
    end = data.find(b"/", iso_start)
    if end < 0 or end - iso_start > 64:
        return None
    s = data[iso_start:end].decode("ascii", errors="replace")
    return _parse_iso6709(s)


def _parse_iso6709(s: str) -> dict[str, Any] | None:
    """Parse ISO 6709 lat/lon string. Examples:
    '+49.2345+028.4567/'  → (49.2345, 28.4567)
    '+49.2345-028.4567/'  → (49.2345, -28.4567)
    '+49.2345+028.4567+150.0/' → with altitude (ignored here)

    Strategy: lat starts at position 0 with explicit sign. Lon starts at
    position N where the Nth char is +/- and the preceding char is a digit
    (so we don't match a sign embedded inside the lat digits). When altitude
    is present, the simplest correct split is the FIRST split where BOTH
    `lat_str` and the FIRST chunk of `lon_str` (before any further sign) parse
    as floats. Try all splits and pick the first that yields two valid floats.
    """
    s = s.rstrip("/").strip()
    if not s or s[0] not in "+-":
        return None

    candidates: list[tuple[float, float]] = []
    for i in range(1, len(s)):
        if s[i] in "+-" and s[i - 1].isdigit():
            lat_str = s[:i]
            lon_str = s[i:]
            # Try to parse lon_str as float directly (succeeds only when no altitude)
            try:
                lat = float(lat_str)
                lon = float(lon_str)
                candidates.append((lat, lon))
            except ValueError:
                pass
            # If altitude present, find the NEXT sign in lon_str and split
            for j in range(1, len(lon_str)):
                if lon_str[j] in "+-" and lon_str[j - 1].isdigit():
                    try:
                        lat = float(lat_str)
                        lon_only = float(lon_str[:j])
                        candidates.append((lat, lon_only))
                        break
                    except ValueError:
                        pass
            if candidates:
                lat, lon = candidates[0]
                return {
                    "lat": lat,
                    "lon": lon,
                    "source": "quicktime_location",
                    "datetime": None,
                    "datetime_raw": None,
                    "raw": {"iso6709": s},
                }
    return None


def extract_gps_from_media(data: bytes, mime: str) -> dict[str, Any] | None:
    """Dispatcher: pick the right extractor based on mime type.

    Supported:
        image/jpeg, image/jpg → EXIF GPS via JPEG APP1 reader
        video/mp4, video/quicktime, video/mov → QuickTime ISO 6709
    """
    if not data or not mime:
        return None
    mime = mime.lower().split(";")[0].strip()
    if mime in ("image/jpeg", "image/jpg"):
        return extract_gps_from_jpeg(data)
    if mime in ("video/mp4", "video/quicktime", "video/mov"):
        return extract_gps_from_quicktime(data)
    return None


def compute_confidence(
    media_geo: dict[str, Any] | None,
    posted_at: datetime | None,
    threshold_hours: int = 24,
) -> float:
    """Compute confidence score based on EXIF datetime vs posted_at.

    Returns 0.9 if both datetimes present and within threshold_hours, else 0.5.
    Returns 0.5 if either datetime is missing (repost risk).
    """
    if media_geo is None:
        return 0.0
    exif_dt = media_geo.get("datetime")
    if exif_dt is None or posted_at is None:
        return 0.5
    delta = abs((exif_dt - posted_at).total_seconds())
    if delta <= threshold_hours * 3600:
        return 0.9
    return 0.5


__all__ = [
    "extract_gps_from_jpeg",
    "extract_gps_from_quicktime",
    "extract_gps_from_media",
    "compute_confidence",
]