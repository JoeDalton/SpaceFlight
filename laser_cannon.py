from direct.showbase.ShowBase import ShowBase
from direct.interval.IntervalGlobal import LerpPosInterval
from panda3d.core import CardMaker, TransparencyAttrib, LVector3, Quat, PointLight
from direct.showbase.ShowBaseGlobal import ClockObject

from direct.gui.OnscreenText import OnscreenText

import quaternion
import numpy as np
from utils import rotate_single_vector
from trihedron import Trihedron

LASER_SPEED = 1000 # TODO: to add to ship speed
SQT2_S = np.sqrt(2.0)/2.0

class LaserCannon():
    
    def __init__(self, app: ShowBase, parent_ship):
        self.parent_ship = parent_ship
        self.app = app

        # Cannon configuration
        self.cannon_positions = self.parent_ship.conf["cannon_positions"]
        self.n_cannon = len(self.cannon_positions)
        
        # Laser configuration
        self.range = self.parent_ship.conf["laser_range"]
        self.fire_delay = 1.0 / self.parent_ship.conf["laser_fire_rate"]
        color = self.parent_ship.conf["laser_color"]

        # Initialize laser model
        laser_intensity = 1.0
        self.light_attenuation = (1, 0.05, 0)
        if color == "red":
            self.light_color = (laser_intensity, 0, 0, 1)
        elif color == "green":
            self.light_color = (0, laser_intensity, 0, 1)
        elif color == "blue":
            self.light_color = (0, 0, laser_intensity, 1)
        else:
            raise ValueError
        self.laser_texture = self.app.loader.loadTexture(f"models/lasers/laser_{color}.png")

        # Initialize cannon
        self.next_cannon_idx = 0
        self.global_clock = ClockObject.getGlobalClock()
        self.last_fire_time = self.global_clock.getFrameTime()

    def fire(self):
        # Fire at prescribed rate
        current_time = self.global_clock.getFrameTime()
        if current_time - self.last_fire_time < self.fire_delay:
            return

        # Create flat quad
        cm = CardMaker("laser")
        cm.set_frame(-0.5, 0.5, -4.0, 4.0)
        laser_np = self.app.render.attach_new_node(cm.generate())
        laser_np.set_texture(self.laser_texture)
        laser_np.set_two_sided(True)
        laser_np.set_transparency(TransparencyAttrib.MAlpha)
        
        # Start position and orientation relative to the ship
        ship_pos = self.parent_ship.node.get_pos(self.app.render)
        ship_quat = self.parent_ship.node.get_quat(self.app.render)
        q_ship = np.quaternion(*ship_quat)
        q_laser = q_ship * np.quaternion(SQT2_S, SQT2_S, 0, 0)
        ship_dir = ship_quat.get_forward()
        laser_np.set_quat(Quat(*quaternion.as_float_array(q_laser)))

        # Compute start and end positions
        relative_start_position = np.array(self.cannon_positions[self.next_cannon_idx])
        absolute_start_position = (
            np.array([*ship_pos]) +
            rotate_single_vector(q_ship, relative_start_position)
        )
        start_pos = LVector3(*absolute_start_position)
        end_pos = start_pos + ship_dir * self.range
        duration = self.range / LASER_SPEED
        light_duration = duration / 3
        
        # Don't rely on scene lighting since it emits its own light
        laser_np.set_light_off()

        # Preset movement
        laser_np.set_pos(start_pos)
        LerpPosInterval(laser_np, duration, end_pos).start()
        # Make it disappear at the end of range
        self.app.doMethodLater(duration, lambda t: laser_np.remove_node(), "RemoveLaser")

        # Add light source on laser
        plight = PointLight('plight')
        plight.setColor(self.light_color)
        plight.set_attenuation(self.light_attenuation)
        plnp = laser_np.attachNewNode(plight)
        plnp.setPos(0, 0, 0)
        self.app.render.setLight(plnp)
        self.app.doMethodLater(light_duration, lambda t: self.app.render.clear_light(plnp), "RemoveLaserLight")
        self.app.doMethodLater(light_duration, lambda t: plnp.remove_node(), "RemoveLaserLight")


        # Prepare next laser shot
        self.next_cannon_idx = (self.next_cannon_idx + 1) % self.n_cannon
        self.last_fire_time = current_time
