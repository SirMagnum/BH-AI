"""
`canvas_rect_to_normalized` — the drag-to-block coordinate math, tested
as a pure function so it doesn't need a live Qt widget or a display.
"""

from __future__ import annotations

from bhai.ui.region_editor import canvas_rect_to_normalized


def test_normalizes_a_simple_rect() -> None:
    region = canvas_rect_to_normalized((100, 100, 200, 150), (400, 300))
    assert region.x == 0.25
    assert round(region.y, 6) == round(100 / 300, 6)
    assert round(region.w, 6) == round(100 / 400, 6)
    assert round(region.h, 6) == round(50 / 300, 6)


def test_handles_a_reversed_drag_direction() -> None:
    """Dragging from bottom-right to top-left must give the same region
    as the equivalent top-left-to-bottom-right drag."""
    forward = canvas_rect_to_normalized((50, 50, 150, 120), (400, 300))
    backward = canvas_rect_to_normalized((150, 120, 50, 50), (400, 300))
    assert forward == backward


def test_clamps_to_canvas_bounds() -> None:
    region = canvas_rect_to_normalized((-50, -50, 500, 500), (400, 300))
    assert region.x == 0.0
    assert region.y == 0.0
    assert region.w == 1.0
    assert region.h == 1.0


def test_zero_size_drag_yields_zero_area_region() -> None:
    region = canvas_rect_to_normalized((10, 10, 10, 10), (400, 300))
    assert region.w == 0.0
    assert region.h == 0.0
