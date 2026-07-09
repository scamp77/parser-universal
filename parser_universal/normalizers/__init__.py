"""Normalizer protocol + bbox classifier (copy from sup-app parsers.py)."""

from parser_universal.normalizers.bbox import (
    SUPPORTED_BBOX,
    detect_country,
    in_supported_region,
)
from parser_universal.normalizers.coord_canonical import (
    RE_DECIMAL_PAIR,
    RE_DMS_PAIR,
    extract_coord_pairs,
    parse_url_to_coords,
    _dms_to_decimal,
)

__all__ = [
    "SUPPORTED_BBOX",
    "detect_country",
    "in_supported_region",
    "RE_DECIMAL_PAIR",
    "RE_DMS_PAIR",
    "extract_coord_pairs",
    "parse_url_to_coords",
    "_dms_to_decimal",
]
