"""
Mission 1: Rookies -- a tutorial mission that replaces the old Race level.

Teaches the radial target-filter menu (select "Waypoints", then "Fighters",
cycling targets within a filter with "loop"), then an escort-formation
sequence (stay close to any member of the formation, not just its leader)
with two distinct fail conditions, ending in an impromptu race against the
very ships the player was just escorting. More steps are expected to be
appended later -- keep the mission body easy to extend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator

import numpy as np

from space_flight.actors.player import Player
from space_flight.game.scenario import WaveSpec
from space_flight.game.scenario.conditions import (
    near,
    near_actor,
    not_,
    reached_waypoint,
)
from space_flight.scenes.scenes import scene_factory
from space_flight.ui.input_context import InputContext

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState
    from space_flight.game.scenario import Mission

# --- tunable numbers -------------------------------------------------------
# All illustrative placeholders, sized to fit comfortably inside the
# "asteroids" scene's field (field_size=15000) -- easy to retune after a
# playtest.
PLAYER_SPAWN_POINT = [0, -3000, 500]
WAYPOINT_1 = [0, 0, 500]
WAYPOINT_1_ARRIVAL_RADIUS_M = 350

FORMATION_AHEAD_M = 1000  # "1km ahead"
FORMATION_LEFT_M = 400  # "and to the left"
FOLLOW_RADIUS_M = 300  # "within 300m of any member of the formation"
CATCH_UP_DEADLINE_S = 60
SUSTAINED_SEPARATION_S = 30

# Blue squadron's patrol circuit, a rough loop starting near WAYPOINT_1 and
# closing back on itself.
CIRCUIT_WAYPOINTS = [
    [-800, 1200, 550],
    [800, 2500, 650],
    [1500, 4500, 500],
    [-500, 5500, 600],
    [-2000, 3000, 550],
]

# The leader + 3 wingmen the player follows, then races. Their spawn point
# depends on the player's position when WAYPOINT_1 is reached, so it is given
# at spawn time.
BLUE_SQUADRON = WaveSpec(
    name="blue",
    ship_model="x-wing",
    size=4,
    team=1,
    formation="arrowhead",
    waypoints=CIRCUIT_WAYPOINTS,
    loop=True,
)

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
RACE_TIMEOUT_S = 300  # defeat if the player hasn't finished by then


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


def mission1_mission(m: Mission) -> Iterator[None]:
    """
    Mission 1: Rookies' mission body.

    :param m: The level's :class:`Mission`
    """
    game = m.game

    # ==================================================================
    # 1. A single waypoint, teaching the Waypoints filter + loop.
    # ==================================================================
    radial_key = InputContext.key_label(
        game.app.bindings, "flight", "radial_menu", "the target-menu key"
    )
    loop_key = InputContext.key_label(
        game.app.bindings, "flight", "loop_target", "the cycle-target key"
    )

    m.player_waypoints([WAYPOINT_1], arrival_radius_m=WAYPOINT_1_ARRIVAL_RADIUS_M)
    yield from m.wait(3)
    m.hud(
        f"Hold [{radial_key}] to open the target menu,\n"
        f"point at Waypoints, then press [{loop_key}]\n"
        "to lock onto your next waypoint."
    )

    # The waypoint marker detects arrival itself but exposes no event for
    # it, so poll the same radius.
    yield from m.wait_until(near(game.player, WAYPOINT_1, WAYPOINT_1_ARRIVAL_RADIUS_M))
    m.clear_player_waypoints()

    # ==================================================================
    # 2. Spawn the formation 1km ahead and to the left, teach Fighters + loop.
    # ==================================================================
    player_pawn = game.player.pawn
    spawn_point = (
        player_pawn.position
        + player_pawn.forward * FORMATION_AHEAD_M
        - player_pawn.right * FORMATION_LEFT_M
    )
    blue = m.spawn(BLUE_SQUADRON, spawn_point=spawn_point)

    m.hud(
        f"Allied formation inbound! Hold [{radial_key}],\n"
        f"point at Fighters, then press [{loop_key}]\n"
        "to lock onto the formation leader."
    )
    yield from m.wait(1)
    m.speech("Follow me, rookie!", speaker="Blue Leader")

    # ==================================================================
    # 3. Follow the formation: a catch-up deadline, then a sustained-
    #    separation fail condition for the rest of the circuit. "Close
    #    enough" means close to ANY live member of the formation.
    # ==================================================================
    yield from m.wait_until(blue.alive)
    # Spawned first, so the formation leader; its own progress (not the
    # formation's) marks the end of the circuit in step 4.
    leader = blue.pawns()[0]

    m.speech("On me, rookie. Try to keep up!", speaker="Blue Leader")

    close_to_blue = near_actor(game.player, blue, FOLLOW_RADIUS_M)
    caught_up = yield from m.wait_until(close_to_blue, timeout=CATCH_UP_DEADLINE_S)
    if not caught_up:
        m.defeat("You failed to catch up with the formation in time. Mission failed.")
        return

    # Registered only now, so the initial catch-up isn't double-punished by
    # the same radius.
    losing_contact = m.on(
        m.sustained(not_(close_to_blue), SUSTAINED_SEPARATION_S / 2),
        lambda: m.speech(
            "Come on Rookie, you're falling behind! Catch up!.", speaker="Blue Leader"
        ),
    )
    lost_contact = m.on(
        m.sustained(not_(close_to_blue), SUSTAINED_SEPARATION_S),
        lambda: m.defeat(
            "You fell too far behind the formation for too long. Mission failed."
        ),
    )

    # ==================================================================
    # 4. The leader's circuit, then the handoff to a race.
    # ==================================================================
    yield from m.wait_until(reached_waypoint(leader, len(CIRCUIT_WAYPOINTS) - 1))
    losing_contact.cancel()
    lost_contact.cancel()

    m.speech(
        "Not bad! Race you to the marker! Follow the new waypoints.",
        speaker="Blue Leader",
    )
    m.player_waypoints(RACE_WAYPOINTS)
    blue.set_waypoints(RACE_WAYPOINTS, loop=False)

    # ==================================================================
    # 5. Ranking: ends the instant the player crosses the line, ranked by
    #    whoever has already finished by then (no waiting for stragglers) --
    #    a special line for finishing first -- or in defeat if the player
    #    never finishes within the timeout.
    # ==================================================================
    finish_point = RACE_WAYPOINTS[-1]
    racers = [game.player, *blue.pawns()]
    finish_order: list = []
    for racer in racers:
        m.on(
            near(racer, finish_point, FINISH_RADIUS_M),
            lambda racer=racer: finish_order.append(racer),
        )

    player_finished = yield from m.wait_until(
        lambda: game.player in finish_order, timeout=RACE_TIMEOUT_S
    )
    if not player_finished:
        m.defeat("You didn't reach the finish line in time. Mission failed.")
    elif finish_order[0] is game.player:
        m.victory("First across the line! Outstanding flying, rookie!")
    else:
        m.victory("You made it across without embarrassing yourself. Mission complete.")
