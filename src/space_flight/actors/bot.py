from __future__ import annotations

import gc
import logging
import math
import sys
from typing import TYPE_CHECKING, Any

import numpy as np

from space_flight import DEBUG_DELETION, RECORD_GAME
from space_flight.actors.destructibles import Destructible
from space_flight.actors.fighter import Fighter
from space_flight.actors.major_ship import make_major_ship
from space_flight.actors.major_ship.tractor_beam import TractorBeamProjector
from space_flight.actors.major_ship.turret import Turret
from space_flight.ai import Intent, Personality
from space_flight.ai.fighter.fighter_navigator import FighterNavigator
from space_flight.ai.fighter.fighter_pilot import FighterPilot
from space_flight.ai.fighter.fighter_tactician import FighterTactician
from space_flight.ai.major_ship.major_ship_navigator import MajorShipNavigator
from space_flight.ai.major_ship.major_ship_pilot import MajorShipPilot
from space_flight.ai.major_ship.major_ship_tactician import MajorShipTactician
from space_flight.ai.tracking_mount.tracking_mount_navigator import (
    TrackingMountNavigator,
)
from space_flight.ai.tracking_mount.tracking_mount_pilot import TrackingMountPilot
from space_flight.ai.tracking_mount.tracking_mount_tactician import (
    TrackingMountTactician,
)
from space_flight.utils import magnitude

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger()
WAYPOINT_MEETING_TOLERANCE = 10


class Bot(Destructible):
    def __init__(
        self,
        game: FlightState,
        name: str,
        bot_type: str,
        pawn_model: str,
        team: int = 0,
        debug_decisions: bool = False,
        **kwargs: Any,
    ):
        super().__init__(game=game)
        self.name = name
        self.bot_type = bot_type
        if self.bot_type == "fighter":
            self.pawn = Fighter(
                game=self.game,
                parent=self,
                ship_type=pawn_model,
                ini_position=kwargs.get("ini_position", np.zeros(3)),
                ini_orientation=kwargs.get(
                    "ini_orientation", np.array([1.0, 0.0, 0.0, 0.0])
                ),
                ini_speed=kwargs.get("ini_speed", np.zeros(3)),
                is_cockpit=False,
                team=team,
            )

            self.pilot = FighterPilot(game=self.game, pawn=self.pawn)
            self.navigator = FighterNavigator(
                game=self.game, pawn=self.pawn, debug=debug_decisions
            )
            self.tactician = FighterTactician(
                game=self.game, pawn=self.pawn, debug=debug_decisions
            )
        elif self.bot_type == "turret":
            # A turret is a subsystem of the ship it is mounted on (its team is
            # taken from that ship); the bot only controls it.
            self.pawn = Turret(
                game=self.game,
                parent=self,
                turret_type=pawn_model,
                mounted_on=kwargs.get("parent_object"),
                base_position=kwargs.get("base_position", np.zeros(3)),
                base_orientation=kwargs.get(
                    "base_orientation", np.array([1.0, 0.0, 0.0, 0.0])
                ),
                ini_yaw_deg=kwargs.get("ini_yaw_deg", 0.0),
                ini_pitch_deg=kwargs.get("ini_pitch_deg", -30),
                personality=Personality.TURRET_DEFAULT,
            )

            self.pilot = TrackingMountPilot(game=self.game, pawn=self.pawn)
            self.navigator = TrackingMountNavigator(
                game=self.game, pawn=self.pawn, debug=debug_decisions
            )
            self.tactician = TrackingMountTactician(
                game=self.game, pawn=self.pawn, debug=debug_decisions
            )
        elif self.bot_type == "tractor_beam":
            # A tractor beam projector is, like a turret, a subsystem of its ship
            # driven by this bot. It shares the generic tracking-mount AI; only its
            # personality (grab behaviour) and its pawn differ.
            self.pawn = TractorBeamProjector(
                game=self.game,
                parent=self,
                projector_type=pawn_model,
                mounted_on=kwargs.get("parent_object"),
                base_position=kwargs.get("base_position", np.zeros(3)),
                base_orientation=kwargs.get(
                    "base_orientation", np.array([1.0, 0.0, 0.0, 0.0])
                ),
                ini_yaw_deg=kwargs.get("ini_yaw_deg", 0.0),
                ini_pitch_deg=kwargs.get("ini_pitch_deg", -30),
                personality=Personality.TRACTOR_BEAM_DEFAULT,
            )

            self.pilot = TrackingMountPilot(
                game=self.game,
                pawn=self.pawn,
                personality=Personality.TRACTOR_BEAM_DEFAULT,
            )
            self.navigator = TrackingMountNavigator(
                game=self.game,
                pawn=self.pawn,
                personality=Personality.TRACTOR_BEAM_DEFAULT,
                debug=debug_decisions,
            )
            self.tactician = TrackingMountTactician(
                game=self.game,
                pawn=self.pawn,
                personality=Personality.TRACTOR_BEAM_DEFAULT,
                debug=debug_decisions,
            )
        elif self.bot_type == "major_ship":
            # The ship config picks the class: an escort ship or a capital ship
            self.pawn = make_major_ship(
                game=self.game,
                parent=self,
                ship_type=pawn_model,
                ini_position=kwargs.get("ini_position", np.zeros(3)),
                ini_orientation=kwargs.get(
                    "ini_orientation", np.array([1.0, 0.0, 0.0, 0.0])
                ),
                ini_speed=kwargs.get("ini_speed", np.zeros(3)),
                is_cockpit=False,
                team=team,
            )

            # The ship class says how its bot flies it (see EscortShip and
            # CapitalShip): a scripted capital ship has no tactician (it always
            # patrols) and no collision avoidance
            personality = self.pawn.personality
            self.pilot = MajorShipPilot(
                game=self.game, pawn=self.pawn, personality=personality
            )
            self.navigator = MajorShipNavigator(
                game=self.game,
                pawn=self.pawn,
                personality=personality,
                debug=debug_decisions,
                collision_avoidance=self.pawn.collision_avoidance,
            )
            self.tactician = (
                MajorShipTactician(
                    game=self.game,
                    pawn=self.pawn,
                    personality=personality,
                    debug=debug_decisions,
                )
                if self.pawn.has_tactician
                else None
            )
        else:
            raise NotImplementedError(f"Unknown bot type {self.bot_type}")

        self.team = team
        self.record = kwargs.get("record", False)

        # Think (navigate + pilot) only when the pilot samples its commands, on
        # a frame balanced against the other bots' (see ThinkScheduler). The
        # first frame always thinks.
        self.pilot.sample_externally()
        self._think_slot = self.game.think_scheduler.register(
            period_s=self.pilot.sample_period_s
        )
        self._next_think_s = -math.inf
        self._commands = None

        self.add_task(method=self.move_bot_task)

        # Add the pawn to the interacting actors. A subsystem pawn (e.g. a
        # turret) already registered itself, so skip the duplicate.
        try:
            self.game.interactions.add_actor(self.pawn)
        except ValueError:
            pass

    def move_bot_task(self):
        """
        Find how the bot should move:
        - The tactician picks the intent and target
        - The navigator turns them into a direction to point to (and, for
            ships, a desired speed)
        - The pilot turns that into throttle/rate commands
        - The pawn moves according to the game's physics

        The navigator (ships only) and the pilot run only on think frames; the
        pawn flies the last commands in between.
        """
        # While dying, the AI is silenced and a ship pawn tumbles instead (a
        # mounted subsystem pawn cannot tumble and simply waits out its death).
        if self.is_dying:
            if hasattr(self.pawn, "tumble_step"):
                self.pawn.tumble_step(elapsed_s=self.death_elapsed_s())
            return
        if self.bot_type == "fighter" or self.bot_type == "major_ship":
            if self.tactician is not None:
                intent, target_dict = self.tactician.think()
            else:
                # No tactician (a scripted capital ship): always patrol
                intent, target_dict = Intent.PATROL, {}

            if self._think_is_due():
                target_direction, desired_speed_mps = self.navigator.navigate(
                    intent=intent, target_dict=target_dict
                )
                if RECORD_GAME and self.record:
                    self.record_state(
                        intent=intent,
                        target_dict=target_dict,
                        desired_speed_mps=desired_speed_mps,
                    )
                self._commands = self.pilot.pilot(
                    target_direction=target_direction,
                    desired_speed_mps=desired_speed_mps,
                    up_reference=self.navigator.up_reference,
                    minimum_speed_mps=self.navigator.minimum_speed_mps,
                )
            else:
                self.navigator.update_triggers(intent=intent, target_dict=target_dict)
            self._schedule_sensor()
            throttle, yaw_rate, pitch_rate, roll_rate = self._commands
            self.pawn.move(
                throttle=throttle,
                yaw_rate=yaw_rate,
                pitch_rate=pitch_rate,
                roll_rate=roll_rate,
            )
        elif self.bot_type in ("turret", "tractor_beam"):
            intent, target_dict = self.tactician.think()

            # Navigates every frame: it is cheap, and publishes the firing
            # solution the mount checks every frame. Only the pilot waits.
            target_direction = self.navigator.navigate(
                intent=intent, target_dict=target_dict
            )
            if self._think_is_due():
                self._commands = self.pilot.pilot(target_direction=target_direction)
            yaw_rate, pitch_rate = self._commands
            self.pawn.move(
                yaw_rate=yaw_rate,
                pitch_rate=pitch_rate,
            )
        else:
            raise NotImplementedError(f"Unknown bot type {self.bot_type}")

    def _think_is_due(self) -> bool:
        """
        Whether the bot thinks this frame; if so, schedule its next think.

        A think needs this frame's obstacle contacts: if the collision sensor sat
        out this frame's traversal (the frame came later than expected, see
        _schedule_sensor), turn it on and think on the next frame instead.

        :return: True on the bot's think frames
        """
        now_s = self.game.game_time.get_current_time()
        if now_s < self._next_think_s:
            return False
        sensor = getattr(self.navigator, "collision_sensor", None)
        if sensor is not None and not sensor.active:
            sensor.set_active(True)
            return False
        self._next_think_s = self._think_slot.next_due_time_s(now_s)
        return True

    def _schedule_sensor(self):
        """
        Keep the collision sensor in the collision traversal only for the frame
        the bot next thinks in: it only reads contacts then. The traversal runs
        before the bots update, so decide one frame ahead (assuming the next
        frame lasts as long as this one).
        """
        sensor = getattr(self.navigator, "collision_sensor", None)
        if sensor is None:
            return
        game_time = self.game.game_time
        next_frame_s = game_time.get_current_time() + game_time.get_time_step()
        sensor.set_active(next_frame_s >= self._next_think_s)

    def _release_think_slot(self):
        """Give the bot's think slot back to the scheduler (once)."""
        if self._think_slot is not None:
            self._think_slot.scheduler.unregister(self._think_slot)
            self._think_slot = None

    def record_state(self, intent: Intent, target_dict: dict, desired_speed_mps: float):
        """
        Step-by-step recording of the bot's tactical decision (intent, attack mode,
        target and the resulting kinematics), namespaced by bot name, for post-hoc
        analysis of an engagement.

        :param intent: The tactician's chosen intent
        :param target_dict: The tactician's target info (may hold attack_mode)
        :param desired_speed_mps: The navigator's desired speed
        """
        name = self.name
        record = self.game.record

        record.record(
            f"{name}_intent", intent.name if hasattr(intent, "name") else str(intent)
        )
        attack_mode = target_dict.get("attack_mode")
        record.record(
            f"{name}_attack_mode",
            attack_mode.name if attack_mode is not None else "",
        )

        # Resolve the target's readable name and current distance, when it is a
        # real actor (some intents carry a sentinel target_id instead).
        target_id = target_dict.get("target_id")
        target_name = ""
        distance_to_target_m = float("nan")
        target_speed_mps = float("nan")
        target_mobility = float("nan")
        nan3 = np.full(3, float("nan"))
        target_position_m = nan3
        target_velocity_mps = nan3
        try:
            target_index = self.game.interactions.get_actor_index_from_id(target_id)
            my_index = self.game.interactions.get_actor_index_from_id(self.pawn.id)
            target_actor = self.game.interactions.actors[target_index]
            target_name = getattr(
                target_actor,
                "name",
                getattr(getattr(target_actor, "parent", None), "name", str(target_id)),
            )
            distance_to_target_m = float(
                self.game.interactions.distances[my_index, target_index]
            )
            target_velocity_mps = np.asarray(
                getattr(target_actor, "speed", nan3), dtype=float
            )
            target_speed_mps = float(magnitude(target_velocity_mps))
            target_mobility = float(getattr(target_actor, "mobility", float("nan")))
            target_position_m = np.asarray(
                getattr(target_actor, "position", nan3), dtype=float
            )
        except (ValueError, KeyError, TypeError, AttributeError):
            pass

        record.record(f"{name}_target", str(target_name))
        record.record(f"{name}_distance_to_target_m", distance_to_target_m)
        record.record(f"{name}_target_speed_mps", target_speed_mps)
        record.record(f"{name}_target_mobility", target_mobility)
        record.record(f"{name}_desired_speed_mps", float(desired_speed_mps))
        record.record(f"{name}_speed_mps", float(magnitude(self.pawn.speed)))

        # Full kinematics (like the player's) so a bomb run's geometry -- overfly
        # position, belly aim, lead/cone alignment -- can be reconstructed offline.
        record.record(
            f"{name}_behaviour", str(getattr(self.navigator, "behaviour", ""))
        )
        record.record(f"{name}_position_m", self.pawn.position.copy())
        record.record(f"{name}_orientation_quat", self.pawn.orientation.copy())
        record.record(f"{name}_velocity_mps", self.pawn.speed.copy())
        record.record(f"{name}_target_position_m", target_position_m)
        record.record(f"{name}_target_velocity_mps", target_velocity_mps)

    @property
    def health(self) -> float:
        """
        The bot's health, uniform with the other destructibles: it is its pawn's.
        """
        return self.pawn.health

    @property
    def shield_level(self) -> float:
        """
        The bot's shield strength, uniform with the other destructibles: it is its
        pawn's.
        """
        return self.pawn.shield_level

    def get_health(self) -> float:
        """
        Find the health of the bot

        :return: The health of the bot
        """
        return self.pawn.health

    def set_personality(self, personality: dict):
        """
        Sets a personality to the bot via its tactician, navigator and pilot parameters

        :param personality: A personality dictionary
        """
        if self.tactician is not None:
            self.tactician.personality = personality
        self.navigator.personality = personality
        self.pilot.personality = personality

    def set_team(self, team: int):
        """
        Reassign this bot's team, cascading to everything that caches it.

        A fighter's team is read live every frame, but a capital ship's
        dependents cache it at construction: each sub_system, the shield, and
        each mounted bot (itself a Bot with its own pawn.team).

        :param team: The new team id
        """
        self.team = team
        self.pawn.team = team
        for sub_system in getattr(self.pawn, "sub_systems", []):
            sub_system.team = team
        shield = getattr(self.pawn, "shield", None)
        if shield is not None:
            shield.team = team
        for mounted_bot in getattr(self.pawn, "mounted_bots", []):
            mounted_bot.set_team(team)

    def begin_death(self):
        """
        Enter the bot's dying phase: silence the AI, make the wreck untargetable,
        and (for ships) start its out-of-control tumble.

        The bot stays alive -- integrating and colliding -- for the length of the
        pawn's death spin; :meth:`move_bot_task` then drives the tumble each frame
        and :meth:`finish_death` fires the terminal explosion. A mounted subsystem
        pawn (turret / tractor beam) cannot tumble, so its death is zero-length.
        """
        if self.is_dying:
            return
        super().begin_death()
        # The AI is silenced: the dying bot no longer thinks
        self._release_think_slot()
        sensor = getattr(self.navigator, "collision_sensor", None)
        if sensor is not None:
            sensor.set_active(False)

        # Drop the pawn from targeting/interactions immediately, so nothing can
        # lock onto or keep shooting the wreck while it spins (it stays collidable
        # -- the collider lives until clean()).
        try:
            self.game.player.remove_target(target_to_remove=self.pawn)
        except AttributeError:
            pass
        try:
            self.game.interactions.remove_actor(self.pawn)
        except (KeyError, AttributeError):
            pass

        # Ships tumble; the dying phase lasts their configured spin duration.
        if hasattr(self.pawn, "begin_tumble"):
            self.pawn.begin_tumble()
            self.death_duration_s = self.pawn.death_spin_duration_s

    def play_death(self):
        """
        Procedural explosion at the pawn's last location, after the death spin.

        TODO: pawn-type dependent animation, associated sound
        """
        self.game.fire_smoke_pool.burst(
            position=self.pawn.position,
            scale=self.pawn.explosion_scale,
            base_velocity=self.pawn.speed,
        )

    def clean(self):
        """
        Remove every child
        """
        if DEBUG_DELETION:
            LOGGER.info(f"Cleaning bot {self.name}")
            LOGGER.info(f"Bot tasks {self.tasks}")
        try:
            self.game.player.remove_target(target_to_remove=self.pawn)
        except AttributeError:
            # In level cleanup, player may no longer exist at this point
            pass
        try:
            self.game.interactions.remove_actor(self.pawn)
        except (KeyError, AttributeError):
            # Already removed (a subsystem pawn deregisters itself), or
            # game.interactions is gone during level cleanup
            pass
        self._release_think_slot()
        self.pilot.clean()
        self.pilot = None
        self.navigator.clean()
        self.navigator = None
        if self.tactician is not None:
            self.tactician.clean()
        self.tactician = None
        self.pawn.clean()
        self.pawn = None
        if DEBUG_DELETION:
            LOGGER.info(f"Cleaned bot {self.name}")
            LOGGER.info(f"Bot tasks {self.tasks}")
            LOGGER.info(f"Bot nref = {sys.getrefcount(self)}")
            LOGGER.info(f"Bot references {gc.get_referrers(self)}")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info(f"Deleted bot {self.name}")


def spawn_bot(
    game: FlightState,
    name: str,
    bot_type: str,
    pawn_model: str,
    team: int = 0,
    debug_decisions: bool = False,
    **kwargs: Any,
) -> Bot:
    # TODO useless function, just use the constructor directly ?
    bot = Bot(
        game=game,
        name=name,
        bot_type=bot_type,
        pawn_model=pawn_model,
        team=team,
        debug_decisions=debug_decisions,
        **kwargs,
    )

    return bot
