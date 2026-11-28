from __future__ import annotations

from typing import TYPE_CHECKING

from direct.showbase.ShowBaseGlobal import aspect2d
from panda3d.core import (
    BitMask32,
    Camera,
    CardMaker,
    GraphicsOutput,
    GraphicsPipe,
    NodePath,
    Texture,
    TextureStage,
    WindowProperties,
)
from world_builder.depth import scene_buffer_props
from world_builder.post import PostChain

from space_flight import CAMERA_FAR_M

if TYPE_CHECKING:
    from world_builder.post import RenderSettings

    from space_flight.game.flight_state import FlightState

MIRROR_ASPECT_RATIO = 2
MIRROR_HALF_VERTICAL_SIZE = 0.2
MIRROR_FOV = 30
#: The card's scale on aspect2d (its frame is MIRROR_HALF_VERTICAL_SIZE high)
MIRROR_SCREEN_SCALE = 0.75
#: The mirror buffer's sort: before the main view, which may show the mirror's
#: card; its post chain's passes take the next sorts
MIRROR_SORT = -100


def mirror_screen_size(window_height: int) -> tuple[int, int]:
    """
    :param window_height: The window's height, pixels
    :return: The mirror card's size on screen, pixels (aspect2d spans the
        window's height over 2 units)
    """
    height = window_height * MIRROR_HALF_VERTICAL_SIZE * MIRROR_SCREEN_SCALE
    return max(1, round(MIRROR_ASPECT_RATIO * height)), max(1, round(height))


def mirror_render_size(window_height: int, scale: float) -> tuple[int, int]:
    """
    :param window_height: The window's height, pixels
    :param scale: The mirror's resolution over its card's size on screen
        (the graphics settings' ``mirror.scale``: 1 = native)
    :return: The mirror buffer's size, pixels, the card's aspect ratio
    """
    height = max(1, round(mirror_screen_size(window_height)[1] * scale))
    return MIRROR_ASPECT_RATIO * height, height


class RearViewMirror:
    """
    The rear-view mirror: a camera looking back from the player's ship, drawn
    into a small buffer of its own and shown on a card at the top of the
    screen.

    It has render settings of its own (the graphics settings' ``mirror``
    section, :meth:`GraphicsSettings.mirror_render_settings`): the buffer's
    multisamples (and a float depth buffer, for the reversed depth's
    precision); with FSR 1 or FXAA, a WorldBuilder post chain upscales the
    buffer to the card's size on screen (``world_builder.post.PostChain``
    ending in a texture), so a mirror drawn at ``mirror.scale`` of its card's
    size on screen shows sharp. Without either, the card shows the buffer
    itself, stretched bilinearly. Both follow the window's height.
    """

    # TODO: integrate in 3D cockpit
    def __init__(self, game: FlightState, player_node: NodePath):
        self.game = game
        app = self.game.app
        render = self._render_settings()

        mirror_tex = Texture()
        mirror_tex.setWrapU(Texture.WMClamp)
        mirror_tex.setWrapV(Texture.WMClamp)
        self.mirror_tex = mirror_tex

        # The mirror's resolution: the player's share of the card's size on
        # screen (resized with the window, see _follow)
        self.scale = app.graphics_settings.config["mirror"]["scale"]
        self._window_height = app.win.getYSize()
        self.render_size = mirror_render_size(self._window_height, self.scale)

        self.mirror_buffer = app.graphicsEngine.makeOutput(
            app.win.getPipe(),
            "RearViewBuffer",
            MIRROR_SORT,
            scene_buffer_props(app.win.getFbProperties(), render.msaa),
            WindowProperties.size(*self.render_size),
            GraphicsPipe.BF_refuse_window | GraphicsPipe.BF_resizeable,
            app.win.getGsg(),
            app.win,
        )
        self.mirror_buffer.addRenderTexture(
            mirror_tex, GraphicsOutput.RTMBindOrCopy, GraphicsOutput.RTPColor
        )
        self.mirror_buffer.setClearColor((0, 0, 0, 1))

        self.mirror_cam = Camera("rear_view_cam")
        self.mirror_np = NodePath(self.mirror_cam)

        self.mirror_cam.setLens(app.camLens.makeCopy())
        # The whole range, whatever the main lens holds
        self.mirror_cam.getLens().setNearFar(1.0, CAMERA_FAR_M)
        self.mirror_cam.getLens().setFov(MIRROR_FOV)  # Narrower = more realistic mirror
        self.mirror_cam.getLens().setAspectRatio(MIRROR_ASPECT_RATIO)
        # A finite copy to cull by (set_depth_mode can make the lens itself
        # reversed and infinite)
        self._cull_lens = self.mirror_cam.getLens().makeCopy()

        self.mirror_buffer.makeDisplayRegion().setCamera(self.mirror_np)

        self.mirror_np.reparentTo(player_node)
        self.mirror_np.setPos(0, -2, 1.5)  # Slightly behind and above
        self.mirror_np.setHpr(180, 0, 0)  # Look backwards

        cm = CardMaker("mirror")
        cm.setFrame(
            -MIRROR_ASPECT_RATIO * MIRROR_HALF_VERTICAL_SIZE,
            MIRROR_ASPECT_RATIO * MIRROR_HALF_VERTICAL_SIZE,
            -MIRROR_HALF_VERTICAL_SIZE,
            MIRROR_HALF_VERTICAL_SIZE,
        )

        self.mirror_card = NodePath(cm.generate())
        self.is_mirror_visible = True

        # Mirror in 2D screen layout
        self.mirror_card.reparentTo(aspect2d)
        self.mirror_card.setPos(0, 0, 0.65)  # Place at the top center of the screen
        # Flip image horizontally
        self.mirror_card.setScale(-MIRROR_SCREEN_SCALE, 1, MIRROR_SCREEN_SCALE)

        # Ensure it gets rendered behind the hud
        self.mirror_card.setDepthTest(False)
        self.mirror_card.setDepthWrite(False)
        self.mirror_card.setBin("fixed", 0)

        self.mirror_np.node().setCameraMask(BitMask32.bit(2))

        # FSR 1 (or FXAA) up to the card's size on screen
        self.chain: PostChain | None = None
        if render.fsr or render.fxaa_active:
            self.chain = PostChain(
                app.graphicsEngine,
                app.win,
                mirror_tex,
                render,
                self.render_size,
                buffer_sort=MIRROR_SORT + 1,
                output_size=mirror_screen_size(self._window_height),
            )
        # Apply the mirror's picture as a texture of the card
        self.card_texture = mirror_tex if self.chain is None else self.chain.texture
        self.mirror_card.setTexture(self.card_texture)
        self._task = app.taskMgr.add(self._follow, "rear_view_mirror")

    def _render_settings(self) -> RenderSettings:
        """:return: The mirror's render settings (the graphics settings'
        ``mirror`` section, as WorldBuilder's post chain takes them)"""
        return self.game.app.graphics_settings.mirror_render_settings()

    def _follow(self, task):
        """
        Per frame: the buffer and the chain's output follow the window's
        height (the card's size on screen), and the card shows only the
        texture's drawn part (the GSG may pad it to powers of two).
        """
        height = self.game.app.win.getYSize()
        if height != self._window_height:
            self._window_height = height
            self.render_size = mirror_render_size(height, self.scale)
            self.mirror_buffer.setSize(*self.render_size)
            if self.chain is not None:
                self.chain.resize(self.render_size, mirror_screen_size(height))
        if self.chain is not None:
            self.chain.update()
        sx, sy = self.card_texture.getTexScale()
        if sx > 0.0 and sy > 0.0:  # NaN until the texture's first frame
            self.mirror_card.setTexScale(TextureStage.getDefault(), sx, sy)
        return task.cont

    def set_depth_mode(self, mode: int):
        """
        The view's depth convention (world_builder.depth), which the scene's
        shaders follow: with the world's reversed camera the mirror's camera
        is reversed too (an infinite lens, the "greater" test, depth cleared
        to 0), or the sky, pinned at the reversed far plane, fails its depth
        test here. Culled to the mirror's own standard range either way.
        """
        from panda3d.core import DepthTestAttrib
        from world_builder.depth import (
            DEPTH_STANDARD,
            frustum_bounds,
            reversed_lens,
            view_test,
        )

        lens = self.mirror_cam.getLens()
        state = self.mirror_cam.getInitialState()
        if mode == DEPTH_STANDARD:
            lens.setNearFar(1.0, CAMERA_FAR_M)
            state = state.removeAttrib(DepthTestAttrib)
            self.mirror_buffer.setClearDepth(1.0)
        else:
            reversed_lens(lens, 1.0)
            state = state.setAttrib(DepthTestAttrib.make(view_test(mode)))
            self.mirror_buffer.setClearDepth(0.0)
        self.mirror_cam.setInitialState(state)
        self.mirror_cam.setCullBounds(frustum_bounds(self._cull_lens))

    def toggle_mirror(self):
        """
        Toggles mirror visibility
        triggered by FlightInputContext via player.rear_view_mirror.toggle_mirror()
        """
        self.is_mirror_visible = not self.is_mirror_visible
        self.mirror_buffer.setActive(self.is_mirror_visible)
        if self.chain is not None:
            self.chain.set_active(self.is_mirror_visible)
        if self.is_mirror_visible:
            self.mirror_card.show()
        else:
            self.mirror_card.hide()

    def clean(self):
        """
        Cleans the mirror object
        """
        app = self.game.app
        app.taskMgr.remove(self._task)
        if self.chain is not None:
            self.chain.destroy()
            self.chain = None
        # Delete camera
        self.mirror_np.removeNode()
        self.mirror_cam = None
        # Delete buffer
        self.mirror_buffer.removeAllDisplayRegions()
        self.mirror_buffer.clearRenderTextures()
        app.graphicsEngine.removeWindow(self.mirror_buffer)
        self.mirror_buffer = None
        # Remove card
        self.mirror_card.removeNode()
        self.game = None
