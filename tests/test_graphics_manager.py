"""
Unit tests for
:class:`~space_flight.global_architecture.graphics_manager.GraphicsManager`.

These cover the parts that can run headless (no GSG / FilterManager):
- :meth:`get_render_size` — window vs render-scale buffer size
- :meth:`_build_window_props` — WindowProperties from settings
- :meth:`_update_pipeline_uniforms` — pad-correction uniform feed
- :meth:`begin_scene_render` — the no-op fast path (scale 1.0, no AA)

The full render-to-texture pipeline needs a real GraphicsStateGuardian and is
exercised separately (manual / integration), not here.
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
        "render": {"scale": 1.0, "mirror_scale": 1.0},
        "antialiasing": {"msaa": 0, "fxaa": False},
    }
    for section, values in overrides.items():
        cfg[section].update(values)
    return cfg


# ---------------------------------------------------------------------------
# get_render_size
# ---------------------------------------------------------------------------


class TestGetRenderSize:
    def test_returns_window_size_when_pipeline_inactive(self):
        mgr, app = _make_manager(_full_config())
        app.win.getXSize.return_value = 1920
        app.win.getYSize.return_value = 1080
        assert mgr.get_render_size() == (1920, 1080)

    def test_returns_buffer_size_when_pipeline_active(self):
        mgr, _ = _make_manager(_full_config())
        mgr._render_size = (800, 600)
        assert mgr.get_render_size() == (800, 600)


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


# ---------------------------------------------------------------------------
# _update_pipeline_uniforms
# ---------------------------------------------------------------------------


class TestUpdatePipelineUniforms:
    def test_feeds_texscale_and_rcpframe_from_texture(self):
        mgr, _ = _make_manager(_full_config())
        mgr._scene_quad = MagicMock()
        mgr._scene_tex = MagicMock()
        mgr._scene_tex.getTexScale.return_value = (0.5, 0.75)
        mgr._render_size = (800, 600)
        task = MagicMock()

        result = mgr._update_pipeline_uniforms(task)

        assert result == task.cont
        calls = {
            c.args[0]: c.args[1] for c in mgr._scene_quad.setShaderInput.call_args_list
        }
        assert calls["texScale"] == (0.5, 0.75)
        assert calls["rcpFrame"] == pytest.approx((0.5 / 800, 0.75 / 600))

    def test_returns_done_when_pipeline_torn_down(self):
        mgr, _ = _make_manager(_full_config())
        mgr._scene_quad = None
        task = MagicMock()
        assert mgr._update_pipeline_uniforms(task) == task.done


# ---------------------------------------------------------------------------
# begin_scene_render — no-op fast path
# ---------------------------------------------------------------------------


class TestBeginSceneRenderNoOp:
    def test_vanilla_settings_skip_pipeline(self):
        mgr, app = _make_manager(_full_config())
        mgr.begin_scene_render()
        # No offscreen pipeline created; render size falls back to the window.
        assert mgr._render_size is None
        assert mgr._filter_manager is None
        # The window/camera were never rerouted.
        app.cam.assert_not_called()

    def test_pipeline_built_when_scale_below_one(self, monkeypatch):
        # Stop before touching the GSG: assert we get past the early-return guard
        # by having FilterManager raise, which we catch as "attempted to build".
        mgr, app = _make_manager(_full_config(render={"scale": 0.5}))
        built = {}

        class _Boom(Exception):
            pass

        def _fake_fm(*a, **k):
            built["called"] = True
            raise _Boom()

        monkeypatch.setattr(
            "space_flight.global_architecture.graphics_manager.FilterManager",
            _fake_fm,
        )
        app.win.getXSize.return_value = 1000
        app.win.getYSize.return_value = 800
        with pytest.raises(_Boom):
            mgr.begin_scene_render()
        assert built.get("called") is True
        assert mgr._render_size == (500, 400)


# end_scene_render — the pipeline's buffers
# ---------------------------------------------------------------------------


class TestEndSceneRender:
    def test_buffers_lose_their_display_regions(self):
        """FilterManager.cleanup leaves the buffers' display regions on the
        camera: the next level's depth split would take the dead one and draw
        its far camera into a buffer that no longer exists (everything past
        the split black). They are removed before the cleanup."""
        mgr, _app = _make_manager(_full_config())
        calls = []
        buffer = MagicMock()
        buffer.remove_all_display_regions.side_effect = lambda: calls.append("regions")
        manager = MagicMock()
        manager.buffers = [buffer]
        manager.cleanup.side_effect = lambda: calls.append("cleanup")
        mgr._filter_manager = manager

        mgr.end_scene_render()

        assert calls == ["regions", "cleanup"]
        assert mgr._filter_manager is None

    def test_without_a_pipeline_nothing_happens(self):
        mgr, _app = _make_manager(_full_config())
        mgr.end_scene_render()  # no error
        assert mgr._filter_manager is None
