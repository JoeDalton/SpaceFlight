"""
Mission 1: Rookies -- a tutorial mission that replaces the old Race level.

Teaches the radial target-filter menu (select "Waypoints", then "Fighters",
cycling targets within a filter with "loop"), then a follow-the-leader escort
sequence with two distinct fail conditions, ending in an impromptu race
against the very ships the player was just escorting. More steps are
expected to be appended later -- keep the mission body easy to extend.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterator

import numpy as np

from space_flight.actors.player import Player
from space_flight.game.scenario import Scenario
from space_flight.game.scenario.conditions import (
    Not,
    Sustained,
    after_seconds,
    near,
    near_actor,
    reached_waypoint,
)
from space_flight.game.scenario.loader import load_waves
from space_flight.game.scenario.mission import Mission
from space_flight.scenes.scenes import scene_factory

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

# --- tunable numbers -------------------------------------------------------
# All illustrative placeholders, sized to fit comfortably inside the
# "asteroids" scene's field (field_size=15000) -- easy to retune after a
# playtest.
PLAYER_SPAWN_POINT = [0, -3000, 500]
WAYPOINT_1 = [0, 0, 500]
WAYPOINT_1_ARRIVAL_RADIUS_M = 350

FORMATION_AHEAD_M = 1000  # "1km ahead"
FORMATION_LEFT_M = 400  # "and to the left"
FOLLOW_RADIUS_M = 200  # "within 200m of the formation leader"
CATCH_UP_DEADLINE_S = 30
SUSTAINED_SEPARATION_S = 10

# The escort's patrol circuit (baked into its own wave cfg below), a rough
# loop starting near WAYPOINT_1 and closing back on itself (loop: true).
CIRCUIT_WAYPOINTS = [
    [-800, 1200, 550],
    [800, 2500, 650],
    [1500, 4500, 500],
    [-500, 5500, 600],
    [-2000, 3000, 550],
]

# The 5 new waypoints given to the player AND every former formation member
# once the circuit is done, per issue's step 5. The last one is the finish.
RACE_WAYPOINTS = [
    [-3000, 6000, 600],
    [-1000, 8000, 700],
    [1500, 8500, 500],
    [3000, 6500, 600],
    [2500, 4000, 500],
]
FINISH_RADIUS_M = 300


def build_mission1_upfront(game: FlightState) -> None:
    """
    Build the heavy, up-front part of the level — run synchronously on a black
    screen BEFORE the hyperspace animation starts.

    :param game: The game/flight state
    """
    game.player = Player(
        game=game,
        ship_type="x-wing",
        ini_position=np.array(PLAYER_SPAWN_POINT),
        is_neutral=False,
        has_ai=False,
    )
    game.scene = scene_factory(game=game, scene_name="asteroids")
    game.scene.build_upfront()


def _key_label(game: FlightState, context: str, action: str, fallback: str) -> str:
    """
    Human-readable keybinding label for a bound action, e.g. "R" for the
    keyboard's radial_menu binding.

    Mirrors flight_state.py's _jump_prompt, so a HUD prompt stays correct
    even if the player rebinds the key, instead of hardcoding a key name.

    :param game: The game/flight state
    :param context: The bindings context the action lives under (e.g. "flight")
    :param action: The action name within that context (e.g. "radial_menu")
    :param fallback: Shown instead if the action has no binding
    :return: The uppercased key label, or fallback
    """
    input_type = game.app.bindings.get("input_type", "keyboard")
    key = (
        game.app.bindings.get("contexts", {})
        .get(context, {})
        .get(input_type, {})
        .get(action, "")
    )
    return key.upper() if key else fallback


def mission1_mission(m: Mission) -> Iterator[None]:
    """
    Mission 1: Rookies' mission body.

    :param m: The level's :class:`Mission`
    """
    game = m.game

    # ==================================================================
    # 1. A single waypoint, teaching the Waypoints filter + loop.
    # ==================================================================
    radial_key = _key_label(game, "flight", "radial_menu", "the target-menu key")
    loop_key = _key_label(game, "flight", "loop_target", "the cycle-target key")

    m.player_waypoints(
        {"points": [WAYPOINT_1], "arrival_radius_m": WAYPOINT_1_ARRIVAL_RADIUS_M}
    )
    m.hud(
        f"Hold [{radial_key}] to open the target menu, point at Waypoints, "
        f"then press [{loop_key}] to lock onto it."
    )

    # The waypoint marker auto-detects arrival internally (see
    # PlayerWaypoints), but exposes no public "just reached" event -- poll
    # the same radius with the ordinary near() condition instead of reaching
    # into its private state.
    yield from m.wait_until(near("player", WAYPOINT_1, WAYPOINT_1_ARRIVAL_RADIUS_M))
    game.player_waypoints.clean()

    # ==================================================================
    # 2. Spawn the formation 1km ahead and to the left, teach Fighters + loop.
    # ==================================================================
    player_pawn = game.player.pawn
    spawn_point = (
        player_pawn.position
        + player_pawn.forward * FORMATION_AHEAD_M
        - player_pawn.right * FORMATION_LEFT_M
    )
    escort_cfg = dict(m.waves["escort"])
    escort_cfg["spawn_point"] = spawn_point.tolist()
    escort = m.spawn(escort_cfg)

    m.hud(
        f"Formation inbound! Hold [{radial_key}], point at Fighters, then "
        f"press [{loop_key}] to lock onto the formation leader."
    )

    # ==================================================================
    # 3. Follow the leader: a catch-up deadline, then a sustained-separation
    #    fail condition for the rest of the circuit.
    # ==================================================================
    yield from m.wait_until(escort.alive_cond())
    leader_bot = m.scenario.resolve(game, escort.name)[0].parent
    m.scenario.register("escort_leader", [leader_bot])

    m.speech("On me, rookie. Try to keep up!", speaker="Blue Leader")

    deadline = game.game_time.get_current_time() + CATCH_UP_DEADLINE_S
    yield from m.wait_any(
        near_actor("player", "escort_leader", FOLLOW_RADIUS_M),
        after_seconds(deadline),
    )
    if not near_actor("player", "escort_leader", FOLLOW_RADIUS_M)(game):
        m.defeat("You failed to catch up with the formation in time. Mission failed.")
        return

    # Registered only now, so the initial catch-up isn't double-punished by
    # the same 200m radius.
    lost_contact = m.on(
        Sustained(
            Not(near_actor("player", "escort_leader", FOLLOW_RADIUS_M)),
            SUSTAINED_SEPARATION_S,
        ),
        lambda game: m.defeat(
            "You fell too far behind the formation for too long. Mission failed."
        ),
        name="lost_contact",
    )

    # ==================================================================
    # 4. The leader's circuit, then the handoff to a race.
    # ==================================================================
    yield from m.wait_until(
        reached_waypoint("escort_leader", len(CIRCUIT_WAYPOINTS) - 1)
    )
    if lost_contact in m.scenario.triggers:
        m.scenario.triggers.remove(lost_contact)

    m.speech(
        "Not bad! Race you to the marker -- follow the new waypoints!",
        speaker="Blue Leader",
    )
    m.player_waypoints(RACE_WAYPOINTS)
    escort.set_waypoints(RACE_WAYPOINTS, loop=False)

    # ==================================================================
    # 5. Ranking: the player must not finish last, with a special line for
    #    finishing first.
    # ==================================================================
    finish_point = RACE_WAYPOINTS[-1]
    escort_pawns = m.scenario.resolve(game, escort.name)
    racer_names = ["player"]
    for i, pawn in enumerate(escort_pawns):
        name = f"racer_{i}"
        m.scenario.register(name, [pawn.parent])
        racer_names.append(name)
    total_racers = len(racer_names)

    finish_order: list[str] = []

    def record_finish(name: str):
        def action(game):
            if name not in finish_order:
                finish_order.append(name)

        return action

    for name in racer_names:
        m.on(
            near(name, finish_point, FINISH_RADIUS_M),
            record_finish(name),
            name=f"finish_{name}",
        )

    yield from m.wait_until(lambda game: len(finish_order) == total_racers)

    if finish_order[-1] == "player":
        m.defeat("You crossed the line last. Mission failed.")
    elif finish_order[0] == "player":
        m.victory("First across the line! Outstanding flying, rookie!")
    else:
        m.victory("You made it across without embarrassing yourself. Mission complete.")


def build_mission1_level(game: FlightState) -> Iterator[str]:
    """
    Build Mission 1: Rookies.

    :param game: The game/flight state
    """
    yield from game.scene.build_decomposed()

    game.scenario = Scenario()
    mission = Mission(game)
    mission.waves = load_waves(Path(__file__).with_suffix(".yaml"))
    game.scenario.schedule(mission1_mission(mission))
    yield "scenario"
