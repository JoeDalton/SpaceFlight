"""
Unit tests for the generic UI items (space_flight.ui.utils): the rolling drum.
"""

import pytest
from panda3d.core import GeomVertexReader, NodePath

from space_flight.ui.utils import (
    GAUGE_TRACK_ALPHA,
    ArcGauge,
    ColumnGauge,
    RollingDrum,
    gauge_color,
    make_arc_geom,
)

ROLL_TIME_S = 0.2


class FakeClock:
    def __init__(self):
        self.time_s = 0.0

    def __call__(self) -> float:
        return self.time_s


def make_drum() -> RollingDrum:
    return RollingDrum(
        parent_node=NodePath("parent"), clock=FakeClock(), roll_time_s=ROLL_TIME_S
    )


def shown(drum: RollingDrum) -> dict:
    """The visible lines, by slot offset: (text, z, alpha, x scale, z scale)."""
    return {
        offset: (
            line.node().getText(),
            line.getZ(),
            line.getColorScale()[3],
            line.getScale()[0],
            line.getScale()[2],
        )
        for offset, line in drum.slots.items()
    }


def test_selection_faces_the_viewer_with_neighbours_above_and_below():
    """
    The selected item is centred, at full size and opacity; the previous item
    of the loop is above and the next one below, smaller, flatter and fainter.
    """
    drum = make_drum()

    drum.update(["A", "B", "C"], "A")

    lines = shown(drum)
    assert sorted(lines) == [-1, 0, 1]
    assert [lines[offset][0] for offset in (-1, 0, 1)] == ["C", "A", "B"]
    above, selected, below = lines[-1], lines[0], lines[1]
    assert above[1] > selected[1] > below[1]
    assert selected[2] == pytest.approx(1.0)
    for neighbour in (above, below):
        assert neighbour[2] < selected[2]  # fainter
        assert neighbour[3] < selected[3]  # smaller
        assert neighbour[4] / neighbour[3] < 1.0  # flattened


def test_labels_give_the_lines_text():
    """
    Items are shown through the label function.
    """
    drum = make_drum()

    drum.update([1, 2], 1, label=lambda item: f"item {item}")

    assert shown(drum)[0][0] == "item 1"


def test_two_items_show_the_other_above_and_below():
    """
    With two items, the other one is both the previous and the next.
    """
    drum = make_drum()

    drum.update(["A", "B"], "A")

    lines = shown(drum)
    assert lines[-1][0] == lines[1][0] == "B"


def test_a_single_item_is_shown_alone():
    """
    A single item has no neighbours to show.
    """
    drum = make_drum()

    drum.update(["A"], "A")

    assert sorted(shown(drum)) == [0]


@pytest.mark.parametrize("items, selected", [([], None), (["A", "B"], "Z")])
def test_nothing_is_shown_without_a_selected_item(items, selected):
    """
    Without items, or with a selection that is not one of them, the drum is
    empty.
    """
    drum = make_drum()
    drum.update(["A", "B"], "A")

    drum.update(items, selected)

    assert drum.slots == {}
    assert all(line.isHidden() for line in drum._lines)


@pytest.mark.parametrize("new_selection, start_side", [("B", "below"), ("C", "above")])
def test_drum_rolls_to_the_new_selection(new_selection, start_side):
    """
    Selecting the next item rolls the drum up: the new selection starts where
    it was shown (below) and settles facing the viewer; selecting the previous
    one rolls it down from above.
    """
    drum = make_drum()
    drum.update(["A", "B", "C"], "A")
    resting = shown(drum)
    was_at = 1 if start_side == "below" else -1

    drum.update(["A", "B", "C"], new_selection)

    assert shown(drum)[0][1] == pytest.approx(resting[was_at][1])
    drum.clock.time_s += ROLL_TIME_S
    drum.update(["A", "B", "C"], new_selection)
    settled = shown(drum)
    assert settled[0][1] == pytest.approx(resting[0][1])
    assert settled[0][2] == pytest.approx(1.0)


def test_drum_rolls_several_slots_the_shorter_way_round():
    """
    Skipping items rolls by as many slots, the shorter way round, showing every
    item in between on the way: here two slots forward out of five.
    """
    drum = make_drum()
    items = ["A", "B", "C", "D", "E"]
    drum.update(items, "A")
    resting = shown(drum)

    drum.update(items, "C")

    rolling = shown(drum)
    assert drum.roll_rad() == pytest.approx(2 * drum.slot_angle_rad)
    # The old selection is still where it was, facing the viewer
    assert rolling[-2][0] == "A"
    assert rolling[-2][1] == pytest.approx(resting[0][1])
    assert rolling[-1][0] == "B"


def test_drum_rests_without_rolling_when_the_items_change():
    """
    A different list of items is shown at rest, not rolled to.
    """
    drum = make_drum()
    drum.update(["A", "B", "C"], "A")

    drum.update(["X", "B", "C"], "B")

    assert drum.roll_rad() == pytest.approx(0.0)


def test_clean_removes_the_lines():
    """
    clean detaches the drum from its parent.
    """
    parent = NodePath("parent")
    drum = RollingDrum(parent_node=parent, clock=FakeClock())
    drum.update(["A", "B"], "A")

    drum.clean()

    assert parent.getNumChildren() == 0


# ---------------------------
# Gauges
# ---------------------------


def make_arc_gauge(n_segments: int = 10) -> ArcGauge:
    return ArcGauge(
        parent_node=NodePath("corner"),
        name="gauge",
        color=(0.2, 1.0, 0.4),
        radius=1.0,
        thickness=0.2,
        n_segments=n_segments,
        text_scale=0.05,
    )


def test_gauge_color_scales_and_clips_brightness():
    """
    Brightness scales the RGB components, clipped to 1, and leaves alpha alone.
    """
    assert gauge_color((0.2, 1.0, 0.4), 2.0, 0.5) == pytest.approx((0.4, 1.0, 0.8, 0.5))


def test_arc_geom_sweeps_from_the_left_over_the_top():
    """
    A half-ring's first vertices are at its left end; a half-filled one ends at
    its top.
    """
    geom = make_arc_geom(inner_radius=0.8, outer_radius=1.0, n_steps=2, n_segments=4)
    reader = GeomVertexReader(geom.getVertexData(), "vertex")
    vertices = []
    while not reader.isAtEnd():
        vertices.append(tuple(reader.getData3()))
    assert len(vertices) == 6
    # Outer then inner vertex of each step: left end, 45°, top
    assert vertices[0] == pytest.approx((-1.0, 0.0, 0.0), abs=1e-6)
    assert vertices[1] == pytest.approx((-0.8, 0.0, 0.0), abs=1e-6)
    assert vertices[4] == pytest.approx((0.0, 0.0, 1.0), abs=1e-6)


@pytest.mark.parametrize(
    "level, steps", [(0.0, 0), (0.01, 1), (0.5, 5), (1.0, 10), (1.5, 10), (-1.0, 0)]
)
def test_arc_gauge_fill_is_quantised_to_its_segments(level, steps):
    """
    The fill covers the level's share of the segments; a non-empty level shows
    at least one.
    """
    gauge = make_arc_gauge(n_segments=10)
    gauge.set_level(level)
    assert gauge.fill_steps == steps
    assert gauge.fill.node().getNumGeoms() == (1 if steps else 0)


def test_arc_gauge_only_rebuilds_its_fill_when_the_level_step_changes():
    """
    A level change within the same segment keeps the fill geometry.
    """
    gauge = make_arc_gauge(n_segments=10)
    gauge.set_level(0.5)
    geom = gauge.fill.node().getGeom(0)
    gauge.set_level(0.52)
    assert gauge.fill.node().getGeom(0) == geom


def test_arc_gauge_text_and_brightness():
    """
    The gauge shows its text, and brightness scales both fill and track.
    """
    gauge = make_arc_gauge()
    gauge.set_text("123")
    gauge.set_brightness(0.5)
    assert gauge.text.node().getText() == "123"
    # Node colours are stored with 8 bits per component
    assert tuple(gauge.fill.getColor()) == pytest.approx(
        (0.1, 0.5, 0.2, 1.0), abs=1 / 255
    )
    assert gauge.track.getColor()[3] == pytest.approx(GAUGE_TRACK_ALPHA, abs=1 / 255)


def test_column_gauge_fill_scales_with_level_and_hides_when_empty():
    """
    The column's fill rises with the level, and is hidden when empty.
    """
    gauge = ColumnGauge(
        parent_node=NodePath("corner"),
        name="column",
        color=(1.0, 0.0, 0.0),
        width=0.1,
        height=2.0,
    )
    gauge.set_level(0.25)
    assert gauge.fill.getSz() == pytest.approx(0.5)
    assert not gauge.fill.isHidden()

    gauge.set_level(0.0)
    assert gauge.fill.isHidden()


def test_gauges_clean_removes_their_nodes():
    """
    Cleaning a gauge detaches its nodes.
    """
    corner = NodePath("corner")
    gauge = ArcGauge(
        parent_node=corner,
        name="gauge",
        color=(1.0, 1.0, 1.0),
        radius=1.0,
        thickness=0.2,
        n_segments=4,
        text_scale=0.05,
    )
    gauge.clean()
    assert corner.getNumChildren() == 0
