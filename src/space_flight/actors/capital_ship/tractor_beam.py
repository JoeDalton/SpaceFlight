import logging

import numpy as np
import yaml

from space_flight import DATAFILES_PATH, EPSILON_TOLERANCE
from space_flight.actors.capital_ship.tracking_mount import TrackingMount
from space_flight.ai import Personality
from space_flight.utils.state_machine import Cooldown, StateMachine

# Grab state machine states.
_SEARCHING = "searching"
_GRABBING = "grabbing"

LOGGER = logging.getLogger()


class TractorBeamProjector(TrackingMount):
    """
    A tractor beam projector: a :class:`TrackingMount` that grabs a prey and
    reels it in instead of shooting it.

    It aims its antenna at a prey exactly like a turret aims its barrel. When a
    prey enters the grab cone (which turns with the antenna) within range, the
    projector locks on and, every frame, applies two world-frame forces to the
    prey via :meth:`~space_flight.actors.ship.Ship.apply_external_force`:

    - a drag -k * ||v_rel|| * v_rel opposing the prey's velocity *relative to
      the projector's ship*,
    - a light attraction pulling the prey toward the projector.

    The **cone acquires, range retains**: once locked, the beam holds the prey as
    long as it stays within range. It releases when the maximum grab time elapses,
    when (after a minimum grab time) the prey wrenches free by exceeding a relative
    speed, when the prey leaves range, or when the prey is gone. A cooldown then
    prevents an immediate re-grab. Grabbing the player triggers a placeholder SFX.

    Hardware specs (cone, range, force strengths) come from the model config;
    behaviour (grab times, release speed, cooldown) comes from the personality.

    :param game: The game/flight state
    :param parent: The controlling Bot
    :param projector_type: The projector model/config name
    :param mounted_on: The ship this projector is bolted onto
    :param base_position: Mounting position relative to the ship node
    :param base_orientation: Mounting orientation (quaternion) on the ship
    :param ini_yaw_deg: Initial yaw angle
    :param ini_pitch_deg: Initial pitch angle
    :param personality: Behaviour parameters (grab timing, shared with the AI)
    """

    def __init__(
        self,
        game,
        parent,
        projector_type: str,
        mounted_on,
        base_position: np.ndarray = np.zeros(3),
        base_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
        ini_yaw_deg: float = 0.0,
        ini_pitch_deg: float = 30.0,
        personality: dict = Personality.TRACTOR_BEAM_DEFAULT,
    ):
        # Load configuration first: it feeds the TrackingMount parameters below
        filepath = (
            DATAFILES_PATH / f"models/tractor_beams/{projector_type}/configuration.yaml"
        )
        with open(filepath, "r") as f:
            conf = yaml.safe_load(f)

        super().__init__(
            game=game,
            parent=parent,
            mounted_on=mounted_on,
            conf=conf,
            # The antenna reuses a swivelling model (the turret placeholder).
            model_type=conf.get("model_type", "test"),
            base_position=base_position,
            base_orientation=base_orientation,
            ini_yaw_deg=ini_yaw_deg,
            ini_pitch_deg=ini_pitch_deg,
            personality=personality,
            name="tractor_beam",
        )

        # Hardware specs (fixed capability of the device)
        self.range_m = conf["range_m"]
        self.grab_cone_cos = np.cos(np.deg2rad(conf["cone_half_angle_deg"]))
        self.drag_coefficient = conf["drag_coefficient"]
        self.attraction_force_n = conf["attraction_force_n"]

        # Grab state machine (searching <-> grabbing) + re-grab cooldown, both on
        # the game clock so grab timing is uniform with the other subsystems.
        clock = self.game.game_time.get_current_time
        self.grab_sm = StateMachine(initial_state=_SEARCHING, clock=clock)
        self.grabbed_prey_id = None
        self.regrab_cooldown = Cooldown(
            duration_s=self.personality["tractor_beam"]["regrab_cooldown_s"],
            clock=clock,
        )

    @property
    def is_grabbing(self) -> bool:
        """Whether the beam is currently holding a prey."""
        return self.grab_sm.state == _GRABBING

    def _operate(self):
        """
        Per-frame tractor action: keep reeling in the current prey, or try to
        acquire a new one.
        """
        if self.grab_sm.state == _GRABBING:
            self._service_grab()
        else:
            self._try_acquire()

    def _try_acquire(self):
        """
        Lock onto the tactician's prey if it sits inside the grab cone and within
        range, honouring the re-grab cooldown.
        """
        if not self.regrab_cooldown.ready():
            return
        prey = self._resolve_prey(self.target_id)
        if prey is None:
            return
        distance_m, _, to_prey_dir = self._prey_kinematics(prey)
        in_cone = np.dot(to_prey_dir, self.forward) >= self.grab_cone_cos
        if distance_m <= self.range_m and in_cone:
            self._start_grab(prey)

    def _service_grab(self):
        """
        Hold the grabbed prey: release it if a release condition is met, otherwise
        apply the tractor forces for this frame.
        """
        params = self.personality["tractor_beam"]
        prey = self._resolve_prey(self.grabbed_prey_id)
        if prey is None:
            self._release()
            return

        distance_m, v_rel, to_prey_dir = self._prey_kinematics(prey)
        elapsed_s = self.grab_sm.time_in_state_s

        # Out of reach, held too long, or -- once committed for the minimum time
        # -- wrenched free by going fast enough relative to us.
        if distance_m > self.range_m:
            self._release()
            return
        if elapsed_s >= params["max_grab_time_s"]:
            self._release()
            return
        if (
            elapsed_s >= params["min_grab_time_s"]
            and np.linalg.norm(v_rel) >= params["release_speed_mps"]
        ):
            self._release()
            return

        self._apply_tractor_forces(prey, v_rel, to_prey_dir)

    def _apply_tractor_forces(self, prey, v_rel: np.ndarray, to_prey_dir: np.ndarray):
        """
        Apply the drag and attraction forces to the grabbed prey for this frame.

        :param prey: The grabbed prey (a ship)
        :param v_rel: The prey's velocity relative to the projector's ship
        :param to_prey_dir: Unit vector from the projector to the prey
        """
        # Drag opposes the relative velocity with magnitude k * ||v_rel||^2.
        drag_force = -self.drag_coefficient * np.linalg.norm(v_rel) * v_rel
        # Attraction pulls the prey back toward the projector.
        attraction_force = -self.attraction_force_n * to_prey_dir
        prey.apply_external_force(drag_force + attraction_force)

    def _start_grab(self, prey):
        """
        Begin grabbing a prey, cueing the player-grab SFX if it is the player.

        :param prey: The prey to grab
        """
        self.grab_sm.request(_GRABBING, force=True)
        self.grabbed_prey_id = prey.id
        try:
            if prey.id == self.game.player.pawn.id:
                self.game.app.sfx.tractor_beam_grab(game=self.game)
        except AttributeError:
            # No player yet (e.g. headless), or SFX not wired: grabbing still works
            pass

    def _release(self):
        """
        Release the current prey and start the re-grab cooldown, cueing the
        player-release SFX if the freed prey was the player. The prey's external
        force clears itself once we stop applying it.
        """
        try:
            if self.grabbed_prey_id == self.game.player.pawn.id:
                self.game.app.sfx.tractor_beam_release(game=self.game)
        except AttributeError:
            # No player yet (e.g. headless), or SFX not wired: release still works
            pass
        self.grab_sm.request(_SEARCHING, force=True)
        self.grabbed_prey_id = None
        self.regrab_cooldown.trigger()

    def _resolve_prey(self, prey_id):
        """
        Resolve a prey id to a live, grabbable actor (one that can receive a
        force), or None.

        :param prey_id: The prey's actor id
        :return: The prey actor, or None if gone or not grabbable
        """
        if prey_id is None:
            return None
        try:
            index = self.game.interactions.get_actor_index_from_id(prey_id)
        except ValueError:
            return None
        prey = self.game.interactions.actors[index]
        # Only actors that can take a force (ships) can be tractored.
        if not hasattr(prey, "apply_external_force"):
            return None
        return prey

    def _prey_kinematics(self, prey):
        """
        Compute the projector-to-prey geometry and the prey's relative velocity.

        :param prey: The prey actor
        :return: (distance_m, relative velocity vector, unit direction to prey)
        """
        to_prey = np.asarray(prey.position, dtype=float) - self.position
        distance_m = np.linalg.norm(to_prey)
        if distance_m < EPSILON_TOLERANCE:
            to_prey_dir = np.zeros(3)
        else:
            to_prey_dir = to_prey / distance_m
        host_speed = getattr(self.mounted_on, "speed", np.zeros(3))
        v_rel = np.asarray(prey.speed, dtype=float) - np.asarray(
            host_speed, dtype=float
        )
        return distance_m, v_rel, to_prey_dir

    def clean(self):
        """
        Release any grab and clean the mount. The prey's tractor force clears
        itself on the next physics step once we stop applying it.
        """
        if not self.is_clean:
            self.grabbed_prey_id = None
            super().clean()
