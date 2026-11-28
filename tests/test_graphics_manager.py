"""
Unit tests for
:class:`~space_flight.global_architecture.graphics_manager.GraphicsManager`.

These cover the window's settings (:meth:`_build_window_props`, the delayed
fullscreen). Render scale and anti-aliasing are WorldBuilder's (the world's
``render`` settings, tested there).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from space_flight.global_architecture.graphics_manager import GraphicsManager


def _make_manager(config):
    """Return a GraphicsManager whose mock app exposes *config* as settings."""
    app = MagicMock()
    app.graphics_settings.config = config
    return GraphicsManager(app=app), app


def _full_config(**overrides):
    """A complete, valid settings dict with optional per-section overrides."""
    cfg = {
        "display": {"mode": "fullscreen", "windowed_size": [1280, 720]},
        "mirror": {"scale": 1.0, "msaa": 0, "fxaa": False, "fsr": False},
    }
    for section, values in overrides.items():
        cfg[section].update(values)
    return cfg


# ---------------------------------------------------------------------------
# _build_window_props
# ---------------------------------------------------------------------------


class TestBuildWindowProps:
    @pytest.fixture(autouse=True)
    def primary_monitor(self, monkeypatch):
        """A fixed primary monitor, offset like the secondary of a 2-screen desktop."""
        monitor = SimpleNamespace(
            x=1440, y=237, width=2560, height=1440, is_primary=True
        )
        monkeypatch.setattr(
            "space_flight.global_architecture.graphics_manager.get_primary_monitor",
            lambda: monitor,
        )
        return monitor

    def test_fullscreen_window_covers_primary_monitor(self, primary_monitor):
        mgr, _ = _make_manager(_full_config(display={"mode": "fullscreen"}))
        props = mgr._build_window_props()
        assert props.getXSize() == primary_monitor.width
        assert props.getYSize() == primary_monitor.height
        assert props.getXOrigin() == primary_monitor.x
        assert props.getYOrigin() == primary_monitor.y

    def test_fullscreen_props_are_windowed_and_decorated(self):
        # Fullscreen is requested later (go_full_screen_task), once the window sits
        # on the right monitor. It must also stay decorated: Panda3D asks the window
        # manager for fullscreen only on decorated windows; an undecorated one ends
        # up at x=0, straddling two monitors.
        mgr, _ = _make_manager(_full_config(display={"mode": "fullscreen"}))
        props = mgr._build_window_props()
        assert props.getFullscreen() is False
        assert props.getUndecorated() is False

    def test_fullscreen_schedules_delayed_fullscreen_task(self):
        mgr, app = _make_manager(_full_config(display={"mode": "fullscreen"}))
        mgr._build_window_props()
        app.taskMgr.doMethodLater.assert_called_once()
        delay, method = app.taskMgr.doMethodLater.call_args.args[:2]
        assert delay > 0
        assert method == mgr.go_full_screen_task

    def test_windowed_does_not_schedule_fullscreen_task(self):
        mgr, app = _make_manager(_full_config(display={"mode": "windowed"}))
        mgr._build_window_props()
        app.taskMgr.doMethodLater.assert_not_called()

    def test_windowed_uses_configured_size(self):
        mgr, _ = _make_manager(
            _full_config(display={"mode": "windowed", "windowed_size": [1600, 900]})
        )
        props = mgr._build_window_props()
        assert props.getFullscreen() is False
        assert props.getXSize() == 1600
        assert props.getYSize() == 900

    def test_windowed_is_centered_on_primary_monitor(self, primary_monitor):
        mgr, _ = _make_manager(
            _full_config(display={"mode": "windowed", "windowed_size": [1600, 900]})
        )
        props = mgr._build_window_props()
        assert props.getXOrigin() == primary_monitor.x + (2560 - 1600) // 2
        assert props.getYOrigin() == primary_monitor.y + (1440 - 900) // 2

    def test_windowed_is_decorated(self):
        mgr, _ = _make_manager(_full_config(display={"mode": "windowed"}))
        props = mgr._build_window_props()
        assert props.getUndecorated() is False


# ---------------------------------------------------------------------------
# go_full_screen_task
# ---------------------------------------------------------------------------


class TestGoFullScreenTask:
    def test_sends_monitor_hint_before_requesting_fullscreen_on_linux(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            "space_flight.global_architecture.graphics_manager.sys.platform", "linux"
        )
        mgr, app = _make_manager(_full_config())
        order = []
        mgr.set_fullscreen_monitor_linux = MagicMock(
            side_effect=lambda **kw: order.append("hint")
        )
        app.win.requestProperties.side_effect = lambda p: order.append(
            ("request", p.getFullscreen())
        )
        task = MagicMock()

        result = mgr.go_full_screen_task(task)

        # The hint must reach the window manager before fullscreen is requested.
        assert order == ["hint", ("request", True)]
        assert result == task.done

    def test_skips_monitor_hint_off_linux(self, monkeypatch):
        monkeypatch.setattr(
            "space_flight.global_architecture.graphics_manager.sys.platform", "win32"
        )
        mgr, app = _make_manager(_full_config())
        mgr.set_fullscreen_monitor_linux = MagicMock()

        mgr.go_full_screen_task(MagicMock())

        mgr.set_fullscreen_monitor_linux.assert_not_called()
        props = app.win.requestProperties.call_args.args[0]
        assert props.getFullscreen() is True


def test_the_game_asks_for_clip_control_but_on_macos():
    """WorldBuilder's reversed camera keeps a float depth buffer's precision
    with OpenGL's 0-1 depth (gl-depth-zero-to-one), set before the window
    opens; macOS's OpenGL has none."""
    import sys

    from world_builder.depth import zero_to_one

    import space_flight.global_architecture.simulator  # noqa: F401  (its PRC)

    assert zero_to_one() == (sys.platform != "darwin")
