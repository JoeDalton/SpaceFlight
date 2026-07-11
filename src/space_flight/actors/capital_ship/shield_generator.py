import numpy as np

from space_flight.actors.capital_ship.sub_system import SubSystem


class ShieldGenerator(SubSystem):
    """
    An external shield generator subsystem.

    A capital ship may mount **several** shield generators that together project a
    **single shared** :class:`~space_flight.actors.capital_ship.shield.Shield`.
    The shield is built and owned by the ship, not by the generators, and it
    *polls* the generators' alive state to scale its perks **pro rata**:
    destroying one reduces the shield's strength and regeneration by its share
    (remaining / initial generators); destroying the last one brings the shield
    down for good.

    The coupling is one-way -- the shield watches the generators, the generators
    know nothing of the shield -- so a generator is just a plain destructible
    :class:`SubSystem`: a shoot-off target that happens to prop up the shield.

    :param game: The game/flight state
    :param parent: The ship this generator is mounted on
    :param relative_position: Mounting position relative to the parent ship node
    :param hit_box_radius_m: Radius of the generator's spherical collider
    :param health: Initial (and maximum) health of the generator
    :param explosion_scale: Size of the generator's death explosion
    :param name: Node and display name of the generator
    """

    def __init__(
        self,
        game,
        parent,
        relative_position: np.ndarray = np.zeros(3),
        hit_box_radius_m: float = 5.0,
        health: float = 1000.0,
        explosion_scale: float = 10.0,
        name: str = "shield_generator",
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
        # Visible geometry: a placeholder sphere matching the collider, so the
        # subsystem can be seen and targeted. Flat-shaded like the waypoint
        # markers (see ui/player_waypoints.py) to be visible under any lighting.
        # TODO: swap for a proper per-subsystem 3D model.
        self.model = self.game.app.loader.loadModel("models/misc/smiley")
        self.model.setTextureOff(1)
        self.model.setColor(0.6, 0.6, 0.65, 1.0)
        self.model.setScale(self.hit_box_radius_m)
        self.model.reparentTo(self.node)
        self.model.setShaderOff()
        self.model.setLightOff()
