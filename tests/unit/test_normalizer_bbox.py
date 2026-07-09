"""Unit tests for bbox classifier.

Critical: KZ and UA must be checked BEFORE RU (RU bbox swallows them).
"""

from parser_universal.normalizers.bbox import (
    detect_country,
    in_supported_region,
)


def test_by_inside():
    assert detect_country(53.9, 27.5) == "BY"


def test_ua_inside():
    # Lviv-ish
    assert detect_country(49.8, 24.0) == "UA"


def test_ru_inside_not_swallowing_ua():
    # Critically, a point clearly in UA must NOT be classified as RU.
    # Without proper ordering, the RU bbox (lat 41-82, lon 19-180) swallows it.
    assert detect_country(50.0, 30.0) == "UA"


def test_kz_inside_not_swallowing_ru():
    # Critically, a point in KZ must NOT be classified as RU.
    # Without proper ordering, RU bbox (lon 19-180) swallows it.
    assert detect_country(48.0, 60.0) == "KZ"


def test_unknown_outside_all():
    # Equator/Atlantic — outside every bbox.
    assert detect_country(0.0, 0.0) == "unknown"


def test_in_supported_region_true():
    assert in_supported_region(53.9, 27.5) is True


def test_in_supported_region_false():
    assert in_supported_region(0.0, 0.0) is False
