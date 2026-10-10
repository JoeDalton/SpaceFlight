from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from space_flight.actors.major_ship.sub_system import SubSystem

if TYPE_CHECKING:
    from space_flight.actors.major_ship.major_ship import MajorShip
    from space_flight.game.flight_state import FlightState


class TargetingSystem(SubSystem):
    """
    A fire-control subsystem that boosts the turrets of its ship.

    While alive, it grants every turret mounted on the same ship auto-aim
    (tuned by :attr:`auto_aim_params`) and a faster rate of fire
    (:attr:`fire_rate_multiplier`). The turrets *pull* these each frame (see
    :meth:`~space_flight.actors.major_ship.turret.Turret._active_targeting_system`),
    so the targeting system need not know its turrets; once it is dead the
    turrets revert to unassisted fire at their base rate.

    :param game: The game/flight state
    :param parent: The ship this targeting system is mounted on
    :param relative_position: Mounting position relative to the parent ship node
    :param hit_box_radius_m: Radius of the targeting system's spherical collider
    :param health: Initial (and maximum) health of the targeting system
    :param explosion_scale: Size of the targeting system's death explosion
    :param fire_rate_multiplier: Factor applied to the fire rate of boosted
        turrets (e.g. 2.0 makes them fire twice as fast)
    :param auto_aim_params: Auto-aim tuning passed to
        :meth:`~space_flight.ai.auto_aim.AutoAim.configure` on boosted turrets
        (e.g. target_lock_delay_s, max_assist_angle_deg). Empty falls
        back to the auto-aim defaults.
    :param name: Node and display name of the targeting system
    """

    def __init__(
        self,
        game: FlightState,
        parent: MajorShip,
        relative_position: np.ndarray = np.zeros(3),
        hit_box_radius_m: float = 5.0,
        health: float = 1000.0,
        explosion_scale: float = 10.0,
        fire_rate_multiplier: float = 2.0,
        auto_aim_params: dict | None = None,
        name: str = "targeting_system",
    ):
        super().__init__(
            game=game,
            parent=parent,
            relative_position=relative_position,
            hit_box_radius_m=hit_box_radius_m,
            health=health,
            explosion_scale=explosion_scale,
            name=name,
        )
        self.fire_rate_multiplier = fire_rate_multiplier
        self.auto_aim_params = auto_aim_params or {}

        # Visible geometry: a placeholder sphere matching the collider, so the
        # subsystem can be seen and targeted. Flat-shaded like the waypoint
        # markers (see ui/player_waypoints.py) to be visible under any lighting.
        # TODO: swap for a proper per-subsystem 3D model.
        self.model = self.game.app.loader.loadModel("models/misc/smiley")
        self.model.setTextureOff(1)
        self.model.setColor(0.9, 0.5, 0.2, 1.0)
        self.model.setScale(self.hit_box_radius_m)
        self.model.reparentTo(self.node)
        self.model.setShaderOff()
        self.model.setLightOff()
