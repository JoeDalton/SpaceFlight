import numpy as np

from space_flight.actors.capital_ship.shield import Shield
from space_flight.actors.capital_ship.sub_system import SubSystem


class ShieldGenerator(SubSystem):
    """
    An external shield generator subsystem.

    A shield generator is a :class:`SubSystem` whose defining feature is to
    project a :class:`Shield` around its parent ship. The shield is brought down
    either by destroying this generator (which destroys the shield outright) or
    by depleting the shield's own strength (which merely disables it until it
    regenerates).

    :param game: The game/flight state
    :param parent: The ship this generator is mounted on
    :param relative_position: Mounting position relative to the parent ship node
    :param hit_box_radius_m: Radius of the generator's spherical collider
    :param health: Initial (and maximum) health of the generator
    :param explosion_scale: Size of the generator's death explosion
    :param shield_conf: Shield parameters (health, regen_rate, color, and either
        a ``shape`` primitive spec or a ``model`` path)
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
        shield_conf: dict = None,
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

        # Project the shield. It is a Destructible in its own right and is cleaned
        # up centrally when it dies (i.e. when this generator is destroyed). Its
        # geometry (sphere/tube primitive or a shared model) comes from the config.
        shield_conf = shield_conf or {}
        self.shield = Shield(
            game=game,
            generator=self,
            health=shield_conf.get("health", 4000.0),
            regen_rate=shield_conf.get("regen_rate", 0.0),
            color=shield_conf.get("color"),
            shape=shield_conf.get("shape"),
            model=shield_conf.get("model"),
        )

    def handle_health(self):
        """
        Monitor the generator's health and drop the reference to its shield once
        the shield has died, so we do not hold onto a cleaned husk.
        """
        super().handle_health()
        if self.shield is not None and self.shield.is_dead:
            self.shield = None

    def clean(self):
        """
        Clean the generator.

        The shield is a Destructible in its own right, so we must *not* clean it
        here: it is still in ``alive_objects`` and would be reprocessed (and
        crash) by the death handler. Instead, destroying this generator makes
        :meth:`Shield.get_health` report zero, so the central death handling
        cleans the shield on the next frame. We only hide it now for an immediate
        visual response and drop our reference so we do not touch a husk.
        """
        if not self.is_clean:
            if self.shield is not None:
                self.shield.set_visible(False)
                self.shield = None
            super().clean()
