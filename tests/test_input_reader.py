from unittest.mock import MagicMock

import pytest
from panda3d.core import InputDevice

from space_flight.ui.input_reader import (
    MENU_BUTTONS,
    CompositeInputReader,
    GamepadReader,
    InputReader,
    InputState,
    JoystickReader,
)

# ---------------------------------------------------------------------------
# Stub — exercises InputReader.poll() without any Panda3D initialisation
# ---------------------------------------------------------------------------


class _StubReader(InputReader):
    """
    Concrete InputReader whose Panda3D-dependent __init__ is bypassed.

    Call poll() normally; control what read_all_buttons returns by setting
    self.hw_state, and what axes are produced by setting self.hw_axes.
    Safety-net events can be injected directly into ev_pressed / ev_released.
    """

    def __init__(self, device_type="keyboard"):
        """
        Initialise without calling InputReader.__init__ to avoid Panda3D.

        :param device_type: The device type this stub reports as.
        """
        self.device_type = device_type
        self.state = InputState()
        self.previous = {}
        self.logical_down = {}
        self.ev_pressed = set()
        self.ev_released = set()
        self.hw_state = {}
        self.hw_axes = {}

    def read_all_buttons(self) -> dict:
        """
        :return: A copy of hw_state set by the test.
        """
        return dict(self.hw_state)

    def read_axes(self, state):
        """
        :param state: The InputState whose axes dict will be updated.
        """
        state.axes.update(self.hw_axes)


@pytest.fixture
def reader():
    """
    Returns a fresh _StubReader ready for use.
    """
    return _StubReader()


# ---------------------------------------------------------------------------
# InputState
# ---------------------------------------------------------------------------


def test_input_state_buttons_empty():
    """
    buttons must be an empty dict on construction.
    """
    assert InputState().buttons == {}


def test_input_state_repeats_empty():
    """
    repeats must be an empty dict on construction.
    """
    assert InputState().repeats == {}


def test_input_state_releases_empty():
    """
    releases must be an empty dict on construction.
    """
    assert InputState().releases == {}


def test_input_state_axes_empty():
    """
    axes must be an empty dict on construction.
    """
    assert InputState().axes == {}


# ---------------------------------------------------------------------------
# InputReader.poll — transition logic
# ---------------------------------------------------------------------------


def test_poll_first_press_goes_to_buttons(reader):
    """
    A button that was up last frame and is down this frame must appear in
    state.buttons and nowhere else.
    """
    reader.hw_state = {"fire": True}
    state = reader.poll()
    assert state.buttons.get("fire") is True
    assert "fire" not in state.repeats
    assert "fire" not in state.releases


def test_poll_held_button_goes_to_repeats(reader):
    """
    A button that was down last frame and is still down this frame must
    appear in state.repeats and not in state.buttons.
    """
    reader.hw_state = {"fire": True}
    reader.poll()  # frame 1 — press
    state = reader.poll()  # frame 2 — hold
    assert state.repeats.get("fire") is True
    assert "fire" not in state.buttons


def test_poll_released_button_goes_to_releases(reader):
    """
    A button that was down last frame and is up this frame must appear in
    state.releases and not in state.buttons or state.repeats.
    """
    reader.hw_state = {"fire": True}
    reader.poll()
    reader.hw_state = {"fire": False}
    state = reader.poll()
    assert state.releases.get("fire") is True
    assert "fire" not in state.buttons
    assert "fire" not in state.repeats


def test_poll_unpressed_button_absent_from_all_dicts(reader):
    """
    A button that is not pressed and was not pressed must not appear in any
    transition dict.
    """
    reader.hw_state = {"fire": False}
    state = reader.poll()
    assert "fire" not in state.buttons
    assert "fire" not in state.repeats
    assert "fire" not in state.releases


def test_poll_stale_state_cleared_each_frame(reader):
    """
    A button that was pressed on frame N must not appear in buttons on
    frame N+1 even if the hardware dict no longer contains it.
    """
    reader.hw_state = {"fire": True}
    reader.poll()
    reader.hw_state = {}
    state = reader.poll()
    assert "fire" not in state.buttons
    assert "fire" not in state.repeats


def test_poll_multiple_buttons_independent(reader):
    """
    Pressing several buttons simultaneously must place each in buttons
    independently.
    """
    reader.hw_state = {"fire": True, "boost": True, "pause": False}
    state = reader.poll()
    assert state.buttons.get("fire") is True
    assert state.buttons.get("boost") is True
    assert "pause" not in state.buttons


def test_poll_safety_net_pressed_merges_into_buttons(reader):
    """
    A name in ev_pressed must be merged into state.buttons even if
    polling does not see the button down this frame (brief tap between frames).
    """
    reader.ev_pressed.add("fire")
    reader.hw_state = {}
    state = reader.poll()
    assert state.buttons.get("fire") is True


def test_poll_safety_net_released_merges_into_releases(reader):
    """
    A name in ev_released must be merged into state.releases.
    """
    reader.ev_released.add("fire")
    reader.hw_state = {}
    state = reader.poll()
    assert state.releases.get("fire") is True


def test_poll_safety_net_ev_pressed_cleared_after_poll(reader):
    """
    ev_pressed must be empty after poll() so events are not replayed
    on the next frame.
    """
    reader.ev_pressed.add("fire")
    reader.poll()
    assert len(reader.ev_pressed) == 0


def test_poll_safety_net_ev_released_cleared_after_poll(reader):
    """
    ev_released must be empty after poll() so events are not replayed
    on the next frame.
    """
    reader.ev_released.add("fire")
    reader.poll()
    assert len(reader.ev_released) == 0


def test_poll_safety_net_and_polling_agree_no_duplicate(reader):
    """
    When both polling and a safety-net event report the same button down,
    buttons must contain the button exactly once (True, not duplicated).
    """
    reader.hw_state = {"fire": True}
    reader.ev_pressed.add("fire")
    state = reader.poll()
    assert state.buttons.get("fire") is True
    assert list(state.buttons.keys()).count("fire") == 1


def test_poll_event_after_polling_is_not_a_second_press(reader):
    """
    A press seen by polling, then reported again by its event one frame later,
    is a single press: the second frame is a hold.
    """
    reader.hw_state = {"cycle": True}
    assert reader.poll().buttons.get("cycle") is True

    reader.ev_pressed.add("cycle")
    state = reader.poll()

    assert "cycle" not in state.buttons
    assert state.repeats.get("cycle") is True


def test_poll_polling_after_event_is_not_a_second_press(reader):
    """
    A press reported by its event first, then seen by polling one frame later,
    is a single press: the second frame is a hold.
    """
    reader.ev_pressed.add("cycle")
    assert reader.poll().buttons.get("cycle") is True

    reader.hw_state = {"cycle": True}
    state = reader.poll()

    assert "cycle" not in state.buttons
    assert state.repeats.get("cycle") is True


def test_poll_release_reported_once_by_both_sources(reader):
    """
    A release reported by its event, then seen by polling one frame later, is
    a single release.
    """
    reader.hw_state = {"boost": True}
    reader.poll()  # press
    reader.ev_released.add("boost")
    assert reader.poll().releases.get("boost") is True  # event first

    reader.hw_state = {"boost": False}
    state = reader.poll()  # polling catches up

    assert "boost" not in state.releases


def test_poll_successive_presses_each_count_once(reader):
    """
    Two distinct presses, each seen by polling and by a late event, count as
    two presses.
    """
    n_presses = 0
    for _ in range(2):
        reader.hw_state = {"cycle": True}
        n_presses += "cycle" in reader.poll().buttons
        reader.ev_pressed.add("cycle")
        n_presses += "cycle" in reader.poll().buttons
        reader.hw_state = {"cycle": False}
        reader.poll()
        reader.ev_released.add("cycle")
        reader.poll()

    assert n_presses == 2


def test_poll_release_and_press_between_polls_while_held(reader):
    """
    A button released and pressed again between two polls (polling sees it held
    throughout) reports both the release and the new press.
    """
    reader.hw_state = {"fire": True}
    reader.poll()
    reader.ev_released.add("fire")
    reader.ev_pressed.add("fire")

    state = reader.poll()

    assert state.releases.get("fire") is True
    assert state.buttons.get("fire") is True


def test_poll_axes_populated(reader):
    """
    Axis values returned by read_axes must appear in state.axes.
    """
    reader.hw_axes = {"throttle": 0.75, "yaw": -0.3}
    reader.hw_state = {}
    state = reader.poll()
    assert state.axes["throttle"] == pytest.approx(0.75)
    assert state.axes["yaw"] == pytest.approx(-0.3)


def test_poll_axes_cleared_between_frames(reader):
    """
    Axes from frame N must not bleed into frame N+1 when read_axes no
    longer produces them.
    """
    reader.hw_axes = {"throttle": 0.5}
    reader.hw_state = {}
    reader.poll()
    reader.hw_axes = {}
    state = reader.poll()
    assert "throttle" not in state.axes


def test_poll_release_then_press_is_fresh_press(reader):
    """
    After a button is released (frame N) and pressed again (frame N+1), it
    must appear in buttons on the second press frame.
    """
    reader.hw_state = {"fire": True}
    reader.poll()  # press
    reader.hw_state = {"fire": False}
    reader.poll()  # release
    reader.hw_state = {"fire": True}
    state = reader.poll()  # re-press
    assert state.buttons.get("fire") is True
    assert "fire" not in state.repeats


def test_poll_returns_same_state_object_each_call(reader):
    """
    poll() must return the same InputState instance every call so that
    callers holding a reference always see the current frame.
    """
    s1 = reader.poll()
    s2 = reader.poll()
    assert s1 is s2


# ---------------------------------------------------------------------------
# InputReader.apply_dead_zone — pure static dead-zone method
# ---------------------------------------------------------------------------

apply_dead_zone = InputReader.apply_dead_zone


def test_apply_dead_zone_zero_input_returns_zero():
    assert apply_dead_zone(0.0, 0.1) == pytest.approx(0.0)


def test_apply_dead_zone_value_inside_dead_zone_returns_zero():
    assert apply_dead_zone(0.05, 0.1) == pytest.approx(0.0)


def test_apply_dead_zone_value_at_dead_zone_boundary_returns_zero():
    # At exactly the boundary: value - sign*dead_zone = 0.
    assert apply_dead_zone(0.1, 0.1) == pytest.approx(0.0)


def test_apply_dead_zone_positive_value_beyond_dead_zone():
    assert apply_dead_zone(0.5, 0.1) == pytest.approx(0.4)


def test_apply_dead_zone_negative_value_beyond_dead_zone():
    assert apply_dead_zone(-0.5, 0.1) == pytest.approx(-0.4)


def test_apply_dead_zone_negative_inside_dead_zone_returns_zero():
    assert apply_dead_zone(-0.05, 0.1) == pytest.approx(0.0)


def test_apply_dead_zone_full_deflection():
    assert apply_dead_zone(1.0, 0.15) == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# JoystickReader.button_index — pure static name-to-index conversion
# ---------------------------------------------------------------------------


def test_button_index_stick_button_1_is_zero():
    assert JoystickReader.button_index("stick_button_1") == 0


def test_button_index_stick_button_10_is_nine():
    assert JoystickReader.button_index("stick_button_10") == 9


def test_button_index_non_numeric_suffix_returns_none():
    assert JoystickReader.button_index("stick_button_a") is None


def test_button_index_empty_suffix_returns_none():
    assert JoystickReader.button_index("stick_button_") is None


def test_button_index_arbitrary_name_returns_none():
    assert JoystickReader.button_index("fire") is None


# ---------------------------------------------------------------------------
# InputReader.collect_button_names — per device type
# ---------------------------------------------------------------------------


def test_collect_button_names_reads_only_own_device_type():
    """
    Each reader polls only the buttons bound for its own device type, minus
    the axis names.
    """
    reader = _StubReader(device_type="gamepad")
    reader.app = MagicMock()
    reader.app.bindings = {
        "contexts": {
            "flight": {
                "keyboard": {"fire": "space"},
                "gamepad": {"fire": "gamepad_lshoulder", "yaw": "right_x"},
            },
            "hyperspace": {"gamepad": {"drop_hyperspace": "gamepad_face_a"}},
        }
    }
    names = reader.collect_button_names(frozenset({"right_x"}))
    menu_names = {name for names in MENU_BUTTONS["gamepad"].values() for name in names}
    assert names == {"gamepad_lshoulder", "gamepad_face_a"} | menu_names


def test_collect_button_names_polls_menu_keys_without_bindings():
    """
    The hardcoded menu keys are polled even though no binding uses them.
    """
    reader = _StubReader(device_type="keyboard")
    reader.app = MagicMock()
    reader.app.bindings = {"contexts": {}}
    names = reader.collect_button_names(frozenset())
    assert {"arrow_left", "arrow_right", "enter", "escape"} <= names


# ---------------------------------------------------------------------------
# GamepadReader — hot-plug
# ---------------------------------------------------------------------------


def make_app_with_no_gamepad():
    app = MagicMock()
    app.bindings = {"contexts": {}, "dead_zones": {}}
    app.devices.getDevices.return_value = []
    return app


def make_gamepad_device():
    device = MagicMock()
    device.device_class = InputDevice.DeviceClass.gamepad
    return device


def test_gamepad_reader_starts_without_device():
    """
    No gamepad at startup is a normal case: nothing is attached and polling
    reports nothing.
    """
    app = make_app_with_no_gamepad()
    reader = GamepadReader(app)
    assert reader.gamepad is None
    app.attachInputDevice.assert_not_called()
    state = reader.poll()
    assert state.buttons == {} and state.axes == {}
    reader.clean()


def test_gamepad_reader_attaches_gamepad_on_connect():
    app = make_app_with_no_gamepad()
    reader = GamepadReader(app)
    device = make_gamepad_device()
    reader.connect(device)
    assert reader.gamepad is device
    app.attachInputDevice.assert_called_once_with(device, prefix="gamepad")
    reader.clean()


def test_gamepad_reader_detaches_on_disconnect_with_no_fallback():
    app = make_app_with_no_gamepad()
    reader = GamepadReader(app)
    device = make_gamepad_device()
    reader.connect(device)
    reader.disconnect(device)
    assert reader.gamepad is None
    app.detachInputDevice.assert_called_once_with(device)
    reader.clean()


def test_readers_do_not_replace_each_other_hotplug_handlers():
    """
    Gamepad and joystick readers both listen for connect-device: as separate
    DirectObjects, neither replaces the other's handler, and cleaning one
    leaves the other's in place.
    """
    app = make_app_with_no_gamepad()
    gamepad_reader = GamepadReader(app)
    joystick_reader = JoystickReader(app)
    assert gamepad_reader.isAccepting("connect-device")
    assert joystick_reader.isAccepting("connect-device")
    gamepad_reader.clean()
    assert joystick_reader.isAccepting("connect-device")
    joystick_reader.clean()


# ---------------------------------------------------------------------------
# CompositeInputReader
# ---------------------------------------------------------------------------


def make_composite_app(cursor_hidden=False):
    """
    :param cursor_hidden: Whether the window's cursor is currently hidden.
    :return: A mock app with a still mouse at the window centre.
    """
    app = MagicMock()
    app.mouseWatcherNode.hasMouse.return_value = True
    app.mouseWatcherNode.getMouseX.return_value = 0.0
    app.mouseWatcherNode.getMouseY.return_value = 0.0
    app.win.getProperties.return_value.getCursorHidden.return_value = cursor_hidden
    return app


def make_composite(app=None):
    """
    :param app: The mock app (a still-mouse one by default).
    :return: (composite, keyboard stub, gamepad stub)
    """
    keyboard = _StubReader(device_type="keyboard")
    gamepad = _StubReader(device_type="gamepad")
    app = app or make_composite_app()
    return CompositeInputReader(app, [keyboard, gamepad]), keyboard, gamepad


def test_composite_merges_every_reader_state():
    composite, keyboard, gamepad = make_composite()
    keyboard.hw_state = {"space": True}
    gamepad.hw_state = {"gamepad_lshoulder": True}
    gamepad.hw_axes = {"right_x": 0.3}
    state = composite.poll()
    assert state.buttons == {"space": True, "gamepad_lshoulder": True}
    assert state.axes == {"right_x": 0.3}


def test_composite_keeps_each_reader_transitions():
    """
    A key held on one device and a button pressed on another are reported
    as a repeat and a press respectively.
    """
    composite, keyboard, gamepad = make_composite()
    keyboard.hw_state = {"space": True}
    composite.poll()
    gamepad.hw_state = {"gamepad_lshoulder": True}
    state = composite.poll()
    assert state.repeats == {"space": True}
    assert state.buttons == {"gamepad_lshoulder": True}


def test_composite_clears_previous_frame():
    composite, keyboard, gamepad = make_composite()
    gamepad.hw_axes = {"right_x": 0.3}
    keyboard.hw_state = {"space": True}
    composite.poll()
    gamepad.hw_axes = {}
    keyboard.hw_state = {"space": False}
    state = composite.poll()
    assert state.axes == {}
    assert state.buttons == {} and state.releases == {"space": True}


def test_composite_last_device_defaults_to_keyboard():
    composite, _, _ = make_composite()
    composite.poll()
    assert composite.last_device == "keyboard"


def test_composite_last_device_follows_button_press():
    composite, keyboard, gamepad = make_composite()
    gamepad.hw_state = {"gamepad_lshoulder": True}
    composite.poll()
    assert composite.last_device == "gamepad"
    keyboard.hw_state = {"space": True}
    composite.poll()
    assert composite.last_device == "keyboard"


def test_composite_last_device_ignores_held_button():
    composite, keyboard, gamepad = make_composite()
    gamepad.hw_state = {"gamepad_lshoulder": True}
    composite.poll()
    keyboard.hw_state = {"space": True}
    composite.poll()
    # The gamepad button is still held, but only new presses count
    composite.poll()
    assert composite.last_device == "keyboard"


def test_composite_last_device_follows_axis_crossing_threshold():
    composite, _, gamepad = make_composite()
    gamepad.hw_axes = {"right_x": 0.3}
    composite.poll()
    assert composite.last_device == "keyboard"
    gamepad.hw_axes = {"right_x": -0.8}
    composite.poll()
    assert composite.last_device == "gamepad"


def test_composite_last_device_ignores_axis_resting_past_threshold():
    """
    A throttle lever left forward does not keep claiming last_device.
    """
    composite, keyboard, gamepad = make_composite()
    gamepad.hw_axes = {"right_trigger": 0.9}
    composite.poll()
    keyboard.hw_state = {"space": True}
    composite.poll()
    composite.poll()
    assert composite.last_device == "keyboard"


def test_composite_clean_cleans_every_reader():
    first, second = MagicMock(), MagicMock()
    composite = CompositeInputReader(make_composite_app(), [first, second])
    composite.clean()
    first.clean.assert_called_once()
    second.clean.assert_called_once()


def requested_cursor_hidden(app):
    """
    :return: The cursor-hidden flags requested on the window, in order.
    """
    return [
        call.args[0].getCursorHidden()
        for call in app.win.requestProperties.call_args_list
    ]


def test_composite_mouse_moved_only_after_a_move():
    app = make_composite_app()
    composite, _, _ = make_composite(app)
    assert composite.poll().mouse_moved is False
    assert composite.poll().mouse_moved is False
    app.mouseWatcherNode.getMouseX.return_value = 0.3
    assert composite.poll().mouse_moved is True
    assert composite.poll().mouse_moved is False


def test_composite_mouse_outside_window_is_not_a_move():
    app = make_composite_app()
    composite, _, _ = make_composite(app)
    composite.poll()
    app.mouseWatcherNode.hasMouse.return_value = False
    assert composite.poll().mouse_moved is False


def test_composite_hides_cursor_on_device_input():
    app = make_composite_app()
    composite, keyboard, _ = make_composite(app)
    keyboard.hw_state = {"space": True}
    composite.poll()
    assert requested_cursor_hidden(app) == [True]


def test_composite_shows_cursor_when_mouse_moves():
    app = make_composite_app(cursor_hidden=True)
    composite, _, _ = make_composite(app)
    composite.poll()
    app.mouseWatcherNode.getMouseX.return_value = 0.3
    composite.poll()
    assert requested_cursor_hidden(app) == [False]


def test_composite_leaves_cursor_alone_when_already_right():
    app = make_composite_app(cursor_hidden=True)
    composite, keyboard, _ = make_composite(app)
    keyboard.hw_state = {"space": True}
    composite.poll()
    app.win.requestProperties.assert_not_called()


def test_composite_held_key_does_not_hide_cursor_again():
    """
    Only presses count, so a key held while the mouse moves leaves it shown.
    """
    app = make_composite_app()
    composite, keyboard, _ = make_composite(app)
    keyboard.hw_state = {"w": True}
    composite.poll()
    app.win.getProperties.return_value.getCursorHidden.return_value = True
    app.mouseWatcherNode.getMouseX.return_value = 0.3
    composite.poll()
    app.win.getProperties.return_value.getCursorHidden.return_value = False
    composite.poll()
    assert requested_cursor_hidden(app) == [True, False]
