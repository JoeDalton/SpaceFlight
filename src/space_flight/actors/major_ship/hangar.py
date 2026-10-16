from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import quaternion

from space_flight.actors.major_ship.sub_system import SubSystem
from space_flight.actors.ship import load_ship_configuration
from space_flight.ai.formation import Formation

if TYPE_CHECKING:
    from space_flight.actors.bot import Bot
    from space_flight.actors.major_ship.major_ship import MajorShip
    from space_flight.game.flight_state import FlightState
    from space_flight.weapons.loadout import Loadout

# A launch waits while fewer interaction slots than this are free, so fighters
# never take the last ones (adding an actor to a full Interactions raises)
HANGAR_ACTOR_SLOT_RESERVE = 4


@dataclass(eq=False)
class LaunchOrder:
    """
    A queued request for fighters from one hangar, filled one launch at a time.

    :param fighter_type: The fighter model launched
    :param count: How many fighters to launch
    :param on_launched: Called with each launched fighter's Bot
    :param primary_target_ids: Primary targets given to each launched fighter
    :param formation_shape: The launched fighters' formation shape (None for
        none)
    :param formation_scale_m: Spacing of its slots
    :param loadout: The launched fighters' weapons (None for their default)
    """

    fighter_type: str
    count: int
    on_launched: Callable[[Bot], None] | None = None
    primary_target_ids: list = field(default_factory=list)
    formation_shape: str | None = "arrowhead"
    formation_scale_m: float = Formation.FIGHTER_SCALE_M
    loadout: Loadout | None = None
    #: Pawn ids of the fighters launched so far, in launch order
    ids: list = field(default_factory=list)
    #: The launched fighters' formation (the first one out leads)
    formation: Formation | None = None
    #: Set when the order can no longer be filled (hangar destroyed, no stock)
    cancelled: bool = False

    @property
    def remaining(self) -> int:
        """Fighters still to launch (0 once cancelled)."""
        return 0 if self.cancelled else max(self.count - len(self.ids), 0)

    @property
    def done(self) -> bool:
        """Every fighter is launched, or the order was cancelled."""
        return self.remaining == 0


class Hangar(SubSystem):
    """
    A hangar bay of a major ship, launching fighter bots on request.

    It is a destructible subsystem with a box collider (the bay). What it holds
    is its stock, set by the level once the ship exists (set_stock): how many
    fighters of each type. Fighters are launched one at a time,
    launch_interval_s apart, just outside the box face its launch_direction
    points out of, nose first along that direction (so their thrust carries
    them away from the bay), with the ship's velocity plus launch_speed_mps
    along it, and the ship's team (read at launch). A launch waits while
    max_active of its fighters are alive, or while the interaction slots run
    low (HANGAR_ACTOR_SLOT_RESERVE). Destroying the hangar, or its ship,
    cancels whatever is left to launch.

    :param game: The game/flight state
    :param parent: The ship it is on
    :param relative_position: The bay's centre, ship-local
    :param half_extents_m: The bay box's half-sizes along the ship axes
    :param health: Initial (and maximum) health
    :param explosion_scale: Size of its death explosion
    :param group_size: How many fighters a launch request gets by default
    :param launch_interval_s: Time between two launches
    :param max_active: How many of its fighters may be alive at once
    :param launch_direction: The way fighters leave the bay, ship-local (the
        bay's open face)
    :param launch_speed_mps: Launch speed along launch_direction, relative to
        the ship
    :param launch_margin_m: Clearance between the bay box and a launched
        fighter's collision sphere
    :param name: Node and display name
    :param ion_capacity: Ion damage it takes to be disabled (see
        :class:`SubSystem`); ION_CAPACITY_HEALTH_FRACTION of its
        health by default
    """

    def __init__(
        self,
        game: FlightState,
        parent: MajorShip,
        relative_position: np.ndarray = np.zeros(3),
        half_extents_m: Sequence[float] = (20.0, 20.0, 10.0),
        health: float = 3000.0,
        explosion_scale: float = 40.0,
        group_size: int = 3,
        launch_interval_s: float = 1.5,
        max_active: int = 6,
        launch_direction: Sequence[float] = (0.0, 0.0, -1.0),
        launch_speed_mps: float = 30.0,
        launch_margin_m: float = 5.0,
        name: str = "hangar",
        ion_capacity: float | None = None,
    ):
        super().__init__(
            game=game,
            parent=parent,
            relative_position=relative_position,
            half_extents_m=half_extents_m,
            health=health,
            explosion_scale=explosion_scale,
            name=name,
            ion_capacity=ion_capacity,
        )
        self.relative_position = np.asarray(relative_position, dtype=float)
        #: Fighters it can still launch, per fighter type (see set_stock)
        self.stock: dict[str, int] = {}
        # Collision radius of each stocked fighter type, which sets its launch
        # point (see _fighter_radius_m)
        self._fighter_radii_m = {}
        self.group_size = group_size
        self.launch_interval_s = launch_interval_s
        self.max_active = max_active
        direction = np.asarray(launch_direction, dtype=float)
        self.launch_direction = direction / np.linalg.norm(direction)
        self.launch_speed_mps = launch_speed_mps
        self.launch_margin_m = launch_margin_m

        self.orders: list[LaunchOrder] = []
        self._launched_ids: list = []
        self._launch_serial = 0
        self._next_launch_s = -np.inf

        # Visible geometry: a placeholder box matching the collider (the stock
        # unit cube spans 0..1), flat-shaded like the other placeholder
        # subsystems to be visible under any lighting.
        # TODO: swap for a proper hangar bay model.
        self.model = self.game.app.loader.loadModel("models/box")
        self.model.setTextureOff(1)
        self.model.setColor(0.3, 0.9, 0.3, 1.0)
        self.model.setScale(*(2.0 * self.half_extents_m))
        self.model.setPos(*(-self.half_extents_m))
        self.model.reparentTo(self.node)
        self.model.setShaderOff()
        self.model.setLightOff()

        self.add_task(method=self.update)

    # ------------------------------------------------------------------
    # Requests and state
    # ------------------------------------------------------------------

    def set_stock(self, stock: Mapping[str, int]):
        """
        Set what the hangar holds: how many fighters of each type (any fighter
        ship type). Called by the level once the ship exists.

        :param stock: Fighter type -> number of fighters
        :raises ValueError: on a negative count
        :raises FileNotFoundError: on an unknown ship type
        """
        for fighter_type, count in stock.items():
            if count < 0:
                raise ValueError(f"{self.name}: negative stock of {fighter_type!r}")
            # Read its config now, so an unknown type fails here
            self._fighter_radius_m(fighter_type)
        self.stock = dict(stock)

    def launch(
        self,
        fighter_type: str,
        count: int | None = None,
        on_launched: Callable[[Bot], None] | None = None,
        primary_target_ids: Sequence = (),
        formation: str | None = "arrowhead",
        formation_scale_m: float = Formation.FIGHTER_SCALE_M,
        loadout: Loadout | None = None,
    ) -> LaunchOrder:
        """
        Queue a launch of count fighters of fighter_type (group_size by
        default), launched one at a time behind any earlier request, as long
        as the stock of that type lasts.

        :param fighter_type: The fighter model to launch, one of the stock's
        :param count: How many fighters to launch
        :param on_launched: Called with each launched fighter's Bot
        :param primary_target_ids: Primary targets given to each fighter
        :param formation: The launched fighters' formation shape:
            "arrowhead", "diamond", "around_diamond", or None for none
        :param formation_scale_m: Spacing of its slots
        :param loadout: The fighters' weapons; None for their default loadout
        :return: The order, filled as the fighters launch (already cancelled,
            launching nothing, if that type's stock is empty or the hangar
            cannot launch)
        :raises KeyError: if fighter_type is not in the stock
        """
        if fighter_type not in self.stock:
            raise KeyError(
                f"{self.name}: no {fighter_type!r} in its stock {sorted(self.stock)}"
            )
        order = LaunchOrder(
            fighter_type=fighter_type,
            count=self.group_size if count is None else count,
            on_launched=on_launched,
            primary_target_ids=list(primary_target_ids),
            formation_shape=formation,
            formation_scale_m=formation_scale_m,
            loadout=loadout,
        )
        if self.stock[fighter_type] <= 0 or not self.is_operational:
            order.cancelled = True
        else:
            self.orders.append(order)
        return order

    @property
    def is_operational(self) -> bool:
        """The hangar and its ship are alive (neither dying nor destroyed)."""
        host = self.mounted_on
        return (
            not self.is_dying
            and self.health > 0.0
            and host is not None
            and not host.is_dead
            and host.health > 0.0
            and not getattr(host.parent, "is_dying", False)
        )

    def launched_pawns(self) -> list:
        """Its launched fighters still alive, in launch order."""
        interactions = self.game.interactions
        id_dict = interactions.actors_id_dict
        return [
            interactions.actors[id_dict[i]] for i in self._launched_ids if i in id_dict
        ]

    @property
    def n_active(self) -> int:
        """How many of its launched fighters are alive."""
        return len(self.launched_pawns())

    def _fighter_radius_m(self, fighter_type: str) -> float:
        """
        A fighter type's collision radius, read from its config once.

        :param fighter_type: The fighter ship type
        :return: Its hit_box_radius_m
        """
        if fighter_type not in self._fighter_radii_m:
            self._fighter_radii_m[fighter_type] = load_ship_configuration(fighter_type)[
                "hit_box_radius_m"
            ]
        return self._fighter_radii_m[fighter_type]

    def launch_orientation(self, body_to_world: np.ndarray) -> np.ndarray:
        """
        A launched fighter's orientation: its nose along launch_direction, its
        top toward the ship axis the most across it (the bow, for a ventral or
        dorsal bay).

        :param body_to_world: The ship's body axes (right, forward, up) as
            columns, in world space
        :return: The orientation quaternion (w, x, y, z)
        """
        forward = body_to_world @ self.launch_direction
        ship_axes = (body_to_world[:, 1], body_to_world[:, 2], body_to_world[:, 0])
        reference = min(ship_axes, key=lambda axis: abs(np.dot(axis, forward)))
        up = reference - np.dot(reference, forward) * forward
        up /= np.linalg.norm(up)
        right = np.cross(forward, up)
        return quaternion.as_float_array(
            quaternion.from_rotation_matrix(np.column_stack((right, forward, up)))
        )

    def launch_point(self, fighter_radius_m: float) -> np.ndarray:
        """
        Where a fighter is launched, ship-local: just outside the bay box face
        launch_direction points out of, clear of it by launch_margin_m.

        :param fighter_radius_m: The fighter's collision radius
        :return: The launch point, in the ship's frame
        """
        box_extent_m = float(np.abs(self.launch_direction) @ self.half_extents_m)
        distance_m = box_extent_m + fighter_radius_m + self.launch_margin_m
        return self.relative_position + distance_m * self.launch_direction

    # ------------------------------------------------------------------
    # Per-frame
    # ------------------------------------------------------------------

    def update(self):
        """
        Launch the next queued fighter when it is due and allowed; cancel a
        request once its type's stock is spent, and every request once the
        hangar or its ship is destroyed. A disabled hangar launches nothing, but
        keeps its requests.
        """
        if not self.is_operational:
            self._cancel_orders()
            return
        if self.is_disabled:
            return
        self.orders = [order for order in self.orders if not order.done]
        if not self.orders:
            return
        now_s = self.game.game_time.get_current_time()
        if now_s < self._next_launch_s:
            return
        if self.n_active >= self.max_active:
            return
        if len(self.game.interactions.free_slots) <= HANGAR_ACTOR_SLOT_RESERVE:
            return
        order = self.orders[0]
        if self.stock[order.fighter_type] <= 0:
            # Its type ran out: what is left of it is cancelled, the next
            # request goes on
            order.cancelled = True
            return
        self._launch_one(order)
        self._next_launch_s = now_s + self.launch_interval_s

    def on_enabled(self):
        """
        Back online: the next launch waits for a full launch interval.
        """
        self._next_launch_s = (
            self.game.game_time.get_current_time() + self.launch_interval_s
        )

    def _launch_one(self, order: LaunchOrder) -> Bot:
        """
        Launch one fighter for order.

        :param order: The order it fills
        :return: The launched fighter's Bot
        """
        # Deferred import: bot imports the major ships, so importing spawn_bot
        # at the top would be circular.
        from space_flight.actors.bot import spawn_bot

        host = self.mounted_on
        fighter_type = order.fighter_type
        # Ship-local to world: the host's body axes as columns
        body_to_world = np.column_stack((host.right, host.forward, host.up))
        position = host.position + body_to_world @ self.launch_point(
            self._fighter_radius_m(fighter_type)
        )
        velocity = host.speed + body_to_world @ (
            self.launch_speed_mps * self.launch_direction
        )

        bot = spawn_bot(
            game=self.game,
            name=f"{host.parent.name}_{self.name}_{self._launch_serial}",
            bot_type="fighter",
            pawn_model=fighter_type,
            team=host.team,
            ini_position=position,
            ini_orientation=self.launch_orientation(body_to_world),
            ini_speed=velocity,
            loadout=order.loadout,
        )
        self._launch_serial += 1
        self.stock[fighter_type] -= 1
        pawn = bot.pawn
        order.ids.append(pawn.id)
        self._launched_ids.append(pawn.id)

        if order.formation_shape is not None:
            if order.formation is None or len(order.formation.ship_ids) >= len(
                order.formation.relative_positions
            ):
                # The first fighter out leads; a full formation starts a new one
                order.formation = Formation(
                    scale_m=order.formation_scale_m, shape=order.formation_shape
                )
            order.formation.add_ship(ship=pawn)
        bot.tactician.primary_target_ids.extend(order.primary_target_ids)
        if order.on_launched is not None:
            order.on_launched(bot)
        return bot

    def _cancel_orders(self):
        """Cancel every queued request."""
        for order in self.orders:
            order.cancelled = True
        self.orders = []

    def clean(self):
        """
        Cancel what is left to launch, then clean the subsystem.
        """
        if not self.is_clean:
            self._cancel_orders()
            self._launched_ids = []
        super().clean()
