"""
Tests for menu navigation: :class:`MenuNavigator` (with stub widgets) and the
focus look of :class:`CustomButton` (on the session app's real widgets).
"""

from unittest.mock import MagicMock

import pytest

from space_flight.menus.menu_utils import CustomButton, MenuNavigator
from space_flight.ui.input_context import InputContextStack, MenuInputContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class StubWidget:
    """
    Duck-typed navigable widget recording its focus and activations.
    """

    def __init__(self, name, hidden=False):
        """
        :param name: Label used in assertion messages.
        :param hidden: Initial hidden state.
        """
        self.name = name
        self.hidden = hidden
        self.focused = False
        self.activations = 0
        # Name of the mouse region over it, and whether it shows the hover
        self.region = f"region_{name}"
        self.hovered = False

    def is_hidden(self):
        return self.hidden

    def set_focus(self, focused):
        self.focused = focused
        self.hovered = False  # as setting a button's state does

    def refresh_hover(self, region_name):
        if region_name == self.region:
            self.hovered = True

    def activate(self):
        self.activations += 1

    def __repr__(self):
        return self.name


class AdjustableWidget(StubWidget):
    """
    Stub widget that also records adjust() steps.
    """

    def __init__(self, name):
        super().__init__(name)
        self.adjustments = []

    def adjust(self, direction):
        self.adjustments.append(direction)


def make_navigator(rows, on_back=None):
    """
    :param rows: Widget rows.
    :param on_back: Back callback.
    :return: A MenuNavigator on a mock app with a real context stack.
    """
    app = MagicMock()
    app.bindings = {"contexts": {}}
    app.input_context_stack = InputContextStack()
    return MenuNavigator(app, rows, on_back)


def focused(navigator):
    """
    :return: The widgets showing the focus.
    """
    return [w for row in navigator.rows for w in row if w.focused]


@pytest.fixture
def column():
    """
    A three-button column navigator: (navigator, [a, b, c]).
    """
    widgets = [StubWidget("a"), StubWidget("b"), StubWidget("c")]
    return make_navigator([[w] for w in widgets]), widgets


# ---------------------------------------------------------------------------
# Context lifecycle
# ---------------------------------------------------------------------------


def test_navigator_pushes_and_removes_its_context():
    navigator = make_navigator([[StubWidget("a")]])
    stack = navigator.app.input_context_stack
    assert isinstance(stack.stack[-1], MenuInputContext)
    assert stack.stack[-1].navigator is navigator
    navigator.remove()
    assert stack.stack == []


# ---------------------------------------------------------------------------
# Showing the focus
# ---------------------------------------------------------------------------


def test_focus_hidden_until_first_input(column):
    navigator, _ = column
    assert focused(navigator) == []


def test_first_move_only_shows_focus(column):
    navigator, (a, _, _) = column
    navigator.move(0, 1)
    assert focused(navigator) == [a]


def test_first_confirm_only_shows_focus(column):
    navigator, (a, _, _) = column
    navigator.confirm()
    assert focused(navigator) == [a]
    assert a.activations == 0


def test_hide_focus_keeps_position(column):
    navigator, (_, b, _) = column
    navigator.move(0, 1)
    navigator.move(0, 1)
    navigator.hide_focus()
    assert focused(navigator) == []
    navigator.move(0, 1)
    assert focused(navigator) == [b]


def test_show_focus_clears_mouse_hover(column):
    """
    The cursor hides on a key press: the widget under it must not keep its
    hover look next to the focus.
    """
    navigator, (_, b, _) = column
    b.hovered = True
    navigator.move(0, 1)
    assert not b.hovered


def test_refresh_hover_restores_widget_under_mouse(column):
    navigator, (_, b, c) = column
    navigator.app.mouseWatcherNode.getOverRegion.return_value.getName.return_value = (
        b.region
    )
    navigator.refresh_hover()
    assert b.hovered
    assert not c.hovered


def test_refresh_hover_without_region_under_mouse(column):
    navigator, (a, _, _) = column
    navigator.app.mouseWatcherNode.getOverRegion.return_value = None
    navigator.refresh_hover()  # must not raise
    assert not a.hovered


def test_show_focus_skips_hidden_first_widget():
    a, b = StubWidget("a", hidden=True), StubWidget("b")
    navigator = make_navigator([[a], [b]])
    navigator.move(0, 1)
    assert focused(navigator) == [b]


# ---------------------------------------------------------------------------
# Moving
# ---------------------------------------------------------------------------


def test_move_down_and_up(column):
    navigator, (a, b, _) = column
    navigator.move(0, 1)
    navigator.move(0, 1)
    assert focused(navigator) == [b]
    navigator.move(0, -1)
    assert focused(navigator) == [a]


def test_move_wraps_around(column):
    navigator, (_, _, c) = column
    navigator.move(0, 1)
    navigator.move(0, -1)
    assert focused(navigator) == [c]


def test_move_skips_hidden_rows():
    a, b, c = StubWidget("a"), StubWidget("b", hidden=True), StubWidget("c")
    navigator = make_navigator([[a], [b], [c]])
    navigator.move(0, 1)
    navigator.move(0, 1)
    assert focused(navigator) == [c]


def test_move_along_row():
    a, back, start = StubWidget("a"), StubWidget("back"), StubWidget("start")
    navigator = make_navigator([[a], [back, start]])
    navigator.move(0, 1)
    navigator.move(0, 1)
    assert focused(navigator) == [back]
    navigator.move(1, 0)
    assert focused(navigator) == [start]
    navigator.move(1, 0)
    assert focused(navigator) == [back]


def test_move_along_row_skips_hidden():
    """
    A row whose other widget is hidden acts as a lone widget.
    """
    back, start = StubWidget("back"), StubWidget("start", hidden=True)
    navigator = make_navigator([[back, start]])
    navigator.move(0, 1)
    navigator.move(1, 0)
    assert focused(navigator) == [back]


def test_move_into_row_keeps_nearest_column():
    left, right = StubWidget("left"), StubWidget("right")
    below = StubWidget("below")
    navigator = make_navigator([[left, right], [below]])
    navigator.move(0, 1)
    navigator.move(1, 0)
    navigator.move(0, 1)
    assert focused(navigator) == [below]
    navigator.move(0, -1)
    assert focused(navigator) == [right]


def test_left_right_adjusts_lone_widget():
    slider = AdjustableWidget("slider")
    navigator = make_navigator([[slider]])
    navigator.move(0, 1)
    navigator.move(1, 0)
    navigator.move(-1, 0)
    assert slider.adjustments == [1, -1]


def test_left_right_on_plain_lone_widget_does_nothing(column):
    navigator, (a, _, _) = column
    navigator.move(0, 1)
    navigator.move(1, 0)
    assert focused(navigator) == [a]


def test_focus_on_moves_focus(column):
    navigator, (a, _, c) = column
    navigator.focus_on(c)
    navigator.move(0, 1)  # shows it
    assert focused(navigator) == [c]
    navigator.focus_on(a)
    assert focused(navigator) == [a]


def test_focus_on_does_not_show_hidden_focus(column):
    navigator, (_, _, c) = column
    navigator.focus_on(c)
    assert focused(navigator) == []


# ---------------------------------------------------------------------------
# Confirm / back
# ---------------------------------------------------------------------------


def test_confirm_activates_focused(column):
    navigator, (_, b, _) = column
    navigator.move(0, 1)
    navigator.move(0, 1)
    navigator.confirm()
    assert b.activations == 1


def test_back_calls_on_back():
    on_back = MagicMock()
    navigator = make_navigator([[StubWidget("a")]], on_back)
    navigator.back()
    on_back.assert_called_once()


def test_back_without_callback_is_noop(column):
    navigator, _ = column
    navigator.back()  # must not raise


def test_covered_screen_ignores_input():
    """
    With every widget hidden (another screen on top), nothing reacts.
    """
    a = StubWidget("a", hidden=True)
    on_back = MagicMock()
    navigator = make_navigator([[a]], on_back)
    navigator.move(0, 1)
    navigator.confirm()
    navigator.back()
    assert focused(navigator) == []
    assert a.activations == 0
    on_back.assert_not_called()


# ---------------------------------------------------------------------------
# CustomButton focus
# ---------------------------------------------------------------------------


@pytest.fixture
def button(spaceflight_app):
    command = MagicMock()
    btn = CustomButton(
        app=spaceflight_app,
        pos=(0, 0, 0),
        command=command,
        text="b",
        scale=0.2,
        extraArgs=[3],
    )
    yield btn, command
    btn.destroy()


def test_button_focus_shows_hover_state(button):
    btn, _ = button
    btn.set_focus(True)
    assert btn.button.guiItem.getState() == 2
    btn.set_focus(False)
    assert btn.button.guiItem.getState() == 0


def test_button_activate_runs_command(button):
    btn, command = button
    btn.activate()
    command.assert_called_once_with(3)


def test_selected_button_shows_hover_geom_while_focused(button, spaceflight_app):
    btn, _ = button
    geoms = spaceflight_app.menu_models.button_geom
    btn.set_pressed()
    assert btn.button["geom"] == geoms[1]
    btn.set_focus(True)
    assert btn.button["geom"] == geoms[2]
    btn.set_focus(False)
    assert btn.button["geom"] == geoms[1]


def test_button_refresh_hover_only_when_mouse_over_it(button):
    btn, _ = button
    btn.refresh_hover("another region")
    assert btn.button.guiItem.getState() == 0
    btn.refresh_hover(btn.button.guiItem.getId())
    assert btn.button.guiItem.getState() == 2


def test_button_is_hidden(button):
    btn, _ = button
    assert not btn.is_hidden()
    btn.hide()
    assert btn.is_hidden()
