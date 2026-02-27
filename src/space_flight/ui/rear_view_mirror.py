from direct.showbase.ShowBaseGlobal import aspect2d
from panda3d.core import BitMask32, Camera, CardMaker, NodePath, Texture

MIRROR_ASPECT_RATIO = 2
MIRROR_VERTICAL_RESOLUTION = 128
MIRROR_HALF_VERTICAL_SIZE = 0.2
MIRROR_FOV = 30


class RearViewMirror:
    # TODO: integrate in 3D cockpit
    def __init__(self, game, player_node):
        self.game = game

        mirror_tex = Texture()
        mirror_tex.setWrapU(Texture.WMClamp)
        mirror_tex.setWrapV(Texture.WMClamp)

        self.mirror_buffer = self.game.app.win.makeTextureBuffer(
            "RearViewBuffer",
            MIRROR_VERTICAL_RESOLUTION * MIRROR_ASPECT_RATIO,
            MIRROR_VERTICAL_RESOLUTION,
            mirror_tex,
        )
        self.mirror_buffer.setClearColor((0, 0, 0, 1))

        self.mirror_cam = Camera("rear_view_cam")
        self.mirror_np = NodePath(self.mirror_cam)

        self.mirror_cam.setLens(self.game.app.camLens.makeCopy())
        self.mirror_cam.getLens().setFov(MIRROR_FOV)  # Narrower = more realistic mirror
        self.mirror_cam.getLens().setAspectRatio(MIRROR_ASPECT_RATIO)

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
        self.mirror_card.setScale(-0.75, 1, 0.75)  # Flip image horizontally

        # Ensure it gets rendered behind the hud
        self.mirror_card.setDepthTest(False)
        self.mirror_card.setDepthWrite(False)
        self.mirror_card.setBin("fixed", 0)

        # Apply mirror camera as a texture of the card
        self.mirror_card.setTexture(mirror_tex)

        self.mirror_buffer.setSort(-100)
        self.mirror_np.node().setCameraMask(BitMask32.bit(1))

        self.game.app.accept(  # TODO handle elsewhere
            self.game.key_bindings["toggle_mirror"], self.toggle_mirror
        )

    def toggle_mirror(self):
        """
        Toggles mirror visibility
        """
        self.is_mirror_visible = not self.is_mirror_visible
        self.mirror_buffer.setActive(self.is_mirror_visible)
        if self.is_mirror_visible:
            self.mirror_card.show()
        else:
            self.mirror_card.hide()

    def clean(self):
        """
        Cleans the mirror object
        """
        # Remove key binding
        self.game.app.ignore(  # TODO handle elsewhere
            self.game.key_bindings["toggle_mirror"]
        )
        # Delete camera
        self.mirror_np.removeNode()
        self.mirror_cam = None
        # Delete buffer
        self.mirror_buffer.removeAllDisplayRegions()
        self.mirror_buffer.clearRenderTextures()
        self.game.app.graphicsEngine.removeWindow(self.mirror_buffer)
        self.mirror_buffer = None
        # Remove card
        self.mirror_card.removeNode()
        self.game = None
