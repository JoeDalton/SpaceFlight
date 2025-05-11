from direct.showbase.ShowBase import ShowBase
from direct.interval.IntervalGlobal import LerpPosInterval
from panda3d.core import CardMaker, TransparencyAttrib, LVector3

from direct.gui.OnscreenText import OnscreenText

import quaternion
import numpy as np
from utils import rotate_single_vector

LASER_SPEED = 1000

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

        self.message = OnscreenText(text="", pos=(0, 0.85), scale=0.07, fg=(1, 0, 0, 1))

    def fire(self):
        # Create flat quad
        cm = CardMaker("laser")
        cm.set_frame(-1.15, 1.15, -1.01, 1.01)
        laser_np = self.app.render.attach_new_node(cm.generate())
        laser_np.set_texture(self.laser_texture)
        laser_np.set_transparency(TransparencyAttrib.MAlpha)
        # laser_np.set_billboard_axis()

        # Start position and orientation relative to the ship
        ship_pos = self.parent_ship.node.get_pos(self.app.render)
        ship_quat = self.parent_ship.node.get_quat(self.app.render)
        q_ship = np.quaternion(*ship_quat)
        ship_dir = ship_quat.get_forward()
        # laser_np.set_quat(ship_quat)

        # Compute start and end positions
        relative_start_position = np.array(self.cannon_positions[self.next_cannon_idx])
        absolute_start_position = (
            np.array([*ship_pos]) +
            rotate_single_vector(q_ship, relative_start_position)
        )
        start_pos = LVector3(*absolute_start_position)
        end_pos = start_pos + ship_dir * self.laser_range
        duration = self.laser_range / LASER_SPEED
        
        # Don't rely on scene lighting since it emits its own light
        laser_np.set_light_off()

        # Preset movement
        laser_np.set_pos(start_pos)
        LerpPosInterval(laser_np, duration, end_pos).start()
        # Make it disappear at the end of range
        self.app.doMethodLater(duration, lambda t: laser_np.remove_node(), "RemoveLaser")

        # TODO: Debug
        self.message.setText("Shoot!")
        self.app.doMethodLater(0.3, lambda t: self.message.setText(''), "RemoveLaser")

        # Prepare next laser shot
        self.next_cannon_idx = (self.next_cannon_idx + 1) % self.n_cannon
