from direct.showbase.ShowBase import ShowBase
from direct.interval.IntervalGlobal import LerpPosInterval
from panda3d.core import CardMaker, TransparencyAttrib, LVector3

from direct.gui.OnscreenText import OnscreenText

LASER_SPEED = 500

class LaserCannon():
    
    def __init__(self, app: ShowBase, parent_ship):
        self.parent_ship = parent_ship
        self.app = app

        # Cannon configuration
        self.cannon_positions = self.parent_ship.conf["cannon_positions"]
        self.n_cannon = len(self.cannon_positions)
        self.next_cannon_idx = 0

        # Laser configuration
        self.laser_range = self.parent_ship.conf["laser_range"]
        color = self.parent_ship.conf["laser_color"]

        self.laser_texture = self.app.loader.loadTexture(f"models/lasers/laser_{color}.png")

        # TODO temporary
        # Press SPACE to shoot
        self.app.accept("space", self.fire_laser)

        self.message = OnscreenText(text="", pos=(0, 0.85), scale=0.07, fg=(1, 0, 0, 1))



    def fire_laser(self):
        # Create flat quad
        cm = CardMaker("laser")
        cm.set_frame(-1.15, 1.15, -1.01, 1.01)
        laser_np = self.app.render.attach_new_node(cm.generate())
        laser_np.set_texture(self.laser_texture)
        laser_np.set_transparency(TransparencyAttrib.MAlpha)
        laser_np.set_billboard_axis()

        # Start just under the camera
        cam_pos = self.app.camera.get_pos(self.app.render)
        cam_dir = self.app.camera.get_quat(self.app.render).get_forward()
        start_pos = cam_pos + LVector3(2, 0, 0.5)
        end_pos = start_pos + cam_dir * self.laser_range
        duration = self.laser_range / LASER_SPEED
        laser_np.set_pos(start_pos)

        # Don't rely on scene lighting since it emits its own light
        laser_np.set_light_off()

        # Preset movement
        LerpPosInterval(laser_np, duration, end_pos).start()
        # Make it disappear at the end of range
        self.app.doMethodLater(duration, lambda t: laser_np.remove_node(), "RemoveLaser")

        self.message.setText("Shoot!")
        self.app.doMethodLater(0.3, lambda t: self.message.setText(''), "RemoveLaser")
