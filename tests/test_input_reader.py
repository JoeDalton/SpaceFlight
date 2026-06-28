import pytest

from space_flight.ui.input_reader import (
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

    Call poll() normally; control what _read_all_buttons returns by setting
    self.hw_state, and what axes are produced by setting self.hw_axes.
    Safety-net events can be injected directly into _ev_pressed / _ev_released.
    """

    def __init__(self):
        """
        Initialise without calling InputReader.__init__ to avoid Panda3D.
        """
        self.state = InputState()
        self.previous = {}
        self.ev_pressed = set()
        self.ev_released = set()
        self.global_keys = []
        self.hw_state = {}
        self.hw_axes = {}

    def read_all_buttons(self) -> dict:
        """
        :return: A copy of hw_state set by the test.
        """
        return dict(self.hw_state)

    def read_axes(self, state) -> None:
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
    ``buttons`` must be an empty dict on construction.
    """
    assert InputState().buttons == {}


def test_input_state_repeats_empty():
    """
    ``repeats`` must be an empty dict on construction.
    """
    assert InputState().repeats == {}


def test_input_state_releases_empty():
    """
    ``releases`` must be an empty dict on construction.
    """
    assert InputState().releases == {}


def test_input_state_axes_empty():
    """
    ``axes`` must be an empty dict on construction.
    """
    assert InputState().axes == {}


# ---------------------------------------------------------------------------
# InputReader.poll — transition logic
# ---------------------------------------------------------------------------


def test_poll_first_press_goes_to_buttons(reader):
    """
    A button that was up last frame and is down this frame must appear in
    ``state.buttons`` and nowhere else.
    """
    reader.hw_state = {"fire": True}
    state = reader.poll()
    assert state.buttons.get("fire") is True
    assert "fire" not in state.repeats
    assert "fire" not in state.releases


def test_poll_held_button_goes_to_repeats(reader):
    """
    A button that was down last frame and is still down this frame must
    appear in ``state.repeats`` and not in ``state.buttons``.
    """
    reader.hw_state = {"fire": True}
    reader.poll()  # frame 1 — press
    state = reader.poll()  # frame 2 — hold
    assert state.repeats.get("fire") is True
    assert "fire" not in state.buttons


def test_poll_released_button_goes_to_releases(reader):
    """
    A button that was down last frame and is up this frame must appear in
    ``state.releases`` and not in ``state.buttons`` or ``state.repeats``.
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
    A button that was pressed on frame N must not appear in ``buttons`` on
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
    Pressing several buttons simultaneously must place each in ``buttons``
    independently.
    """
    reader.hw_state = {"fire": True, "boost": True, "pause": False}
    state = reader.poll()
    assert state.buttons.get("fire") is True
    assert state.buttons.get("boost") is True
    assert "pause" not in state.buttons


def test_poll_safety_net_pressed_merges_into_buttons(reader):
    """
    A name in ``_ev_pressed`` must be merged into ``state.buttons`` even if
    polling does not see the button down this frame (brief tap between frames).
    """
    reader.ev_pressed.add("fire")
    reader.hw_state = {}
    state = reader.poll()
    assert state.buttons.get("fire") is True


def test_poll_safety_net_released_merges_into_releases(reader):
    """
    A name in ``_ev_released`` must be merged into ``state.releases``.
    """
    reader.ev_released.add("fire")
    reader.hw_state = {}
    state = reader.poll()
    assert state.releases.get("fire") is True


def test_poll_safety_net_ev_pressed_cleared_after_poll(reader):
    """
    ``_ev_pressed`` must be empty after poll() so events are not replayed
    on the next frame.
    """
    reader.ev_pressed.add("fire")
    reader.poll()
    assert len(reader.ev_pressed) == 0


def test_poll_safety_net_ev_released_cleared_after_poll(reader):
    """
    ``_ev_released`` must be empty after poll() so events are not replayed
    on the next frame.
    """
    reader.ev_released.add("fire")
    reader.poll()
    assert len(reader.ev_released) == 0


def test_poll_safety_net_and_polling_agree_no_duplicate(reader):
    """
    When both polling and a safety-net event report the same button down,
    ``buttons`` must contain the button exactly once (True, not duplicated).
    """
    reader.hw_state = {"fire": True}
    reader.ev_pressed.add("fire")
    state = reader.poll()
    assert state.buttons.get("fire") is True
    assert list(state.buttons.keys()).count("fire") == 1


def test_poll_axes_populated(reader):
    """
    Axis values returned by ``_read_axes`` must appear in ``state.axes``.
    """
    reader.hw_axes = {"throttle": 0.75, "yaw": -0.3}
    reader.hw_state = {}
    state = reader.poll()
    assert state.axes["throttle"] == pytest.approx(0.75)
    assert state.axes["yaw"] == pytest.approx(-0.3)


def test_poll_axes_cleared_between_frames(reader):
    """
    Axes from frame N must not bleed into frame N+1 when _read_axes no
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
    must appear in ``buttons`` on the second press frame.
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
# GamepadReader.dz / JoystickReader.dz — pure static dead-zone methods
# ---------------------------------------------------------------------------


@pytest.fixture(
    params=[GamepadReader.dz, JoystickReader.dz], ids=["gamepad", "joystick"]
)
def dz(request):
    """Parametrize over both reader dead-zone implementations."""
    return request.param


def test_dz_zero_input_returns_zero(dz):
    assert dz(0.0, 0.1) == pytest.approx(0.0)


def test_dz_value_inside_dead_zone_returns_zero(dz):
    assert dz(0.05, 0.1) == pytest.approx(0.0)


def test_dz_value_at_dead_zone_boundary_returns_zero(dz):
    # At exactly the boundary: value - sign*dead_zone = 0.
    assert dz(0.1, 0.1) == pytest.approx(0.0)


def test_dz_positive_value_beyond_dead_zone(dz):
    assert dz(0.5, 0.1) == pytest.approx(0.4)


def test_dz_negative_value_beyond_dead_zone(dz):
    assert dz(-0.5, 0.1) == pytest.approx(-0.4)


def test_dz_negative_inside_dead_zone_returns_zero(dz):
    assert dz(-0.05, 0.1) == pytest.approx(0.0)


def test_dz_full_deflection(dz):
    assert dz(1.0, 0.15) == pytest.approx(0.85)


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
