from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from space_flight import THROTTLE_BOOST_VALUE
from space_flight.ui.input_context import (
    FlightInputContext,
    HyperspaceInputContext,
    InputContext,
    InputContextStack,
    PauseMenuInputContext,
    RadialMenuInputContext,
    angle_to_slice,
    bound_keys,
)
from space_flight.ui.input_reader import InputState

# ---------------------------------------------------------------------------
# Helpers — mock objects
# ---------------------------------------------------------------------------


def make_state(buttons=None, repeats=None, releases=None, axes=None):
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


def make_game(device_bindings=None, gamepad_bindings=None, joystick_bindings=None):
    """
    Build a minimal mock game whose app.bindings reflects the given config.

    :param device_bindings: Action → hardware-name dict for the keyboard.
    :param gamepad_bindings: Action → hardware-name dict for the gamepad.
    :param joystick_bindings: Action → hardware-name dict for the joystick.
    :return: MagicMock with app.bindings configured.
    """
    game = MagicMock()
    game.app.bindings = {
        "contexts": {
            "flight": {
                "keyboard": device_bindings or {},
                "gamepad": gamepad_bindings or {},
                "joystick": joystick_bindings or {},
            }
        },
    }
    game.game_time.get_time_step.return_value = 0.016
    return game


def make_flight_ctx(
    device_bindings=None, gamepad_bindings=None, joystick_bindings=None
):
    """
    Return a (FlightInputContext, game_mock, player_mock) triple.

    :param device_bindings: Keyboard bindings dict.
    :param gamepad_bindings: Gamepad bindings dict.
    :param joystick_bindings: Joystick bindings dict.
    :return: Tuple of (context, game, player).
    """
    game = make_game(device_bindings, gamepad_bindings, joystick_bindings)
    player = MagicMock()
    player.view_offset = [0.0, 0.0]
    player.is_dying = False
    ctx = FlightInputContext(game=game, player=player)
    return ctx, game, player


# ---------------------------------------------------------------------------
# Minimal InputContext stub for stack tests
# ---------------------------------------------------------------------------


class TrackingContext(InputContext):
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
# InputContext.key_label
# ---------------------------------------------------------------------------


def make_label_app(last_device="keyboard"):
    """
    :param last_device: The device the input reader saw last.
    :return: A mock app with keyboard and gamepad radial_menu bindings.
    """
    app = MagicMock()
    app.input_reader.last_device = last_device
    app.bindings = {
        "contexts": {
            "flight": {
                "keyboard": {"radial_menu": "r"},
                "gamepad": {"radial_menu": "gamepad_dpad_down"},
            }
        },
    }
    return app


def test_key_label_returns_uppercased_bound_key():
    app = make_label_app()
    assert InputContext.key_label(app, "flight", "radial_menu") == "R"


def test_key_label_uses_the_last_used_device():
    app = make_label_app(last_device="gamepad")
    assert InputContext.key_label(app, "flight", "radial_menu") == "GAMEPAD_DPAD_DOWN"


def test_key_label_defaults_to_keyboard_without_reader():
    """Headless apps have no input reader."""
    app = SimpleNamespace(bindings=make_label_app().bindings)
    assert InputContext.key_label(app, "flight", "radial_menu") == "R"


def test_key_label_falls_back_when_unbound():
    app = make_label_app(last_device="joystick")
    assert (
        InputContext.key_label(app, "flight", "radial_menu", "fallback") == "fallback"
    )
    assert InputContext.key_label(app, "flight", "radial_menu") == ""


# ---------------------------------------------------------------------------
# bound_keys
# ---------------------------------------------------------------------------


def test_bound_keys_collects_every_device():
    bindings = make_game(
        device_bindings={"fire": "space"},
        gamepad_bindings={"fire": "gamepad_lshoulder"},
        joystick_bindings={"fire": "stick_button_1"},
    ).app.bindings
    assert bound_keys(bindings, "flight", "fire") == {
        "space",
        "gamepad_lshoulder",
        "stick_button_1",
    }


def test_bound_keys_skips_unbound_devices_and_non_keys():
    bindings = make_game(
        device_bindings={"fire": "space"},
        gamepad_bindings={"invert_yaw": True},
    ).app.bindings
    assert bound_keys(bindings, "flight", "fire") == {"space"}
    assert bound_keys(bindings, "flight", "invert_yaw") == frozenset()
    assert bound_keys(bindings, "unknown", "fire") == frozenset()


# ---------------------------------------------------------------------------
# InputContextStack
# ---------------------------------------------------------------------------


def test_stack_dispatch_on_empty_is_noop(stack):
    """
    Calling dispatch() on an empty stack must not raise.
    """
    stack.dispatch(make_state())  # must not raise


def test_stack_push_calls_on_activate(stack):
    """
    push() must call on_activate on the pushed context.
    """
    ctx = TrackingContext()
    stack.push(ctx)
    assert "activate" in ctx.calls


def test_stack_push_deactivates_previous_top(stack):
    """
    push() must deactivate the context that was previously on top before
    activating the new one.
    """
    ctx_a = TrackingContext("a")
    ctx_b = TrackingContext("b")
    stack.push(ctx_a)
    ctx_a.calls.clear()
    stack.push(ctx_b)
    assert ctx_a.calls[0] == "deactivate"
    assert "activate" in ctx_b.calls


def test_stack_pop_calls_on_deactivate_and_clean(stack):
    """
    pop() must call on_deactivate then clean on the removed context.
    """
    ctx = TrackingContext()
    stack.push(ctx)
    ctx.calls.clear()
    stack.pop()
    assert ctx.calls == ["deactivate", "clean"]


def test_stack_pop_reactivates_context_below(stack):
    """
    pop() must call on_activate on the context that becomes the new top.
    """
    ctx_a = TrackingContext("a")
    ctx_b = TrackingContext("b")
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
    ctx_a = TrackingContext("a")
    ctx_b = TrackingContext("b")
    stack.push(ctx_a)
    stack.push(ctx_b)
    ctx_a.calls.clear()
    ctx_b.calls.clear()
    stack.dispatch(make_state())
    assert "consume" in ctx_b.calls
    assert "consume" not in ctx_a.calls


def test_stack_dispatch_after_pop_reaches_new_top(stack):
    """
    After pop(), dispatch() must route to the context that is now on top.
    """
    ctx_a = TrackingContext("a")
    ctx_b = TrackingContext("b")
    stack.push(ctx_a)
    stack.push(ctx_b)
    stack.pop()
    ctx_a.calls.clear()
    stack.dispatch(make_state())
    assert "consume" in ctx_a.calls


def test_stack_clean_removes_all_contexts(stack):
    """
    clean() must pop and clean every context in the stack.
    """
    ctx_a = TrackingContext("a")
    ctx_b = TrackingContext("b")
    stack.push(ctx_a)
    stack.push(ctx_b)
    stack.clean()
    assert "clean" in ctx_a.calls
    assert "clean" in ctx_b.calls
    stack.dispatch(make_state())  # stack now empty — must not raise


def test_stack_clean_calls_on_deactivate_before_clean(stack):
    """
    clean() must call on_deactivate before clean on every removed context.
    """
    ctx = TrackingContext()
    stack.push(ctx)
    ctx.calls.clear()
    stack.clean()
    assert ctx.calls.index("deactivate") < ctx.calls.index("clean")


# ---------------------------------------------------------------------------
# FlightInputContext — binding helpers
# ---------------------------------------------------------------------------


def test_flight_ctx_pressed_detects_device_binding():
    """
    pressed must return True when the device-specific hardware key is in
    state.buttons.
    """
    ctx, _, _ = make_flight_ctx(device_bindings={"fire": "space"})
    state = make_state(buttons={"space": True})
    assert ctx.pressed(state, "fire") is True


def test_flight_ctx_pressed_returns_false_when_not_pressed():
    """
    pressed must return False when the bound key is absent from state.buttons.
    """
    ctx, _, _ = make_flight_ctx(device_bindings={"fire": "space"})
    state = make_state(buttons={})
    assert ctx.pressed(state, "fire") is False


def test_flight_ctx_pressed_detects_any_device_binding():
    """
    pressed must return True when the action's key on any device is pressed.
    """
    ctx, _, _ = make_flight_ctx(
        device_bindings={"pause": "escape"},
        gamepad_bindings={"pause": "gamepad_start"},
    )
    assert ctx.pressed(make_state(buttons={"escape": True}), "pause") is True
    assert ctx.pressed(make_state(buttons={"gamepad_start": True}), "pause") is True


def test_flight_ctx_held_detects_device_binding():
    """
    held must return True when the device-specific key is in state.repeats.
    """
    ctx, _, _ = make_flight_ctx(device_bindings={"fire": "space"})
    state = make_state(repeats={"space": True})
    assert ctx.held(state, "fire") is True


def test_flight_ctx_held_detects_other_device_binding():
    """
    held must return True when another device's key is in state.repeats.
    """
    ctx, _, _ = make_flight_ctx(
        device_bindings={"fire": "space"},
        joystick_bindings={"fire": "stick_button_1"},
    )
    state = make_state(repeats={"stick_button_1": True})
    assert ctx.held(state, "fire") is True


def test_flight_ctx_released_detects_device_binding():
    """
    released must return True when the device-specific key is in
    state.releases.
    """
    ctx, _, _ = make_flight_ctx(device_bindings={"boost_off": "b"})
    state = make_state(releases={"b": True})
    assert ctx.released(state, "boost_off") is True


def test_flight_ctx_released_detects_other_device_binding():
    """
    released must return True when another device's key is in state.releases.
    """
    ctx, _, _ = make_flight_ctx(
        device_bindings={"boost_off": "b"},
        gamepad_bindings={"boost_off": "gamepad_rshoulder"},
    )
    state = make_state(releases={"gamepad_rshoulder": True})
    assert ctx.released(state, "boost_off") is True


def test_flight_ctx_active_true_on_press():
    """
    active must return True when the key is freshly pressed (in buttons).
    """
    ctx, _, _ = make_flight_ctx(device_bindings={"fire": "space"})
    state = make_state(buttons={"space": True})
    assert ctx.active(state, "fire") is True


def test_flight_ctx_active_true_while_held():
    """
    active must return True when the key is being held (in repeats).
    """
    ctx, _, _ = make_flight_ctx(device_bindings={"fire": "space"})
    state = make_state(repeats={"space": True})
    assert ctx.active(state, "fire") is True


def test_flight_ctx_active_false_when_not_pressed_or_held():
    """
    active must return False when the key is neither in buttons nor repeats.
    """
    ctx, _, _ = make_flight_ctx(device_bindings={"fire": "space"})
    state = make_state()
    assert ctx.active(state, "fire") is False


def test_flight_ctx_handle_actions_fires_on_fire_binding():
    """
    handle_actions must fire the laser cannon while the fire binding is active.
    """
    ctx, _, player = make_flight_ctx(
        device_bindings={"fire": "space", "fire_secondary": "x"}
    )
    ctx.handle_actions(make_state(buttons={"space": True}))
    player.pawn.laser_cannon.fire.assert_called_once()
    player.pawn.fire_secondary.assert_not_called()


def test_flight_ctx_handle_actions_fires_secondary_on_fire_secondary_binding():
    """
    handle_actions must fire the secondary weapon while the fire_secondary
    binding is active, without firing the guns.
    """
    ctx, _, player = make_flight_ctx(
        device_bindings={"fire": "space", "fire_secondary": "x"}
    )
    ctx.handle_actions(make_state(buttons={"x": True}))
    player.pawn.fire_secondary.assert_called_once()
    player.pawn.laser_cannon.fire.assert_not_called()


def test_flight_ctx_handle_actions_fires_secondary_while_held():
    """
    Holding fire_secondary keeps firing (the launcher's reload limits the rate).
    """
    ctx, _, player = make_flight_ctx(device_bindings={"fire_secondary": "x"})
    ctx.handle_actions(make_state(repeats={"x": True}))
    player.pawn.fire_secondary.assert_called_once()


def test_flight_ctx_handle_actions_cycles_secondary_on_press_only():
    """
    cycle_secondary selects the next secondary weapon once per press, not while
    held.
    """
    ctx, _, player = make_flight_ctx(device_bindings={"cycle_secondary": "c"})
    ctx.handle_actions(make_state(buttons={"c": True}))
    player.pawn.cycle_secondary.assert_called_once()
    ctx.handle_actions(make_state(repeats={"c": True}))
    player.pawn.cycle_secondary.assert_called_once()


def test_flight_ctx_handle_actions_drops_flare_on_drop_flare_binding():
    """
    handle_actions must drop a flare while the drop_flare binding is active.
    """
    ctx, _, player = make_flight_ctx(device_bindings={"drop_flare": "f"})
    ctx.handle_actions(make_state(buttons={"f": True}))
    player.pawn.drop_flare.assert_called_once()
    player.pawn.fire_secondary.assert_not_called()


def test_flight_ctx_handle_actions_ignores_weapons_and_targeting_while_dying():
    """
    While the player is dying its pawn has left the interactions, so firing
    (auto-aim) or targeting would look it up and crash: only pause still works.
    """
    ctx, game, player = make_flight_ctx(
        device_bindings={
            "fire": "space",
            "fire_secondary": "x",
            "cycle_secondary": "c",
            "drop_flare": "f",
            "loop_target": ",",
            "point_target": "t",
            "pause": "p",
        }
    )
    player.is_dying = True
    ctx.handle_actions(
        make_state(
            buttons={
                "space": True,
                "x": True,
                "c": True,
                "f": True,
                ",": True,
                "t": True,
                "p": True,
            }
        )
    )
    player.pawn.laser_cannon.fire.assert_not_called()
    player.pawn.fire_secondary.assert_not_called()
    player.pawn.cycle_secondary.assert_not_called()
    player.pawn.drop_flare.assert_not_called()
    player.loop_target.assert_not_called()
    player.point_target.assert_not_called()
    game.set_pause.assert_called_once()


@pytest.mark.parametrize(
    "action, mode",
    [
        ("energy_engines", "engines"),
        ("energy_lasers", "lasers"),
        ("energy_shields", "shields"),
        ("energy_balanced", "balanced"),
    ],
)
def test_flight_ctx_handle_actions_sets_energy_mode(action, mode):
    """
    The energy actions redirect the pawn's power to their system, or back to
    balanced.
    """
    ctx, _, player = make_flight_ctx(device_bindings={action: "1"})
    ctx.handle_actions(make_state(buttons={"1": True}))
    player.pawn.energy.set_mode.assert_called_once_with(mode)
    player.pawn.energy.cycle_mode.assert_not_called()


def test_flight_ctx_handle_actions_cycles_energy_mode_on_press_only():
    """
    cycle_energy cycles the distribution once per press, not while held.
    """
    ctx, _, player = make_flight_ctx(device_bindings={"cycle_energy": "y"})
    ctx.handle_actions(make_state(repeats={"y": True}))
    player.pawn.energy.cycle_mode.assert_not_called()
    ctx.handle_actions(make_state(buttons={"y": True}))
    player.pawn.energy.cycle_mode.assert_called_once()
    player.pawn.energy.set_mode.assert_not_called()


def test_flight_ctx_handle_actions_no_ordnance_when_idle():
    """
    handle_actions must not launch ordnance when their bindings are inactive.
    """
    ctx, _, player = make_flight_ctx(
        device_bindings={
            "fire": "space",
            "fire_secondary": "x",
            "cycle_secondary": "c",
            "drop_flare": "f",
        }
    )
    ctx.handle_actions(make_state(buttons={}))
    player.pawn.fire_secondary.assert_not_called()
    player.pawn.cycle_secondary.assert_not_called()
    player.pawn.drop_flare.assert_not_called()


def test_flight_ctx_axis_returns_value():
    """
    axis must return the device's axis value from state.axes for the action.
    """
    ctx, _, _ = make_flight_ctx(gamepad_bindings={"throttle": "right_trigger"})
    state = make_state(axes={"right_trigger": 0.8})
    assert ctx.axis(state, "gamepad", "throttle") == pytest.approx(0.8)


def test_flight_ctx_axis_applies_invert():
    ctx, _, _ = make_flight_ctx(gamepad_bindings={"yaw": "right_x", "invert_yaw": True})
    state = make_state(axes={"right_x": 0.5})
    assert ctx.axis(state, "gamepad", "yaw") == pytest.approx(-0.5)


def test_flight_ctx_axis_returns_none_for_unknown_action():
    """
    axis must return None when the action has no binding on the device.
    """
    ctx, _, _ = make_flight_ctx()
    state = make_state(axes={"right_trigger": 0.8})
    assert ctx.axis(state, "gamepad", "throttle") is None


def test_flight_ctx_axis_returns_none_for_disconnected_device():
    """
    A device that is not connected reports no axes: axis must return None.
    """
    ctx, _, _ = make_flight_ctx(gamepad_bindings={"throttle": "right_trigger"})
    assert ctx.axis(make_state(), "gamepad", "throttle") is None


# ---------------------------------------------------------------------------
# FlightInputContext — flight axes
# ---------------------------------------------------------------------------

KEYBOARD_FLIGHT = {
    "throttle_up": "arrow_up",
    "throttle_down": "arrow_down",
    "yaw_left": "q",
}
GAMEPAD_FLIGHT = {"throttle": "right_trigger", "yaw": "right_x"}
JOYSTICK_FLIGHT = {"throttle": "throttle", "yaw": "yaw"}


def make_axes_ctx():
    """
    :return: A flight context with keyboard, gamepad and joystick axes bound.
    """
    ctx, _, _ = make_flight_ctx(
        device_bindings=KEYBOARD_FLIGHT,
        gamepad_bindings=GAMEPAD_FLIGHT,
        joystick_bindings=JOYSTICK_FLIGHT,
    )
    return ctx


def test_flight_axes_sum_rates_across_devices():
    ctx = make_axes_ctx()
    _, yaw, _, _ = ctx.flight_axes(make_state(axes={"right_x": 0.2, "yaw": 0.3}))
    assert yaw == pytest.approx(0.5)


def test_flight_axes_clamp_summed_rates():
    ctx = make_axes_ctx()
    _, yaw, _, _ = ctx.flight_axes(make_state(axes={"right_x": 0.8, "yaw": 0.7}))
    assert yaw == pytest.approx(1.0)


def test_flight_axes_add_smoothed_keyboard_rate():
    ctx = make_axes_ctx()
    _, yaw, _, _ = ctx.flight_axes(make_state(repeats={"q": True}))
    assert 0.0 < yaw < 1.0
    _, yaw_with_stick, _, _ = ctx.flight_axes(
        make_state(repeats={"q": True}, axes={"yaw": -0.2})
    )
    assert yaw_with_stick == pytest.approx(ctx.yaw_smoothed - 0.2)


def test_throttle_ignores_analog_resting_where_first_seen():
    """
    A throttle lever left forward at spawn does not take the throttle.
    """
    ctx = make_axes_ctx()
    throttle, *_ = ctx.flight_axes(make_state(axes={"throttle": 0.8}))
    assert throttle == pytest.approx(0.0)
    assert ctx.throttle_owner is None


def test_throttle_analog_takes_over_once_moved():
    ctx = make_axes_ctx()
    ctx.flight_axes(make_state(axes={"right_trigger": 0.0}))
    throttle, *_ = ctx.flight_axes(make_state(axes={"right_trigger": 0.6}))
    assert throttle == pytest.approx(0.6)
    assert ctx.throttle_owner == "gamepad"


def test_throttle_analog_owner_follows_small_moves():
    ctx = make_axes_ctx()
    ctx.flight_axes(make_state(axes={"right_trigger": 0.0}))
    ctx.flight_axes(make_state(axes={"right_trigger": 0.6}))
    throttle, *_ = ctx.flight_axes(make_state(axes={"right_trigger": 0.62}))
    assert throttle == pytest.approx(0.62)


def test_throttle_keyboard_steps_from_analog_value():
    """
    The keyboard takes the throttle over from where the analog left it.
    """
    ctx = make_axes_ctx()
    ctx.flight_axes(make_state(axes={"right_trigger": 0.0}))
    ctx.flight_axes(make_state(axes={"right_trigger": 0.6}))
    throttle, *_ = ctx.flight_axes(
        make_state(repeats={"arrow_up": True}, axes={"right_trigger": 0.6})
    )
    assert throttle == pytest.approx(0.605)
    assert ctx.throttle_owner == "keyboard"


def test_throttle_analog_does_not_retake_without_moving():
    """
    Once the keyboard owns the throttle, a still analog does not take it back.
    """
    ctx = make_axes_ctx()
    ctx.flight_axes(make_state(axes={"right_trigger": 0.0}))
    ctx.flight_axes(make_state(axes={"right_trigger": 0.6}))
    ctx.flight_axes(
        make_state(repeats={"arrow_down": True}, axes={"right_trigger": 0.6})
    )
    throttle, *_ = ctx.flight_axes(make_state(axes={"right_trigger": 0.62}))
    assert throttle == pytest.approx(0.595)
    assert ctx.throttle_owner == "keyboard"


def test_throttle_analog_retakes_once_moved_again():
    ctx = make_axes_ctx()
    ctx.flight_axes(make_state(axes={"right_trigger": 0.0}))
    ctx.flight_axes(make_state(axes={"right_trigger": 0.6}))
    ctx.flight_axes(
        make_state(repeats={"arrow_down": True}, axes={"right_trigger": 0.6})
    )
    throttle, *_ = ctx.flight_axes(make_state(axes={"right_trigger": 0.0}))
    assert throttle == pytest.approx(0.0)
    assert ctx.throttle_owner == "gamepad"


def test_throttle_kept_when_owner_disconnects():
    ctx = make_axes_ctx()
    ctx.flight_axes(make_state(axes={"throttle": 0.0}))
    ctx.flight_axes(make_state(axes={"throttle": 0.7}))
    throttle, *_ = ctx.flight_axes(make_state())
    assert throttle == pytest.approx(0.7)


def test_throttle_keyboard_clamped_to_unit_range():
    ctx = make_axes_ctx()
    throttle, *_ = ctx.flight_axes(make_state(repeats={"arrow_down": True}))
    assert throttle == pytest.approx(0.0)


def test_throttle_boost_overrides_owner():
    ctx = make_axes_ctx()
    ctx.is_boost = True
    throttle, *_ = ctx.flight_axes(make_state(axes={"right_trigger": 0.3}))
    assert throttle == pytest.approx(THROTTLE_BOOST_VALUE)


def test_flight_ctx_clean_nulls_references():
    """
    clean() must set the game and player references to None so the context
    does not hold live objects after removal from the stack.
    """
    ctx, _, _ = make_flight_ctx()
    ctx.clean()
    assert ctx.game is None
    assert ctx.player is None


# ---------------------------------------------------------------------------
# PauseMenuInputContext
# ---------------------------------------------------------------------------


def make_pause_ctx(keyboard_pause=None, joystick_pause=None):
    """
    Return a PauseMenuInputContext backed by a mock game.

    :param keyboard_pause: Hardware key mapped to pause on the keyboard.
    :param joystick_pause: Hardware key mapped to pause on the joystick.
    :return: Tuple of (PauseMenuInputContext, game_mock).
    """
    game = make_game(
        device_bindings={"pause": keyboard_pause} if keyboard_pause else {},
        joystick_bindings={"pause": joystick_pause} if joystick_pause else {},
    )
    ctx = PauseMenuInputContext(app=game.app)
    return ctx, game


def test_pause_ctx_consume_pops_state_manager_on_device_key():
    """
    consume() must call app.state_manager.pop() when the device-specific
    pause key is in state.buttons.
    """
    ctx, game = make_pause_ctx(joystick_pause="stick_button_7")
    ctx.consume(make_state(buttons={"stick_button_7": True}))
    game.app.state_manager.pop.assert_called_once()


def test_pause_ctx_consume_pops_state_manager_on_other_device_key():
    """
    consume() must call app.state_manager.pop() when another device's pause
    key (escape) is in state.buttons.
    """
    ctx, game = make_pause_ctx(keyboard_pause="escape", joystick_pause="stick_button_7")
    ctx.consume(make_state(buttons={"escape": True}))
    game.app.state_manager.pop.assert_called_once()


def test_pause_ctx_consume_does_not_pop_when_no_key_pressed():
    """
    consume() must not call app.state_manager.pop() when neither pause key
    is present in state.buttons.
    """
    ctx, game = make_pause_ctx(keyboard_pause="escape", joystick_pause="stick_button_7")
    ctx.consume(make_state(buttons={}))
    game.app.state_manager.pop.assert_not_called()


def test_pause_ctx_consume_pops_only_once_when_both_keys_pressed():
    """
    consume() must call pop() at most once even if the pause keys of two
    devices are pressed simultaneously.
    """
    ctx, game = make_pause_ctx(keyboard_pause="escape", joystick_pause="stick_button_7")
    ctx.consume(make_state(buttons={"stick_button_7": True, "escape": True}))
    game.app.state_manager.pop.assert_called_once()


def test_pause_ctx_clean_nulls_game():
    """
    clean() must set the game reference to None.
    """
    ctx, _ = make_pause_ctx(keyboard_pause="escape")
    ctx.clean()
    assert ctx.game is None


# ---------------------------------------------------------------------------
# angle_to_slice helper
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
    assert angle_to_slice(x, y, n_slices) == expected


def test_angle_to_slice_wraps_near_top():
    """
    A direction just left of straight up must map to the last slice, not
    wrap beyond the valid range.
    """
    import math

    epsilon = 0.01
    x = -math.sin(epsilon)
    y = math.cos(epsilon)
    result = angle_to_slice(x, y, 4)
    assert result == 3


# ---------------------------------------------------------------------------
# RadialMenuInputContext
# ---------------------------------------------------------------------------


def make_radial_ctx(
    radial_bindings=None,
    gamepad_radial_bindings=None,
    n_slices=4,
    trigger_hw="r",
    min_magnitude=0.3,
):
    """
    Build a RadialMenuInputContext with a fresh mock game.

    :param radial_bindings: Keyboard radial_menu context bindings (direction
        keys).
    :param gamepad_radial_bindings: Gamepad radial_menu context bindings
        (axes).
    :param n_slices: Number of radial slices.
    :param trigger_hw: Hardware name(s) of the trigger button(s).
    :param min_magnitude: Dead-zone threshold.
    :return: Tuple of (RadialMenuInputContext, game_mock, on_select_mock).
    """
    game = MagicMock()
    game.app.bindings = {
        "contexts": {
            "radial_menu": {
                "keyboard": radial_bindings or {},
                "gamepad": gamepad_radial_bindings or {},
            },
        },
    }
    on_select = MagicMock()
    ctx = RadialMenuInputContext(
        game=game,
        n_slices=n_slices,
        on_select=on_select,
        trigger_hw_names=frozenset(
            [trigger_hw] if isinstance(trigger_hw, str) else trigger_hw
        ),
        min_magnitude=min_magnitude,
    )
    return ctx, game, on_select


def test_radial_ctx_no_selection_when_magnitude_below_threshold():
    """
    When the direction vector magnitude is below min_magnitude, selected_slice
    must be None and on_select must not be called.
    """
    ctx, game, on_select = make_radial_ctx(
        radial_bindings={
            "dir_up": "i",
            "dir_down": "k",
            "dir_left": "j",
            "dir_right": "l",
        },
        trigger_hw="r",
    )
    ctx.consume(make_state())  # no keys held
    assert ctx.selected_slice is None
    on_select.assert_not_called()


def test_radial_ctx_selects_slice_on_held_direction_key():
    """
    Holding a direction key long enough to appear in repeats must produce a
    valid slice index.
    """
    ctx, _, _ = make_radial_ctx(
        radial_bindings={
            "dir_up": "i",
            "dir_down": "k",
            "dir_left": "j",
            "dir_right": "l",
        },
    )
    ctx.consume(make_state(repeats={"i": True}))  # pointing up → slice 0
    assert ctx.selected_slice == 0


def test_radial_ctx_selects_slice_on_pressed_direction_key():
    """
    A freshly pressed direction key (in state.buttons) must also produce a
    valid slice.
    """
    ctx, _, _ = make_radial_ctx(
        radial_bindings={
            "dir_up": "i",
            "dir_down": "k",
            "dir_left": "j",
            "dir_right": "l",
        },
    )
    ctx.consume(make_state(buttons={"l": True}))  # pointing right → slice 1
    assert ctx.selected_slice == 1


def test_radial_ctx_selects_slice_from_analog_axis():
    """
    When axis bindings are present, the direction must be read from state.axes.
    """
    ctx, _, _ = make_radial_ctx(
        gamepad_radial_bindings={"axis_x": "right_x", "axis_y": "right_y"},
    )
    ctx.consume(make_state(axes={"right_x": 0.0, "right_y": 0.8}))  # up → slice 0
    assert ctx.selected_slice == 0


def test_radial_ctx_sums_device_directions():
    """
    Keys and stick point together: right key + stick up → up-right.
    """
    ctx, _, _ = make_radial_ctx(
        radial_bindings={"dir_right": "l"},
        gamepad_radial_bindings={"axis_x": "right_x", "axis_y": "right_y"},
        n_slices=8,
    )
    ctx.consume(make_state(repeats={"l": True}, axes={"right_y": 1.0}))
    assert ctx.selected_slice == 1


def test_radial_ctx_any_trigger_release_closes():
    ctx, game, on_select = make_radial_ctx(trigger_hw=("r", "gamepad_dpad_down"))
    ctx.consume(make_state(releases={"gamepad_dpad_down": True}))
    game.app.state_manager.pop.assert_called_once()
    on_select.assert_called_once_with(None)


def test_radial_ctx_calls_on_hover_every_frame():
    """
    on_hover must be called every frame with the current selected slice.
    """
    hover = MagicMock()
    game = MagicMock()
    game.app.bindings = {
        "contexts": {"radial_menu": {"keyboard": {"dir_up": "i"}}},
    }
    ctx = RadialMenuInputContext(
        game=game,
        n_slices=4,
        on_select=MagicMock(),
        trigger_hw_names=frozenset({"r"}),
        on_hover=hover,
    )
    ctx.consume(make_state(repeats={"i": True}))
    hover.assert_called_once_with(0)


def test_radial_ctx_on_hover_none_when_no_direction():
    """
    on_hover must be called with None when the direction magnitude is below
    the threshold.
    """
    hover = MagicMock()
    game = MagicMock()
    game.app.bindings = {"contexts": {"radial_menu": {"keyboard": {}}}}
    ctx = RadialMenuInputContext(
        game=game,
        n_slices=4,
        on_select=MagicMock(),
        trigger_hw_names=frozenset({"r"}),
        on_hover=hover,
    )
    ctx.consume(make_state())
    hover.assert_called_once_with(None)


def test_radial_ctx_trigger_release_calls_on_select_with_slice():
    """
    Releasing the trigger button must call on_select with the selected slice
    index and call state_manager.pop().
    """
    ctx, game, on_select = make_radial_ctx(
        radial_bindings={
            "dir_up": "i",
            "dir_down": "k",
            "dir_left": "j",
            "dir_right": "l",
        },
        trigger_hw="r",
    )
    ctx.consume(make_state(repeats={"i": True}, releases={"r": True}))
    game.app.state_manager.pop.assert_called_once()
    on_select.assert_called_once_with(0)


def test_radial_ctx_trigger_release_calls_on_select_with_none_in_dead_zone():
    """
    Releasing the trigger with no direction held must call on_select(None).
    """
    ctx, game, on_select = make_radial_ctx(trigger_hw="r")
    ctx.consume(make_state(releases={"r": True}))
    game.app.state_manager.pop.assert_called_once()
    on_select.assert_called_once_with(None)


def test_radial_ctx_selection_survives_direction_release_before_trigger():
    """
    Letting go of the direction before the trigger must keep the last slice:
    the dead-zone frame in between must not clear the selection.
    """
    ctx, game, on_select = make_radial_ctx(
        radial_bindings={"dir_up": "i", "dir_right": "l"},
        trigger_hw="r",
    )
    hover = MagicMock()
    ctx.on_hover = hover
    ctx.consume(make_state(buttons={"r": True}, repeats={"i": True}))
    ctx.consume(make_state(buttons={"r": True}))
    hover.assert_called_with(0)
    ctx.consume(make_state(releases={"r": True}))
    on_select.assert_called_once_with(0)


def test_radial_ctx_new_direction_replaces_latched_selection():
    """
    Pointing at another slice after a latched one must switch the selection.
    """
    ctx, _, on_select = make_radial_ctx(
        radial_bindings={"dir_up": "i", "dir_right": "l"},
        trigger_hw="r",
    )
    ctx.consume(make_state(repeats={"i": True}))
    ctx.consume(make_state(repeats={"l": True}))
    ctx.consume(make_state(releases={"r": True}))
    on_select.assert_called_once_with(1)


def test_radial_ctx_no_pop_while_trigger_held():
    """
    While the trigger is held (button or repeat but not release), on_select
    and state_manager.pop must not be called.
    """
    ctx, game, on_select = make_radial_ctx(trigger_hw="r")
    ctx.consume(make_state(buttons={"r": True}))
    ctx.consume(make_state(repeats={"r": True}))
    game.app.state_manager.pop.assert_not_called()
    on_select.assert_not_called()


def test_radial_ctx_clean_nulls_references():
    """
    clean() must set game, on_select, and on_hover to None.
    """
    ctx, _, _ = make_radial_ctx()
    ctx.on_hover = MagicMock()
    ctx.clean()
    assert ctx.game is None
    assert ctx.on_select is None
    assert ctx.on_hover is None


# ---------------------------------------------------------------------------
# refresh_bindings / refresh_all_bindings
# ---------------------------------------------------------------------------


class _RefreshTrackingContext(InputContext):
    """InputContext stub that records refresh_bindings calls."""

    def __init__(self):
        self.refresh_calls = []

    def consume(self, state):
        pass

    def refresh_bindings(self, app):
        self.refresh_calls.append(app)


def test_refresh_all_bindings_calls_refresh_on_every_context(stack):
    """
    refresh_all_bindings must call refresh_bindings(app) on every context
    currently in the stack, including those not on top.
    """
    ctx_a = _RefreshTrackingContext()
    ctx_b = _RefreshTrackingContext()
    stack.push(ctx_a)
    stack.push(ctx_b)
    sentinel = object()
    stack.refresh_all_bindings(sentinel)
    assert ctx_a.refresh_calls == [sentinel]
    assert ctx_b.refresh_calls == [sentinel]


def test_refresh_all_bindings_on_empty_stack_does_not_raise(stack):
    """
    refresh_all_bindings on an empty stack must silently do nothing.
    """
    stack.refresh_all_bindings(MagicMock())  # must not raise


def test_flight_ctx_refresh_bindings_new_key_triggers_action():
    """
    After refresh_bindings with a new app.bindings that remaps 'fire' from
    'space' to 'f', pressing 'f' must return True for the fire action.
    """
    ctx, game, _ = make_flight_ctx(device_bindings={"fire": "space"})
    game.app.bindings["contexts"]["flight"]["keyboard"]["fire"] = "f"
    ctx.refresh_bindings(game.app)
    state = make_state(buttons={"f": True})
    assert ctx.pressed(state, "fire") is True


def test_flight_ctx_refresh_bindings_old_key_no_longer_triggers():
    """
    After refresh_bindings, the previously mapped key ('space') must no longer
    trigger the fire action.
    """
    ctx, game, _ = make_flight_ctx(device_bindings={"fire": "space"})
    game.app.bindings["contexts"]["flight"]["keyboard"]["fire"] = "f"
    ctx.refresh_bindings(game.app)
    state = make_state(buttons={"space": True})
    assert ctx.pressed(state, "fire") is False


def test_pause_ctx_refresh_bindings_new_key_triggers_pop():
    """
    After refresh_bindings with a new pause key, pressing the new key must
    call state_manager.pop().
    """
    ctx, game = make_pause_ctx(keyboard_pause="escape")
    game.app.bindings["contexts"]["flight"]["keyboard"]["pause"] = "p"
    ctx.refresh_bindings(game.app)
    ctx.consume(make_state(buttons={"p": True}))
    game.app.state_manager.pop.assert_called_once()


def test_pause_ctx_refresh_bindings_old_key_no_longer_triggers():
    """
    After refresh_bindings, the previously mapped pause key must no longer
    trigger state_manager.pop().
    """
    ctx, game = make_pause_ctx(keyboard_pause="escape")
    game.app.bindings["contexts"]["flight"]["keyboard"]["pause"] = "p"
    ctx.refresh_bindings(game.app)
    ctx.consume(make_state(buttons={"escape": True}))
    game.app.state_manager.pop.assert_not_called()


# ---------------------------------------------------------------------------
# HyperspaceInputContext
# ---------------------------------------------------------------------------


def make_hyperspace_ctx(device_key=None, gamepad_key=None):
    """
    Return a (HyperspaceInputContext, app_mock, on_trigger_mock) triple.

    :param device_key: hardware name bound to drop_hyperspace on the keyboard
    :param gamepad_key: hardware name bound to drop_hyperspace on the gamepad
    :return: tuple of (context, app, on_trigger)
    """
    app = MagicMock()
    app.bindings = {
        "contexts": {
            "hyperspace": {
                "keyboard": {"drop_hyperspace": device_key} if device_key else {},
                "gamepad": {"drop_hyperspace": gamepad_key} if gamepad_key else {},
            }
        },
    }
    on_trigger = MagicMock(return_value=True)
    ctx = HyperspaceInputContext(app=app, on_trigger=on_trigger)
    return ctx, app, on_trigger


def test_hyperspace_ctx_triggers_on_bound_key():
    ctx, _, on_trigger = make_hyperspace_ctx(device_key="space")
    ctx.consume(make_state(buttons={"space": True}))
    on_trigger.assert_called_once()
    assert ctx.triggered


def test_hyperspace_ctx_triggers_only_once():
    """A held/repeated key must fire the jump exactly once."""
    ctx, _, on_trigger = make_hyperspace_ctx(device_key="space")
    ctx.consume(make_state(buttons={"space": True}))
    ctx.consume(make_state(buttons={"space": True}))
    on_trigger.assert_called_once()


def test_hyperspace_ctx_not_latched_when_trigger_rejected():
    """A press the overlay refuses (not waiting yet) must not use up the trigger."""
    ctx, _, on_trigger = make_hyperspace_ctx(device_key="space")
    on_trigger.return_value = False
    ctx.consume(make_state(buttons={"space": True}))
    assert not ctx.triggered
    on_trigger.return_value = True
    ctx.consume(make_state(buttons={"space": True}))
    assert ctx.triggered
    ctx.consume(make_state(buttons={"space": True}))
    assert on_trigger.call_count == 2


def test_hyperspace_ctx_ignores_unbound_keys():
    ctx, _, on_trigger = make_hyperspace_ctx(device_key="space")
    ctx.consume(make_state(buttons={"enter": True}))
    on_trigger.assert_not_called()
    assert not ctx.triggered


def test_hyperspace_ctx_honours_every_device_binding():
    """The drop key of any device works."""
    ctx, _, on_trigger = make_hyperspace_ctx(
        device_key="space", gamepad_key="gamepad_lshoulder"
    )
    ctx.consume(make_state(buttons={"gamepad_lshoulder": True}))
    on_trigger.assert_called_once()


def test_hyperspace_ctx_refresh_bindings():
    """refresh_bindings re-resolves the drop key after a remap."""
    ctx, app, on_trigger = make_hyperspace_ctx(device_key="space")
    app.bindings["contexts"]["hyperspace"]["keyboard"]["drop_hyperspace"] = "enter"
    ctx.refresh_bindings(app)
    ctx.consume(make_state(buttons={"space": True}))
    on_trigger.assert_not_called()
    ctx.consume(make_state(buttons={"enter": True}))
    on_trigger.assert_called_once()
