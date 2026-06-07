from unittest.mock import MagicMock

import pytest

from space_flight.ui.input_context import (
    FlightInputContext,
    InputContext,
    InputContextStack,
    PauseMenuInputContext,
    RadialMenuInputContext,
    _angle_to_slice,
)
from space_flight.ui.input_reader import InputState

# ---------------------------------------------------------------------------
# Helpers — mock objects
# ---------------------------------------------------------------------------


def _make_state(buttons=None, repeats=None, releases=None, axes=None):
    """
    Build an InputState populated with the provided dicts.

    :param buttons: Keys currently pressed this frame.
    :param repeats: Keys held across frames.
    :param releases: Keys released this frame.
    :param axes: Axis name → float value.
    :return: Populated InputState.
    """
    state = InputState()
    state.buttons = buttons or {}
    state.repeats = repeats or {}
    state.releases = releases or {}
    state.axes = axes or {}
    return state


def _make_game(input_type="keyboard", device_bindings=None, global_bindings=None):
    """
    Build a minimal mock game whose app.bindings reflects the given config.

    :param input_type: Active device type string.
    :param device_bindings: Action → hardware-name dict for the device.
    :param global_bindings: Action → hardware-name dict for universal keys.
    :return: MagicMock with app.bindings configured.
    """
    game = MagicMock()
    game.app.bindings = {
        "input_type": input_type,
        "contexts": {"flight": {input_type: device_bindings or {}}},
        "global": global_bindings or {},
    }
    game.game_time.get_time_step.return_value = 0.016
    return game


def _make_flight_ctx(device_bindings=None, global_bindings=None, input_type="keyboard"):
    """
    Return a (FlightInputContext, game_mock, player_mock) triple.

    :param device_bindings: Device-specific bindings dict.
    :param global_bindings: Global bindings dict.
    :param input_type: Active device type.
    :return: Tuple of (context, game, player).
    """
    game = _make_game(input_type, device_bindings, global_bindings)
    player = MagicMock()
    player.view_offset = [0.0, 0.0]
    ctx = FlightInputContext(game=game, player=player)
    return ctx, game, player


# ---------------------------------------------------------------------------
# Minimal InputContext stub for stack tests
# ---------------------------------------------------------------------------


class _TrackingContext(InputContext):
    """
    InputContext that records every lifecycle call it receives.
    """

    def __init__(self, name="ctx"):
        """
        :param name: Label used in call records.
        """
        self.name = name
        self.calls = []

    def on_activate(self):
        """Record activation."""
        self.calls.append("activate")

    def on_deactivate(self):
        """Record deactivation."""
        self.calls.append("deactivate")

    def consume(self, state):
        """
        Record dispatch call.

        :param state: InputState passed by the stack.
        """
        self.calls.append("consume")

    def clean(self):
        """Record cleanup."""
        self.calls.append("clean")


@pytest.fixture
def stack():
    """
    Return an empty InputContextStack.
    """
    return InputContextStack()


# ---------------------------------------------------------------------------
# InputContextStack
# ---------------------------------------------------------------------------


def test_stack_dispatch_on_empty_is_noop(stack):
    """
    Calling dispatch() on an empty stack must not raise.
    """
    stack.dispatch(_make_state())  # must not raise


def test_stack_push_calls_on_activate(stack):
    """
    push() must call on_activate on the pushed context.
    """
    ctx = _TrackingContext()
    stack.push(ctx)
    assert "activate" in ctx.calls


def test_stack_push_deactivates_previous_top(stack):
    """
    push() must deactivate the context that was previously on top before
    activating the new one.
    """
    ctx_a = _TrackingContext("a")
    ctx_b = _TrackingContext("b")
    stack.push(ctx_a)
    ctx_a.calls.clear()
    stack.push(ctx_b)
    assert ctx_a.calls[0] == "deactivate"
    assert "activate" in ctx_b.calls


def test_stack_pop_calls_on_deactivate_and_clean(stack):
    """
    pop() must call on_deactivate then clean on the removed context.
    """
    ctx = _TrackingContext()
    stack.push(ctx)
    ctx.calls.clear()
    stack.pop()
    assert ctx.calls == ["deactivate", "clean"]


def test_stack_pop_reactivates_context_below(stack):
    """
    pop() must call on_activate on the context that becomes the new top.
    """
    ctx_a = _TrackingContext("a")
    ctx_b = _TrackingContext("b")
    stack.push(ctx_a)
    stack.push(ctx_b)
    ctx_a.calls.clear()
    stack.pop()
    assert "activate" in ctx_a.calls


def test_stack_pop_on_empty_does_not_raise(stack):
    """
    pop() on an empty stack must silently do nothing.
    """
    stack.pop()  # must not raise


def test_stack_dispatch_calls_consume_on_top(stack):
    """
    dispatch() must call consume() exactly once on the top context and not
    on any context below it.
    """
    ctx_a = _TrackingContext("a")
    ctx_b = _TrackingContext("b")
    stack.push(ctx_a)
    stack.push(ctx_b)
    ctx_a.calls.clear()
    ctx_b.calls.clear()
    stack.dispatch(_make_state())
    assert "consume" in ctx_b.calls
    assert "consume" not in ctx_a.calls


def test_stack_dispatch_after_pop_reaches_new_top(stack):
    """
    After pop(), dispatch() must route to the context that is now on top.
    """
    ctx_a = _TrackingContext("a")
    ctx_b = _TrackingContext("b")
    stack.push(ctx_a)
    stack.push(ctx_b)
    stack.pop()
    ctx_a.calls.clear()
    stack.dispatch(_make_state())
    assert "consume" in ctx_a.calls


def test_stack_clean_removes_all_contexts(stack):
    """
    clean() must pop and clean every context in the stack.
    """
    ctx_a = _TrackingContext("a")
    ctx_b = _TrackingContext("b")
    stack.push(ctx_a)
    stack.push(ctx_b)
    stack.clean()
    assert "clean" in ctx_a.calls
    assert "clean" in ctx_b.calls
    stack.dispatch(_make_state())  # stack now empty — must not raise


def test_stack_clean_calls_on_deactivate_before_clean(stack):
    """
    clean() must call on_deactivate before clean on every removed context.
    """
    ctx = _TrackingContext()
    stack.push(ctx)
    ctx.calls.clear()
    stack.clean()
    assert ctx.calls.index("deactivate") < ctx.calls.index("clean")


# ---------------------------------------------------------------------------
# FlightInputContext — binding helpers
# ---------------------------------------------------------------------------


def test_flight_ctx_pressed_detects_device_binding():
    """
    _pressed must return True when the device-specific hardware key is in
    state.buttons.
    """
    ctx, _, _ = _make_flight_ctx(device_bindings={"fire": "space"})
    state = _make_state(buttons={"space": True})
    assert ctx._pressed(state, "fire") is True


def test_flight_ctx_pressed_returns_false_when_not_pressed():
    """
    _pressed must return False when the bound key is absent from state.buttons.
    """
    ctx, _, _ = _make_flight_ctx(device_bindings={"fire": "space"})
    state = _make_state(buttons={})
    assert ctx._pressed(state, "fire") is False


def test_flight_ctx_pressed_falls_back_to_global_binding():
    """
    _pressed must return True via the global binding when the device binding
    is absent but the global key is in state.buttons.
    """
    ctx, _, _ = _make_flight_ctx(
        device_bindings={},
        global_bindings={"pause": "escape"},
    )
    state = _make_state(buttons={"escape": True})
    assert ctx._pressed(state, "pause") is True


def test_flight_ctx_pressed_device_binding_takes_precedence():
    """
    When both a device binding and a global binding exist for the same action,
    the device binding key being pressed must be sufficient to return True.
    """
    ctx, _, _ = _make_flight_ctx(
        device_bindings={"pause": "gamepad_start"},
        global_bindings={"pause": "escape"},
    )
    state = _make_state(buttons={"gamepad_start": True})
    assert ctx._pressed(state, "pause") is True


def test_flight_ctx_held_detects_device_binding():
    """
    _held must return True when the device-specific key is in state.repeats.
    """
    ctx, _, _ = _make_flight_ctx(device_bindings={"fire": "space"})
    state = _make_state(repeats={"space": True})
    assert ctx._held(state, "fire") is True


def test_flight_ctx_held_falls_back_to_global_binding():
    """
    _held must return True via the global binding when the global key is in
    state.repeats.
    """
    ctx, _, _ = _make_flight_ctx(
        device_bindings={},
        global_bindings={"pause": "escape"},
    )
    state = _make_state(repeats={"escape": True})
    assert ctx._held(state, "pause") is True


def test_flight_ctx_released_detects_device_binding():
    """
    _released must return True when the device-specific key is in
    state.releases.
    """
    ctx, _, _ = _make_flight_ctx(device_bindings={"boost_off": "b"})
    state = _make_state(releases={"b": True})
    assert ctx._released(state, "boost_off") is True


def test_flight_ctx_released_falls_back_to_global_binding():
    """
    _released must return True via the global binding when the global key is
    in state.releases.
    """
    ctx, _, _ = _make_flight_ctx(
        device_bindings={},
        global_bindings={"pause": "escape"},
    )
    state = _make_state(releases={"escape": True})
    assert ctx._released(state, "pause") is True


def test_flight_ctx_active_true_on_press():
    """
    _active must return True when the key is freshly pressed (in buttons).
    """
    ctx, _, _ = _make_flight_ctx(device_bindings={"fire": "space"})
    state = _make_state(buttons={"space": True})
    assert ctx._active(state, "fire") is True


def test_flight_ctx_active_true_while_held():
    """
    _active must return True when the key is being held (in repeats).
    """
    ctx, _, _ = _make_flight_ctx(device_bindings={"fire": "space"})
    state = _make_state(repeats={"space": True})
    assert ctx._active(state, "fire") is True


def test_flight_ctx_active_false_when_not_pressed_or_held():
    """
    _active must return False when the key is neither in buttons nor repeats.
    """
    ctx, _, _ = _make_flight_ctx(device_bindings={"fire": "space"})
    state = _make_state()
    assert ctx._active(state, "fire") is False


def test_flight_ctx_axis_returns_value():
    """
    _axis must return the axis value from state.axes for the bound action.
    """
    ctx, _, _ = _make_flight_ctx(
        device_bindings={"throttle": "right_trigger"},
        input_type="gamepad",
    )
    state = _make_state(axes={"right_trigger": 0.8})
    assert ctx._axis(state, "throttle") == pytest.approx(0.8)


def test_flight_ctx_axis_returns_zero_for_unknown_action():
    """
    _axis must return 0.0 when the action has no binding.
    """
    ctx, _, _ = _make_flight_ctx(device_bindings={})
    state = _make_state(axes={"right_trigger": 0.8})
    assert ctx._axis(state, "throttle") == pytest.approx(0.0)


def test_flight_ctx_clean_nulls_references():
    """
    clean() must set the game and player references to None so the context
    does not hold live objects after removal from the stack.
    """
    ctx, _, _ = _make_flight_ctx()
    ctx.clean()
    assert ctx._game is None
    assert ctx._player is None


# ---------------------------------------------------------------------------
# PauseMenuInputContext
# ---------------------------------------------------------------------------


def _make_pause_ctx(device_pause=None, global_pause=None):
    """
    Return a PauseMenuInputContext backed by a mock game.

    :param device_pause: Hardware key mapped to pause in the device bindings.
    :param global_pause: Hardware key mapped to pause in the global bindings.
    :return: Tuple of (PauseMenuInputContext, game_mock).
    """
    game = _make_game(
        input_type="joystick",
        device_bindings={"pause": device_pause} if device_pause else {},
        global_bindings={"pause": global_pause} if global_pause else {},
    )
    ctx = PauseMenuInputContext(app=game.app)
    return ctx, game


def test_pause_ctx_consume_pops_state_manager_on_device_key():
    """
    consume() must call app.state_manager.pop() when the device-specific
    pause key is in state.buttons.
    """
    ctx, game = _make_pause_ctx(device_pause="stick_button_7")
    ctx.consume(_make_state(buttons={"stick_button_7": True}))
    game.app.state_manager.pop.assert_called_once()


def test_pause_ctx_consume_pops_state_manager_on_global_key():
    """
    consume() must call app.state_manager.pop() when the global pause key
    (escape) is in state.buttons, regardless of device type.
    """
    ctx, game = _make_pause_ctx(global_pause="escape")
    ctx.consume(_make_state(buttons={"escape": True}))
    game.app.state_manager.pop.assert_called_once()


def test_pause_ctx_consume_does_not_pop_when_no_key_pressed():
    """
    consume() must not call app.state_manager.pop() when neither pause key
    is present in state.buttons.
    """
    ctx, game = _make_pause_ctx(device_pause="stick_button_7", global_pause="escape")
    ctx.consume(_make_state(buttons={}))
    game.app.state_manager.pop.assert_not_called()


def test_pause_ctx_consume_pops_only_once_when_both_keys_pressed():
    """
    consume() must call pop() at most once even if both the device key and
    the global key are pressed simultaneously.
    """
    ctx, game = _make_pause_ctx(device_pause="stick_button_7", global_pause="escape")
    ctx.consume(_make_state(buttons={"stick_button_7": True, "escape": True}))
    game.app.state_manager.pop.assert_called_once()


def test_pause_ctx_clean_nulls_game():
    """
    clean() must set the game reference to None.
    """
    ctx, _ = _make_pause_ctx(global_pause="escape")
    ctx.clean()
    assert ctx._game is None


# ---------------------------------------------------------------------------
# _angle_to_slice helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "x, y, n_slices, expected",
    [
        (0.0, 1.0, 4, 0),  # straight up   → slice 0
        (1.0, 0.0, 4, 1),  # right          → slice 1
        (0.0, -1.0, 4, 2),  # down           → slice 2
        (-1.0, 0.0, 4, 3),  # left           → slice 3
        (0.0, 1.0, 8, 0),  # up, 8 slices   → slice 0
        (1.0, 0.0, 8, 2),  # right, 8 slices → slice 2
    ],
)
def test_angle_to_slice_cardinal_directions(x, y, n_slices, expected):
    """
    Cardinal directions must map to the expected slice index for common
    slice counts.
    """
    assert _angle_to_slice(x, y, n_slices) == expected


def test_angle_to_slice_wraps_near_top():
    """
    A direction just left of straight up must map to the last slice, not
    wrap beyond the valid range.
    """
    import math

    epsilon = 0.01
    x = -math.sin(epsilon)
    y = math.cos(epsilon)
    result = _angle_to_slice(x, y, 4)
    assert result == 3


# ---------------------------------------------------------------------------
# RadialMenuInputContext
# ---------------------------------------------------------------------------


def _make_radial_ctx(
    input_type="keyboard",
    device_bindings=None,
    radial_bindings=None,
    n_slices=4,
    trigger_hw="r",
    min_magnitude=0.3,
):
    """
    Build a RadialMenuInputContext with a fresh mock game.

    :param input_type: Active device type.
    :param device_bindings: Flight context device bindings.
    :param radial_bindings: ``radial_menu`` context bindings (direction keys /
        axes).
    :param n_slices: Number of radial slices.
    :param trigger_hw: Hardware name of the trigger button.
    :param min_magnitude: Dead-zone threshold.
    :return: Tuple of (RadialMenuInputContext, game_mock, on_select_mock).
    """
    game = MagicMock()
    game.app.bindings = {
        "input_type": input_type,
        "contexts": {
            "flight": {input_type: device_bindings or {}},
            "radial_menu": {input_type: radial_bindings or {}},
        },
        "global": {},
    }
    on_select = MagicMock()
    ctx = RadialMenuInputContext(
        game=game,
        n_slices=n_slices,
        on_select=on_select,
        trigger_hw_name=trigger_hw,
        min_magnitude=min_magnitude,
    )
    return ctx, game, on_select


def test_radial_ctx_no_selection_when_magnitude_below_threshold():
    """
    When the direction vector magnitude is below min_magnitude, _selected_slice
    must be None and on_select must not be called.
    """
    ctx, game, on_select = _make_radial_ctx(
        radial_bindings={
            "dir_up": "i",
            "dir_down": "k",
            "dir_left": "j",
            "dir_right": "l",
        },
        trigger_hw="r",
    )
    ctx.consume(_make_state())  # no keys held
    assert ctx._selected_slice is None
    on_select.assert_not_called()


def test_radial_ctx_selects_slice_on_held_direction_key():
    """
    Holding a direction key long enough to appear in repeats must produce a
    valid slice index.
    """
    ctx, _, _ = _make_radial_ctx(
        radial_bindings={
            "dir_up": "i",
            "dir_down": "k",
            "dir_left": "j",
            "dir_right": "l",
        },
    )
    ctx.consume(_make_state(repeats={"i": True}))  # pointing up → slice 0
    assert ctx._selected_slice == 0


def test_radial_ctx_selects_slice_on_pressed_direction_key():
    """
    A freshly pressed direction key (in state.buttons) must also produce a
    valid slice.
    """
    ctx, _, _ = _make_radial_ctx(
        radial_bindings={
            "dir_up": "i",
            "dir_down": "k",
            "dir_left": "j",
            "dir_right": "l",
        },
    )
    ctx.consume(_make_state(buttons={"l": True}))  # pointing right → slice 1
    assert ctx._selected_slice == 1


def test_radial_ctx_selects_slice_from_analog_axis():
    """
    When axis bindings are present, the direction must be read from state.axes.
    """
    ctx, _, _ = _make_radial_ctx(
        input_type="gamepad",
        radial_bindings={"axis_x": "right_x", "axis_y": "right_y"},
    )
    ctx.consume(_make_state(axes={"right_x": 0.0, "right_y": 0.8}))  # up → slice 0
    assert ctx._selected_slice == 0


def test_radial_ctx_calls_on_hover_every_frame():
    """
    on_hover must be called every frame with the current selected slice.
    """
    hover = MagicMock()
    game = MagicMock()
    game.app.bindings = {
        "input_type": "keyboard",
        "contexts": {
            "radial_menu": {"keyboard": {"dir_up": "i"}},
            "flight": {"keyboard": {}},
        },
        "global": {},
    }
    ctx = RadialMenuInputContext(
        game=game,
        n_slices=4,
        on_select=MagicMock(),
        trigger_hw_name="r",
        on_hover=hover,
    )
    ctx.consume(_make_state(repeats={"i": True}))
    hover.assert_called_once_with(0)


def test_radial_ctx_on_hover_none_when_no_direction():
    """
    on_hover must be called with None when the direction magnitude is below
    the threshold.
    """
    hover = MagicMock()
    game = MagicMock()
    game.app.bindings = {
        "input_type": "keyboard",
        "contexts": {"radial_menu": {"keyboard": {}}, "flight": {"keyboard": {}}},
        "global": {},
    }
    ctx = RadialMenuInputContext(
        game=game,
        n_slices=4,
        on_select=MagicMock(),
        trigger_hw_name="r",
        on_hover=hover,
    )
    ctx.consume(_make_state())
    hover.assert_called_once_with(None)


def test_radial_ctx_trigger_release_calls_on_select_with_slice():
    """
    Releasing the trigger button must call on_select with the selected slice
    index and call state_manager.pop().
    """
    ctx, game, on_select = _make_radial_ctx(
        radial_bindings={
            "dir_up": "i",
            "dir_down": "k",
            "dir_left": "j",
            "dir_right": "l",
        },
        trigger_hw="r",
    )
    ctx.consume(_make_state(repeats={"i": True}, releases={"r": True}))
    game.app.state_manager.pop.assert_called_once()
    on_select.assert_called_once_with(0)


def test_radial_ctx_trigger_release_calls_on_select_with_none_in_dead_zone():
    """
    Releasing the trigger with no direction held must call on_select(None).
    """
    ctx, game, on_select = _make_radial_ctx(trigger_hw="r")
    ctx.consume(_make_state(releases={"r": True}))
    game.app.state_manager.pop.assert_called_once()
    on_select.assert_called_once_with(None)


def test_radial_ctx_no_pop_while_trigger_held():
    """
    While the trigger is held (button or repeat but not release), on_select
    and state_manager.pop must not be called.
    """
    ctx, game, on_select = _make_radial_ctx(trigger_hw="r")
    ctx.consume(_make_state(buttons={"r": True}))
    ctx.consume(_make_state(repeats={"r": True}))
    game.app.state_manager.pop.assert_not_called()
    on_select.assert_not_called()


def test_radial_ctx_clean_nulls_references():
    """
    clean() must set game, on_select, and on_hover to None.
    """
    ctx, _, _ = _make_radial_ctx()
    ctx._on_hover = MagicMock()
    ctx.clean()
    assert ctx._game is None
    assert ctx._on_select is None
    assert ctx._on_hover is None
