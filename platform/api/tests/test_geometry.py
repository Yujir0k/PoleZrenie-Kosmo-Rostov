import pytest

from app.services import validate_geometry


def test_valid_polygon_returns_area() -> None:
    geometry = {"type":"Polygon","coordinates":[[[39.70,47.30],[39.71,47.30],[39.71,47.31],[39.70,47.31],[39.70,47.30]]]}
    assert 70 < validate_geometry(geometry) < 90


def test_self_intersection_is_rejected() -> None:
    geometry = {"type":"Polygon","coordinates":[[[39.70,47.30],[39.71,47.31],[39.71,47.30],[39.70,47.31],[39.70,47.30]]]}
    with pytest.raises(ValueError, match="самопересечения"):
        validate_geometry(geometry)

