"""
Menu navigation wiring of the menu screens, and the navigable widgets'
focus/adjust behaviour, on the session app's real widgets.
"""

from unittest.mock import MagicMock

import pytest

from space_flight.menus.gameplay_settings_menu_state import (
    _SLIDERS,
    GameplaySettingsMenuState,
)
from space_flight.menus.graphics_settings_menu_state import GraphicsSettingsMenuState
from space_flight.menus.level_end_state import LevelEndState
from space_flight.menus.level_selection_menu_state import LevelSelectionMenuState
from space_flight.menus.main_menu_state import MainMenuState
from space_flight.menus.menu_utils import (
    _FOCUS_TINT,
    CustomCheckButton,
    CustomDropDown,
    CustomSlider,
    MenuNavigator,
    ScrollableList,
)
from space_flight.menus.pause_menu_state import PauseMenuState
from space_flight.menus.settings_menu_state import SettingsMenuState

SCREENS = [
    MainMenuState,
    SettingsMenuState,
    PauseMenuState,
    LevelEndState,
    LevelSelectionMenuState,
    GameplaySettingsMenuState,
    GraphicsSettingsMenuState,
]

# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------


@pytest.fixture
def entered(spaceflight_app, request):
    """
    Enter the screen class *request.param* on the session app; exit it after.

    :return: The entered state.
    """
    state = request.param(spaceflight_app)
    state.enter()
    yield state
    if state.menu_navigator is not None:
        state.exit()


@pytest.mark.parametrize("entered", SCREENS, indirect=True)
def test_screen_pushes_navigator_context_and_removes_it(entered, spaceflight_app):
    stack = spaceflight_app.input_context_stack
    navigator = entered.menu_navigator
    assert isinstance(navigator, MenuNavigator)
    assert stack.stack[-1] is navigator.context
    entered.exit()
    assert navigator.context not in stack.stack
    entered.menu_navigator = None  # already exited


@pytest.mark.parametrize("entered", SCREENS, indirect=True)
def test_screen_widgets_are_navigable(entered):
    """
    Every widget handed to the navigator implements the duck-typed API.
    """
    navigator = entered.menu_navigator
    assert len(navigator.scroll_rows) == len(navigator.rows)
    for row in navigator.rows:
        assert row
        for widget in row:
            for method in ("is_hidden", "set_focus", "refresh_hover", "activate"):
                assert callable(getattr(widget, method))


@pytest.mark.parametrize(
    "entered, back",
    [
        (MainMenuState, None),
        (SettingsMenuState, "back"),
        (PauseMenuState, "resume_game"),
        (LevelEndState, None),
        (LevelSelectionMenuState, "back"),
        (GameplaySettingsMenuState, "cancel"),
        (GraphicsSettingsMenuState, "cancel"),
    ],
    indirect=["entered"],
)
def test_screen_back_action(entered, back):
    on_back = entered.menu_navigator.on_back
    if back is None:
        assert on_back is None
    else:
        assert on_back == getattr(entered, back)


@pytest.mark.parametrize("entered", [GameplaySettingsMenuState], indirect=True)
def test_gameplay_rows(entered):
    navigator = entered.menu_navigator
    assert navigator.rows[0] == [entered.preset_menu]
    assert navigator.rows[-1] == [entered.cancel_btn, entered.save_btn]
    assert navigator.scroll_list is entered.scroll_list
    assert navigator.scroll_rows[0] is None and navigator.scroll_rows[-1] is None
    # One row per slider and checkbox, at its scroll row
    n_settings = len(entered.sliders) + len(entered.checkboxes)
    assert len(navigator.rows) == n_settings + 2


@pytest.mark.parametrize("entered", [GameplaySettingsMenuState], indirect=True)
def test_gameplay_slider_steps_by_its_setting_step(entered):
    path, slider = next(iter(entered.sliders.items()))
    assert slider.step == _SLIDERS[path[1:]][1]


@pytest.mark.parametrize("entered", [GameplaySettingsMenuState], indirect=True)
def test_gameplay_preset_rebuild_refreshes_navigator_rows(entered):
    """
    Picking a preset rebuilds the rows: the navigator must hold the new ones.
    """
    old_rows = entered.menu_navigator.rows
    entered.select_preset(next(iter(entered.app.gameplay_settings.presets)))
    rows = entered.menu_navigator.rows
    assert rows is not old_rows
    assert rows[1][0] in [*entered.sliders.values(), *entered.checkboxes.values()]


@pytest.mark.parametrize("entered", [GraphicsSettingsMenuState], indirect=True)
def test_graphics_rows(entered):
    navigator = entered.menu_navigator
    assert navigator.rows[0] == [btn for _, btn in entered.mode_buttons]
    assert navigator.rows[-1] == [
        entered.default_btn,
        entered.cancel_btn,
        entered.save_btn,
    ]
    n_settings = len(entered.sliders) + len(entered.checkboxes) + 1  # + mode row
    assert len(navigator.rows) == n_settings + 1


@pytest.mark.parametrize("entered", [GraphicsSettingsMenuState], indirect=True)
def test_graphics_discrete_sliders_step_one_stop(entered):
    assert entered.sliders[("antialiasing", "msaa")].step == 1


@pytest.mark.parametrize("entered", [LevelSelectionMenuState], indirect=True)
def test_level_selection_focus_jumps_to_start(entered):
    entered.set_level(0)
    navigator = entered.menu_navigator
    assert navigator.focused is entered.start_button


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


def test_slider_adjust_steps_and_clamps(spaceflight_app):
    slider = CustomSlider(
        app=spaceflight_app,
        pos=(0, 0, 0),
        value=0.5,
        value_range=(0.0, 1.0),
        command=MagicMock(),
        step=0.2,
    )
    slider.adjust(1)
    assert slider.get_value() == pytest.approx(0.7)
    slider.adjust(1)
    slider.adjust(1)
    assert slider.get_value() == pytest.approx(1.0)
    slider.adjust(-1)
    assert slider.get_value() == pytest.approx(0.8)
    slider.destroy()


def test_slider_default_step_is_a_twentieth_of_range(spaceflight_app):
    slider = CustomSlider(
        app=spaceflight_app,
        pos=(0, 0, 0),
        value=0,
        value_range=(0.0, 2.0),
        command=MagicMock(),
    )
    assert slider.step == pytest.approx(0.1)
    slider.destroy()


def test_slider_focus_and_hover_on_thumb(spaceflight_app):
    slider = CustomSlider(
        app=spaceflight_app,
        pos=(0, 0, 0),
        value=0,
        value_range=(0.0, 1.0),
        command=MagicMock(),
    )
    thumb = slider.slider.thumb.guiItem
    slider.set_focus(True)
    assert thumb.getState() == 2
    slider.set_focus(False)
    assert thumb.getState() == 0
    slider.refresh_hover(thumb.getId())
    assert thumb.getState() == 2
    slider.destroy()


def test_checkbox_focus_tint_and_activate_toggles(spaceflight_app):
    command = MagicMock()
    checkbox = CustomCheckButton(
        app=spaceflight_app,
        pos=(0, 0, 0),
        value=False,
        command=command,
        extraArgs=["path"],
    )
    checkbox.set_focus(True)
    assert tuple(checkbox.checkbox.getColorScale()) == pytest.approx(
        _FOCUS_TINT, abs=1e-3
    )
    checkbox.set_focus(False)
    assert not checkbox.checkbox.hasColorScale()
    checkbox.activate()
    assert checkbox.get_value() is True
    command.assert_called_once_with(1, "path")
    checkbox.destroy()


def make_drop_down(app, value="b"):
    command = MagicMock()
    drop_down = CustomDropDown(
        app=app,
        pos=(0, 0, 0),
        options=[("A", "a"), ("B", "b"), ("C", "c")],
        value=value,
        command=command,
    )
    return drop_down, command


def test_drop_down_adjust_selects_neighbour_and_wraps(spaceflight_app):
    drop_down, command = make_drop_down(spaceflight_app)
    drop_down.adjust(1)
    assert drop_down.get_value() == "c"
    command.assert_called_once_with("c")
    drop_down.adjust(1)
    assert drop_down.get_value() == "a"
    drop_down.adjust(-1)
    assert drop_down.get_value() == "c"
    drop_down.destroy()


def test_drop_down_activate_selects_next(spaceflight_app):
    drop_down, _ = make_drop_down(spaceflight_app, value="a")
    drop_down.activate()
    assert drop_down.get_value() == "b"
    drop_down.destroy()


def test_drop_down_focus_on_head(spaceflight_app):
    drop_down, _ = make_drop_down(spaceflight_app)
    drop_down.set_focus(True)
    assert drop_down.head.button.guiItem.getState() == 2
    drop_down.destroy()


@pytest.fixture
def scroll_list(spaceflight_app):
    """
    A 20-row list showing 5 rows (row height 0.1, frame 0.5 tall).
    """
    scroll = ScrollableList(
        spaceflight_app, row_height=0.1, frame_top=0.5, frame_bottom=0
    )
    scroll.rebuild(20)
    yield scroll
    scroll.destroy()


def test_scroll_to_visible_row_does_not_scroll(scroll_list):
    scroll_list.scroll_to(2)
    assert scroll_list.v_scrollbar["value"] == pytest.approx(0)


def test_scroll_to_row_below_shows_it_with_margin(scroll_list):
    scroll_list.scroll_to(10)
    # Rows 9 to 11 visible: the window ends at the bottom of row 11
    assert scroll_list.v_scrollbar["value"] == pytest.approx(1.2 - 0.5)


def test_scroll_to_row_above_shows_it_with_margin(scroll_list):
    scroll_list.v_scrollbar["value"] = 1.0
    scroll_list.scroll_to(8)
    assert scroll_list.v_scrollbar["value"] == pytest.approx(0.7)


def test_scroll_to_clamps_to_range(scroll_list):
    scroll_list.scroll_to(19)
    assert scroll_list.v_scrollbar["value"] == pytest.approx(1.5)
