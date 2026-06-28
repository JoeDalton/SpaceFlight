"""
Central owner of all graphics/display options.

Responsibilities:

* **Window mode** — fullscreen vs windowed, and window size. Applied when the
  real game window is (re)opened after the splash screen.
* **Render scale** — the 3D scene can be rendered into an offscreen buffer at a
  fraction of the window resolution and upscaled to the window, so old hardware
  can render fewer pixels while the window stays at native resolution. The 2D
  layers (``render2d`` / ``aspect2d`` — HUD, menus) are *not* routed through the
  buffer, so they stay crisp at full window resolution.
* **Anti-aliasing** — MSAA (hardware multisampling, applied to the offscreen
  render buffer) and/or FXAA (a post-process pass on the composited result).
  Both are independently selectable.

Render-scale and anti-aliasing live on a :class:`FilterManager` pipeline that is
(re)built per level load via :meth:`begin_scene_render` / torn down via
:meth:`end_scene_render`, so changing those settings takes effect on the next
level load. Window mode is applied via :meth:`open_game_window`.
"""

import logging
from time import sleep

from direct.filter.FilterManager import FilterManager
from panda3d.core import (
    AntialiasAttrib,
    FrameBufferProperties,
    Shader,
    Texture,
    WindowProperties,
)

from space_flight import DATAFILES_PATH

LOGGER = logging.getLogger()

_COMPOSITE_VERT = DATAFILES_PATH / "shaders/composite.vert"
_BLIT_FRAG = DATAFILES_PATH / "shaders/blit.frag"
_FXAA_FRAG = DATAFILES_PATH / "shaders/fxaa.frag"

# Sort for the offscreen scene buffer. Must be AFTER the per-scene auxiliary
# buffers (ocean reflection and rear-view mirror both use sort -100, so they
# feed their textures into the main scene) but BEFORE the window (sort 0).
_SCENE_BUFFER_SORT = -50


class GraphicsManager:
    """
    Applies the graphics settings to the running engine.
    """

    def __init__(self, app):
        self.app = app
        # FilterManager pipeline state (None when the scene renders straight to
        # the window — i.e. scale == 1.0 and no AA).
        self._filter_manager = None
        self._scene_tex = None
        self._scene_quad = None
        self._render_size = None
        self._uniform_task = None

    @property
    def settings(self) -> dict:
        """The current sanitised settings dict (owned by GraphicsSettings)."""
        return self.app.graphics_settings.config

    # ------------------------------------------------------------------
    # Window mode
    # ------------------------------------------------------------------

    def open_game_window(self):
        """
        Close the current window and open the real game window honouring the
        saved display mode/size.

        Called from :meth:`SplashState.exit` once loading is done. The brief
        sleep gives a clean cut between the splash window and the game window
        rather than a flicker.
        """
        old_win = self.app.win
        self.app.closeWindow(old_win)
        sleep(0.3)
        self.app.openDefaultWindow(props=self._build_window_props())
        self.app.set_background_color(0, 0, 0)

    def apply_window_settings(self):
        """
        Apply the saved display mode/size to the live window without recreating
        it (a runtime fullscreen/windowed toggle or resize).

        Used by the graphics settings menu on save, so window changes take
        effect immediately. Render scale and anti-aliasing are not touched here
        — those are rebuilt on the next level load via :meth:`begin_scene_render`.
        """
        self.app.win.requestProperties(self._build_window_props())

    def _build_window_props(self) -> WindowProperties:
        """Build :class:`WindowProperties` from the saved display settings."""
        props = WindowProperties()
        props.setUndecorated(False)
        if self.settings["display"]["mode"] == "fullscreen":
            props.setSize(
                self.app.pipe.getDisplayWidth(), self.app.pipe.getDisplayHeight()
            )
            props.setFullscreen(True)
        else:
            w, h = self.settings["display"]["windowed_size"]
            props.setSize(int(w), int(h))
            props.setFullscreen(False)
        return props

    # ------------------------------------------------------------------
    # Render size (consumed by resolution-dependent buffers, e.g. the ocean
    # reflection buffer)
    # ------------------------------------------------------------------

    def get_render_size(self) -> tuple[int, int]:
        """
        Return the current 3D render resolution in pixels.

        Equals the offscreen render-scale buffer size when the pipeline is
        active, otherwise the window size. Buffers that should scale with the
        internal resolution (the ocean reflection) size themselves off this
        rather than reading the window directly.
        """
        if self._render_size is not None:
            return self._render_size
        win = self.app.win
        return (win.getXSize(), win.getYSize())

    # ------------------------------------------------------------------
    # Render-scale / AA pipeline (per level load)
    # ------------------------------------------------------------------

    def begin_scene_render(self):
        """
        Build the render-scale / anti-aliasing pipeline for a gameplay session.

        No-op (straight-to-window rendering) when render scale is 1.0 and no
        anti-aliasing is requested. Otherwise routes the 3D camera into an
        offscreen buffer (sized window * scale, with MSAA if requested) and
        composites it back to the window via a fullscreen quad (with FXAA if
        requested). Idempotent: tears down any existing pipeline first.
        """
        self.end_scene_render()

        scale = self.settings["render"]["scale"]
        msaa = self.settings["antialiasing"]["msaa"]
        fxaa = self.settings["antialiasing"]["fxaa"]

        if scale >= 1.0 and msaa <= 0 and not fxaa:
            self._render_size = None
            return

        win = self.app.win
        render_w = max(1, int(round(win.getXSize() * scale)))
        render_h = max(1, int(round(win.getYSize() * scale)))
        self._render_size = (render_w, render_h)

        # forcex/forcey fix the buffer at this absolute size regardless of the
        # window size, which is exactly the render-scale decoupling we want.
        self._filter_manager = FilterManager(
            win, self.app.cam, forcex=render_w, forcey=render_h
        )
        # Render the scene buffer after the auxiliary buffers but before the
        # window (see _SCENE_BUFFER_SORT). createBuffer reads nextsort.
        self._filter_manager.nextsort = _SCENE_BUFFER_SORT

        fbprops = None
        if msaa > 0:
            fbprops = FrameBufferProperties()
            fbprops.setMultisamples(msaa)

        self._scene_tex = Texture("scene_color")
        quad = self._filter_manager.renderSceneInto(
            colortex=self._scene_tex, fbprops=fbprops
        )
        if quad is None:
            LOGGER.warning(
                "Render-scale pipeline failed to initialise; "
                "falling back to direct rendering"
            )
            self.end_scene_render()
            return

        if msaa > 0:
            self.app.render.setAntialias(AntialiasAttrib.MMultisample)

        # Composite the offscreen scene back to the window through a shader: a
        # plain blit, or FXAA when enabled. Both account for power-of-two render-
        # target padding via the texScale uniform (see _update_pipeline_uniforms);
        # without that the scene shows only in the lower-left corner of the quad.
        frag = _FXAA_FRAG if fxaa else _BLIT_FRAG
        quad.setShader(
            Shader.load(Shader.SL_GLSL, vertex=_COMPOSITE_VERT, fragment=frag)
        )
        quad.setShaderInput("sceneTex", self._scene_tex)
        # Seed the pad-correction uniforms now so the very first render (the
        # force_render() in FlightState.enter, which bypasses the task loop)
        # already has them; the task below refines texScale once the GSG has
        # applied any power-of-two padding.
        quad.setShaderInput("texScale", (1.0, 1.0))
        quad.setShaderInput("rcpFrame", (1.0 / render_w, 1.0 / render_h))
        self._scene_quad = quad
        self._uniform_task = self.app.taskMgr.add(
            self._update_pipeline_uniforms, "graphics_composite_uniforms"
        )

        LOGGER.info(
            f"Render pipeline: {render_w}x{render_h} "
            f"(scale {scale}), msaa={msaa}, fxaa={fxaa}"
        )

    def _update_pipeline_uniforms(self, task):
        """
        Keep the composite shader's pad-correction in sync with the render
        target.

        The GSG may pad the offscreen render target up to a power of two; the
        usable region (``tex.getTexScale()``) is only known after the first
        render and is fixed thereafter, but we refresh it every frame so the
        composite stays correct across any re-preparation of the texture.
        """
        if self._scene_quad is None or self._scene_tex is None:
            return task.done
        sx, sy = self._scene_tex.getTexScale()
        render_w, render_h = self._render_size
        self._scene_quad.setShaderInput("texScale", (sx, sy))
        self._scene_quad.setShaderInput("rcpFrame", (sx / render_w, sy / render_h))
        return task.cont

    def end_scene_render(self):
        """
        Tear down the render-scale / AA pipeline and restore direct-to-window
        rendering. Safe to call when no pipeline is active.
        """
        if self._uniform_task is not None:
            self.app.taskMgr.remove(self._uniform_task)
            self._uniform_task = None
        if self._filter_manager is not None:
            self.app.render.clearAntialias()
            self._filter_manager.cleanup()
            # FilterManager listens for window-event; drop it so old pipelines
            # don't accumulate handlers across level loads.
            self._filter_manager.ignoreAll()
            self._filter_manager = None
        if self._scene_quad is not None:
            self._scene_quad.removeNode()
            self._scene_quad = None
        self._scene_tex = None
        self._render_size = None
