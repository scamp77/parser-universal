"""Media geo extraction — EXIF GPS / QuickTime ISO 6709 (domain-independent).

Copy from benz `parsers_hybrid/_media_extract.py` (P3 of the extraction plan,
docs/EXTRACT_FROM_BENZ_2026-09-19.md). Pure-Python, no Pillow/piexif deps.
"""

from parser_universal.media.exif import (
    compute_confidence,
    extract_gps_from_jpeg,
    extract_gps_from_media,
    extract_gps_from_quicktime,
)

__all__ = [
    "compute_confidence",
    "extract_gps_from_jpeg",
    "extract_gps_from_media",
    "extract_gps_from_quicktime",
]
