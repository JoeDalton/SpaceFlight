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


def make_menu_navigator(rows, on_back=None, scroll_list=None, scroll_rows=None):
    """
    :param rows: Widget rows.
    :param on_back: Back callback.
    :param scroll_list: The (mock) scroll list.
    :param scroll_rows: Each row's scroll-list index, or None.
    :return: A MenuNavigator on a mock app with a real context stack.
    """
    app = MagicMock()
    app.bindings = {"contexts": {}}
    app.input_context_stack = InputContextStack()
    return MenuNavigator(app, rows, on_back, scroll_list, scroll_rows)


def focused(menu_navigator):
    """
    :return: The widgets showing the focus.
    """
    return [w for row in menu_navigator.rows for w in row if w.focused]


@pytest.fixture
def column():
    """
    A three-button column menu_navigator: (menu_navigator, [a, b, c]).
    """
    widgets = [StubWidget("a"), StubWidget("b"), StubWidget("c")]
    return make_menu_navigator([[w] for w in widgets]), widgets


# ---------------------------------------------------------------------------
# Context lifecycle
# ---------------------------------------------------------------------------


def test_menu_navigator_pushes_and_removes_its_context():
    menu_navigator = make_menu_navigator([[StubWidget("a")]])
    stack = menu_navigator.app.input_context_stack
    assert isinstance(stack.stack[-1], MenuInputContext)
    assert stack.stack[-1].menu_navigator is menu_navigator
    menu_navigator.remove()
    assert stack.stack == []


# ---------------------------------------------------------------------------
# Showing the focus
# ---------------------------------------------------------------------------


def test_focus_hidden_until_first_input(column):
    menu_navigator, _ = column
    assert focused(menu_navigator) == []


def test_first_move_only_shows_focus(column):
    menu_navigator, (a, _, _) = column
    menu_navigator.move(0, 1)
    assert focused(menu_navigator) == [a]


def test_first_confirm_only_shows_focus(column):
    menu_navigator, (a, _, _) = column
    menu_navigator.confirm()
    assert focused(menu_navigator) == [a]
    assert a.activations == 0


def test_hide_focus_keeps_position(column):
    menu_navigator, (_, b, _) = column
    menu_navigator.move(0, 1)
    menu_navigator.move(0, 1)
    menu_navigator.hide_focus()
    assert focused(menu_navigator) == []
    menu_navigator.move(0, 1)
    assert focused(menu_navigator) == [b]


def test_show_focus_clears_mouse_hover(column):
    """
    The cursor hides on a key press: the widget under it must not keep its
    hover look next to the focus.
    """
    menu_navigator, (_, b, _) = column
    b.hovered = True
    menu_navigator.move(0, 1)
    assert not b.hovered


def test_refresh_hover_restores_widget_under_mouse(column):
    menu_navigator, (_, b, c) = column
    over_region = menu_navigator.app.mouseWatcherNode.getOverRegion.return_value
    over_region.getName.return_value = b.region
    menu_navigator.refresh_hover()
    assert b.hovered
    assert not c.hovered


def test_refresh_hover_without_region_under_mouse(column):
    menu_navigator, (a, _, _) = column
    menu_navigator.app.mouseWatcherNode.getOverRegion.return_value = None
    menu_navigator.refresh_hover()  # must not raise
    assert not a.hovered


def test_show_focus_skips_hidden_first_widget():
    a, b = StubWidget("a", hidden=True), StubWidget("b")
    menu_navigator = make_menu_navigator([[a], [b]])
    menu_navigator.move(0, 1)
    assert focused(menu_navigator) == [b]


# ---------------------------------------------------------------------------
# Moving
# ---------------------------------------------------------------------------


def test_move_down_and_up(column):
    menu_navigator, (a, b, _) = column
    menu_navigator.move(0, 1)
    menu_navigator.move(0, 1)
    assert focused(menu_navigator) == [b]
    menu_navigator.move(0, -1)
    assert focused(menu_navigator) == [a]


def test_move_wraps_around(column):
    menu_navigator, (_, _, c) = column
    menu_navigator.move(0, 1)
    menu_navigator.move(0, -1)
    assert focused(menu_navigator) == [c]


def test_move_skips_hidden_rows():
    a, b, c = StubWidget("a"), StubWidget("b", hidden=True), StubWidget("c")
    menu_navigator = make_menu_navigator([[a], [b], [c]])
    menu_navigator.move(0, 1)
    menu_navigator.move(0, 1)
    assert focused(menu_navigator) == [c]


def test_move_along_row():
    a, back, start = StubWidget("a"), StubWidget("back"), StubWidget("start")
    menu_navigator = make_menu_navigator([[a], [back, start]])
    menu_navigator.move(0, 1)
    menu_navigator.move(0, 1)
    assert focused(menu_navigator) == [back]
    menu_navigator.move(1, 0)
    assert focused(menu_navigator) == [start]
    menu_navigator.move(1, 0)
    assert focused(menu_navigator) == [back]


def test_move_along_row_skips_hidden():
    """
    A row whose other widget is hidden acts as a lone widget.
    """
    back, start = StubWidget("back"), StubWidget("start", hidden=True)
    menu_navigator = make_menu_navigator([[back, start]])
    menu_navigator.move(0, 1)
    menu_navigator.move(1, 0)
    assert focused(menu_navigator) == [back]


def test_move_into_row_keeps_nearest_column():
    left, right = StubWidget("left"), StubWidget("right")
    below = StubWidget("below")
    menu_navigator = make_menu_navigator([[left, right], [below]])
    menu_navigator.move(0, 1)
    menu_navigator.move(1, 0)
    menu_navigator.move(0, 1)
    assert focused(menu_navigator) == [below]
    menu_navigator.move(0, -1)
    assert focused(menu_navigator) == [right]


def test_left_right_adjusts_lone_widget():
    slider = AdjustableWidget("slider")
    menu_navigator = make_menu_navigator([[slider]])
    menu_navigator.move(0, 1)
    menu_navigator.move(1, 0)
    menu_navigator.move(-1, 0)
    assert slider.adjustments == [1, -1]


def test_left_right_on_plain_lone_widget_does_nothing(column):
    menu_navigator, (a, _, _) = column
    menu_navigator.move(0, 1)
    menu_navigator.move(1, 0)
    assert focused(menu_navigator) == [a]


def test_focus_on_moves_focus(column):
    menu_navigator, (a, _, c) = column
    menu_navigator.focus_on(c)
    menu_navigator.move(0, 1)  # shows it
    assert focused(menu_navigator) == [c]
    menu_navigator.focus_on(a)
    assert focused(menu_navigator) == [a]


def test_focus_on_does_not_show_hidden_focus(column):
    menu_navigator, (_, _, c) = column
    menu_navigator.focus_on(c)
    assert focused(menu_navigator) == []


def test_set_rows_keeps_position_and_focus_on_new_widget(column):
    """
    A screen rebuilding its list hands new widgets: the focus moves onto the
    widget now at its position, without touching the (destroyed) old ones.
    """
    menu_navigator, (_, b, _) = column
    menu_navigator.move(0, 1)
    menu_navigator.move(0, 1)
    new = [StubWidget("x"), StubWidget("y"), StubWidget("z")]
    b.set_focus = MagicMock(side_effect=AssertionError("destroyed"))
    menu_navigator.set_rows([[w] for w in new])
    assert focused(menu_navigator) == [new[1]]


def test_set_rows_clamps_position_to_fewer_rows(column):
    menu_navigator, _ = column
    menu_navigator.move(0, 1)
    menu_navigator.move(0, -1)  # wraps to the last row
    new = StubWidget("only")
    menu_navigator.set_rows([[new]])
    assert focused(menu_navigator) == [new]


def test_focus_move_scrolls_list_rows_into_view():
    widgets = [StubWidget("top"), StubWidget("in_list"), StubWidget("bottom")]
    scroll_list = MagicMock()
    menu_navigator = make_menu_navigator(
        [[w] for w in widgets], scroll_list=scroll_list, scroll_rows=[None, 4, None]
    )
    menu_navigator.move(0, 1)  # shows the focus on "top": not in the list
    scroll_list.scroll_to.assert_not_called()
    menu_navigator.move(0, 1)
    scroll_list.scroll_to.assert_called_once_with(4)


def test_hidden_focus_does_not_scroll():
    widgets = [StubWidget("a"), StubWidget("b")]
    scroll_list = MagicMock()
    menu_navigator = make_menu_navigator(
        [[w] for w in widgets], scroll_list=scroll_list, scroll_rows=[0, 1]
    )
    menu_navigator.focus_on(widgets[1])
    scroll_list.scroll_to.assert_not_called()


# ---------------------------------------------------------------------------
# Confirm / back
# ---------------------------------------------------------------------------


def test_confirm_activates_focused(column):
    menu_navigator, (_, b, _) = column
    menu_navigator.move(0, 1)
    menu_navigator.move(0, 1)
    menu_navigator.confirm()
    assert b.activations == 1


def test_back_calls_on_back():
    on_back = MagicMock()
    menu_navigator = make_menu_navigator([[StubWidget("a")]], on_back)
    menu_navigator.back()
    on_back.assert_called_once()


def test_back_without_callback_is_noop(column):
    menu_navigator, _ = column
    menu_navigator.back()  # must not raise


def test_covered_screen_ignores_input():
    """
    With every widget hidden (another screen on top), nothing reacts.
    """
    a = StubWidget("a", hidden=True)
    on_back = MagicMock()
    menu_navigator = make_menu_navigator([[a]], on_back)
    menu_navigator.move(0, 1)
    menu_navigator.confirm()
    menu_navigator.back()
    assert focused(menu_navigator) == []
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
