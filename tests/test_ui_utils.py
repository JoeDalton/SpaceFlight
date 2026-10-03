"""
Unit tests for the generic UI items (space_flight.ui.utils): the rolling drum.
"""

import pytest
from panda3d.core import NodePath

from space_flight.ui.utils import RollingDrum

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
