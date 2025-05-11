import numpy as np
from airseas.quat_ops import rotation_z_axis
from direct.task import Task
from panda3d.core import LineSegs, NodePath

from utils import rotate_single_vector

N_POINT_PER_ARC = 50  # Enough points to make it smooth but not too much for performance
N_ARC_PER_90_DEG = 9  # One arc per 10 deg


class FlightWindowRenderer:
    """
    A class to render a flight window
    """

    def __init__(self, app, thickness=1, color=(1, 1, 1, 1)):
        npitch = N_ARC_PER_90_DEG
        nroll = 2 * N_ARC_PER_90_DEG - 1
        gpitchs = np.deg2rad(np.linspace(0.0, 90.0, npitch))
        gpitchs = gpitchs[:-1]  # Remove arc at 90deg gpitch since it's only a point
        grolls = np.deg2rad(np.linspace(-90.0, 90.0, nroll))
        self.arcs = []
        # Create all iso-gpitch arcs
        for pitch in gpitchs:
            self.arcs.append(
                ArcRenderer(
                    app=app,
                    iso="gpitch",
                    value_rad=pitch,
                    thickness=thickness,
                    color=color,
                )
            )
        # Create all iso-groll arcs
        for roll in grolls:
            self.arcs.append(
                ArcRenderer(
                    app=app,
                    iso="groll",
                    value_rad=roll,
                    thickness=thickness,
                    color=color,
                )
            )


class ArcRenderer:
    """
    A class to render an arc in the simu space
    """

    def __init__(self, app, iso, value_rad, thickness, color):
        assert value_rad >= -np.pi and value_rad <= np.pi
        self.value_rad = value_rad
        self.iso = iso
        self.app = app
        self.arc_model = LineSegs()
        self.arc_model.setColor(*color)  # Opacity does not work on linux
        self.arc_model.setThickness(thickness)  # Thickness does not work on linux
        self.arc_node = self.arc_model.create()
        self.arc_path = NodePath(self.arc_node)
        self.arc_path.reparentTo(self.app.render)
        self.compute_base_points()
        self.app.taskMgr.add(
            self.draw_arc_task, f"draw_arc_iso_{iso}_{value_rad}_rad_task"
        )

    def compute_base_points(self):
        """
        Computes the segment end-points to draw the unit arc

        min and max angles are the angles to be included in the arc.

        - For an iso-groll arc, it must take all gpitch values (i.e. [0, 90])
        - For an iso-gpitch arc, it must take all groll values (i.e. [-90, 90])
        """
        if self.iso == "groll":
            self.min_angle = np.deg2rad(0.0)
            self.max_angle = np.deg2rad(90.0)
            self.base_points = np.zeros((N_POINT_PER_ARC, 3))
            self.angles = np.linspace(self.min_angle, self.max_angle, N_POINT_PER_ARC)
            for angle_idx in range(N_POINT_PER_ARC):
                angle = self.angles[angle_idx]
                self.base_points[angle_idx, :] = [
                    np.sin(angle),
                    np.sin(self.value_rad) * np.cos(angle),
                    np.cos(self.value_rad) * np.cos(angle),
                ]
        elif self.iso == "gpitch":
            self.min_angle = np.deg2rad(-90.0)
            self.max_angle = np.deg2rad(90.0)
            self.base_points = np.zeros((N_POINT_PER_ARC, 3))
            self.angles = np.linspace(self.min_angle, self.max_angle, N_POINT_PER_ARC)
            for angle_idx in range(N_POINT_PER_ARC):
                angle = self.angles[angle_idx]
                self.base_points[angle_idx, :] = [
                    np.sin(self.value_rad),
                    np.sin(angle) * np.cos(self.value_rad),
                    np.cos(angle) * np.cos(self.value_rad),
                ]
        else:
            raise ValueError(
                f"iso={self.iso} is not supported. Only `gpitch` and `groll` are."
            )

    def draw_arc_task(self, task):
        """
        At each frame, draw the arc according to the drum position, tether length
        and wind direction
        """

        # Scale the arc with tether length
        # not RPOD, to make tether easing more visible
        radius = self.app.dataflow.get("TETHER_LENGTH_M")
        # Rendered world is in ENU coordinates
        origin = np.array(
            [
                self.app.dataflow.get("Y_DRUM_NED_M"),
                self.app.dataflow.get("X_DRUM_NED_M"),
                -self.app.dataflow.get("Z_DRUM_NED_M"),
            ]
        )
        # Scale the arc
        points = self.base_points * radius

        # Turn the arc with wind direction
        u_wind_ned = self.app.dataflow.get("U_WIND_NED_MPS", 30.0)
        v_wind_ned = self.app.dataflow.get("V_WIND_NED_MPS", 30.0)
        z_rot_deg = np.rad2deg(np.arctan2(u_wind_ned, v_wind_ned))
        q_wind = rotation_z_axis(z_rot_deg)
        points = rotate_single_vector(q_wind, points)

        # Move the arc with the drum
        points += origin

        # Draw the arc
        self.arc_model.reset()

        # Move to the first point
        self.arc_model.moveTo(*points[0])
        # Draw lines between each consecutive point
        for point in points[1:]:
            self.arc_model.drawTo(*point)

        # Update the NodePath with the new line.
        self.arc_node = self.arc_model.create()
        self.arc_path.removeNode()  # Remove the old NodePath
        self.arc_path = NodePath(self.arc_node)
        self.arc_path.reparentTo(self.app.render)
        return Task.cont
