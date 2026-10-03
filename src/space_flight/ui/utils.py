"""
Generic on-screen UI items.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

import numpy as np
from panda3d.core import NodePath, TextNode, TransparencyAttrib

# Height of a line's glyph centre above its baseline, in text scale units
TEXT_CENTER_OFFSET = 0.35


def make_text_line(
    parent_node: NodePath, name: str, align: int = TextNode.ARight
) -> NodePath:
    """
    A HUD-style line of text: small caps with a drop shadow, fadable.

    :param parent_node: The node to attach the line to
    :param name: The text node's name
    :param align: Its alignment (a TextNode alignment constant)
    :return: The line's node path; set its text with ``line.node().setText``
    """
    text = TextNode(name)
    text.setSmallCaps(True)
    text.setShadow(0.05, 0.05)
    text.setShadowColor(0, 0, 0, 1)
    text.setAlign(align)
    line = parent_node.attachNewNode(text)
    line.setTransparency(TransparencyAttrib.MAlpha)
    return line


class RollingDrum:
    """
    A looping list of text lines written round a drum: a cylinder seen from the
    side, its axis horizontal.

    The selected item faces the viewer, centred on the drum's root node. The
    others follow it round the drum, in list order below it and in reverse
    order above (the list loops), each slot_angle_rad further round: smaller,
    flattened by the curvature and fainter, until they turn out of sight. When
    the selection changes, the drum rolls to it -- up when moving forward in
    the list, down when moving back, the shorter way round.
    """

    def __init__(
        self,
        parent_node: NodePath,
        clock: Callable[[], float],
        text_scale: float = 0.05,
        radius: float = 0.085,
        slot_angle_rad: float = np.pi / 4,
        roll_time_s: float = 0.2,
        side_shrink: float = 0.3,
        align: int = TextNode.ARight,
    ):
        """
        :param parent_node: The node to attach the drum to; place the drum with
            its root node, the centre of the selected line
        :param clock: Returns the current time, in seconds (pause-aware game
            time for an in-game drum)
        :param text_scale: The selected line's text scale
        :param radius: The drum's radius, in the parent's units
        :param slot_angle_rad: The angle between two neighbouring lines
        :param roll_time_s: How long a roll to the next line lasts
        :param side_shrink: Extra shrink of a line seen edge-on, on top of the
            curvature's flattening
        :param align: The lines' alignment (a TextNode alignment constant)
        """
        self.root = parent_node.attachNewNode("rollingDrum")
        self.clock = clock
        self.text_scale = text_scale
        self.radius = radius
        self.slot_angle_rad = slot_angle_rad
        self.roll_time_s = roll_time_s
        self.side_shrink = side_shrink
        self.align = align

        # Text lines, reused from frame to frame; the visible ones by their
        # slot's offset from the selection (negative above)
        self._lines: list[NodePath] = []
        self.slots: dict[int, NodePath] = {}

        # The items and selection last shown, and the current roll
        self._shown_items: list = []
        self._shown_index: int | None = None
        self._roll_start_rad = 0.0
        self._roll_start_time_s = -np.inf

    def update(
        self,
        items: Sequence[Any],
        selected: Any,
        label: Callable[[Any], str] = str,
    ):
        """
        Show the items round the drum, rolling it if the selection changed.

        :param items: The items, in loop order
        :param selected: The selected item; nothing is shown if it is not one
            of the items
        :param label: Gives an item's text
        """
        items = list(items)
        index = items.index(selected) if selected in items else None
        if index is not None and self._shown_index is not None:
            self._start_roll(items, index)
        self._shown_items = items
        self._shown_index = index
        self._draw(items, index, label)

    def roll_rad(self) -> float:
        """
        :return: How far the drum is from resting on the selection: the angle it
            still has to roll, easing out to zero
        """
        elapsed_s = self.clock() - self._roll_start_time_s
        progress = min(max(elapsed_s / self.roll_time_s, 0.0), 1.0)
        return self._roll_start_rad * (1.0 - progress) ** 2

    def _start_roll(self, items: list, index: int):
        """
        Roll the drum from the selection last shown to the new one, if it moved.

        :param items: The items now shown
        :param index: The new selection's index in them
        """
        previous = self._shown_items[self._shown_index]
        if items != self._shown_items or previous not in items:
            return  # A different list: show it at rest
        steps = (index - self._shown_index) % len(items)
        if steps == 0:
            return
        if steps > len(items) / 2:
            steps -= len(items)  # roll back, the shorter way round
        # Start from where the drum stands now (it may still be rolling), so
        # the new selection starts where it was shown
        self._roll_start_rad = self.roll_rad() + steps * self.slot_angle_rad
        self._roll_start_time_s = self.clock()

    def _draw(self, items: list, index: int | None, label: Callable[[Any], str]):
        """
        Place a line on each slot in sight, at its angle plus the roll.

        :param items: The items
        :param index: The selection's index in them (None shows nothing)
        :param label: Gives an item's text
        """
        self.slots = {}
        if index is not None:
            roll_rad = self.roll_rad()
            half_turn_rad = np.pi / 2
            first = int(np.ceil((-half_turn_rad - roll_rad) / self.slot_angle_rad))
            last = int(np.floor((half_turn_rad - roll_rad) / self.slot_angle_rad))
            for offset in range(first, last + 1):
                # A single item has no neighbours to show
                if offset != 0 and len(items) == 1:
                    continue
                angle_rad = offset * self.slot_angle_rad + roll_rad
                facing = np.cos(angle_rad)
                if facing < 1e-3:
                    continue  # edge-on: out of sight
                line = self._line(len(self.slots))
                self._place(line, angle_rad, facing)
                line.node().setText(label(items[(index + offset) % len(items)]))
                line.show()
                self.slots[offset] = line
        for line in self._lines[len(self.slots) :]:
            line.hide()

    def _line(self, number: int) -> NodePath:
        """
        :param number: The line's number among this frame's lines
        :return: A text line, created on first use
        """
        while len(self._lines) <= number:
            self._lines.append(
                make_text_line(self.root, f"drumLine{len(self._lines)}", self.align)
            )
        return self._lines[number]

    def _place(self, line: NodePath, angle_rad: float, facing: float):
        """
        Place, size and fade a line at an angle round the drum.

        :param line: The line
        :param angle_rad: Its angle from facing the viewer (positive below)
        :param facing: The angle's cosine
        """
        # Smaller further round, and flattened by the cylinder's curvature
        scale = self.text_scale * (1.0 - self.side_shrink * (1.0 - facing))
        line.setScale(scale, 1.0, scale * facing)
        # The baseline is lowered to centre the glyphs on the slot
        line.setPos(
            0,
            0,
            -self.radius * np.sin(angle_rad) - TEXT_CENTER_OFFSET * scale * facing,
        )
        line.setAlphaScale(facing**2)

    def clean(self):
        """
        Cleans the RollingDrum object
        """
        self.root.removeNode()
        self.root = None
        self._lines = []
        self.slots = {}
        self._shown_items = []
        self.clock = None
