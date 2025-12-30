from panda3d.core import Camera, BitMask32, NodePath, CardMaker, Texture, WindowProperties
from direct.showbase.ShowBaseGlobal import aspect2d

MIRROR_ASPECT_RATIO = 2
MIRROR_VERTICAL_RESOLUTION = 128
MIRROR_HALF_VERTICAL_SIZE = 0.2
MIRROR_FOV = 60

class RearViewMirror:
    def __init__(self, app, player_node):    
        self.app = app

        mirror_tex = Texture()
        mirror_tex.setWrapU(Texture.WMClamp)
        mirror_tex.setWrapV(Texture.WMClamp)

        mirror_buffer = self.app.win.makeTextureBuffer(
            "RearViewBuffer",
            MIRROR_VERTICAL_RESOLUTION * MIRROR_ASPECT_RATIO, MIRROR_VERTICAL_RESOLUTION,
            mirror_tex
        )
        mirror_buffer.setClearColor((0, 0, 0, 1))


        mirror_cam = Camera("rear_view_cam")
        mirror_np = NodePath(mirror_cam)

        mirror_cam.setLens(self.app.camLens.makeCopy())
        mirror_cam.getLens().setFov(MIRROR_FOV)  # Narrower = more realistic mirror
        mirror_cam.getLens().setAspectRatio(MIRROR_ASPECT_RATIO)

        mirror_cam_node = mirror_buffer.makeDisplayRegion().setCamera(mirror_np)

        mirror_np.reparentTo(player_node)
        mirror_np.setPos(0, -2, 1.5)  # Slightly behind and above
        mirror_np.setHpr(180, 0, 0)   # Look backwards

        cm = CardMaker("mirror")
        cm.setFrame(-MIRROR_ASPECT_RATIO*MIRROR_HALF_VERTICAL_SIZE, MIRROR_ASPECT_RATIO*MIRROR_HALF_VERTICAL_SIZE, -MIRROR_HALF_VERTICAL_SIZE, MIRROR_HALF_VERTICAL_SIZE)

        self.mirror_card = NodePath(cm.generate())
        self.is_mirror_visible = True
        
        # Mirror in 3d space
        # mirror_card.reparentTo(self.app.camera)
        # mirror_card.setPos(0, 0.5, 0.0)  # In front of the player
        # mirror_card.setScale(-1, 1, 1) # Flip image horizontally

        # Mirror in 2D screen layout
        self.mirror_card.reparentTo(aspect2d)
        self.mirror_card.setPos(0, 0, 0.85)
        self.mirror_card.setScale(-1, 1, 1)

        # Apply mirror camera as a texture of the card
        self.mirror_card.setTexture(mirror_tex)

        mirror_buffer.setSort(-100)
        mirror_np.node().setCameraMask(BitMask32.bit(1))


        self.app.accept(self.app.key_bindings["toggle_mirror"], self.toggle_mirror)

    def toggle_mirror(self):
        """
        Toggles mirror visibility
        """
        self.is_mirror_visible = not self.is_mirror_visible
        if self.is_mirror_visible:
            self.mirror_card.show()
        else:
            self.mirror_card.hide()