"""
Mission 1: Rookies -- a tutorial mission.

Teaches the radial target-filter menu (select "Waypoints", then "Fighters",
cycling targets within a filter with "loop"), then an escort-formation
sequence (stay close to any member of the formation, not just its leader)
with two distinct fail conditions, ending in an impromptu race against the
very ships the player was just escorting.
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

# The race route, given to the player AND every formation member once the
# circuit is done. The last waypoint is the finish.
RACE_WAYPOINTS = [
    [-3000, 8000, 1500],
    [-1000, 8000, 700],
    [1500, 8500, 500],
    [3000, 6500, 600],
    [2500, 4000, 500],
]
FINISH_RADIUS_M = 300
RACE_TIMEOUT_S = 300  # defeat if the player hasn't finished by then
RACE_NAG_S = RACE_TIMEOUT_S - 60  # "where are you?" before the timeout
WAYPOINT_NAG_S = 45  # "any time today" if the first waypoint takes this long

# The player flies as Blue Five; the formation is named in spawn order.
BLUE_NAMES = ["Blue Leader", "Blue Two", "Blue Three", "Blue Four"]

# (delay after the previous line, speaker, line) while following the circuit.
CIRCUIT_CHATTER = [
    (8, "Blue Three", "Big rock, two o'clock. Mind your paint, Five."),
    (12, "Blue Four", "So, rookie, is it true you washed out of the simulator twice?"),
    (4, "Blue Two", "Twice? I heard it was three times."),
    (4, "Blue Leader", "That's enough, you two. Five's doing fine."),
    (12, "Blue Three", "Almost around. Lead, you thinking what I'm thinking?"),
    (4, "Blue Leader", "Always, Three."),
]

# The line of whichever wingman crosses the finish line first, if not the player.
WINNER_LINES = {
    "Blue Leader": "And that, rookie, is why they call me Lead.",
    "Blue Two": "Ha! Nobody beats Blue Two!",
    "Blue Three": "Three, first across. Write that down, Four.",
    "Blue Four": "Did you see that? Four, first! Four!",
}


def build_mission1_upfront(game: FlightState):
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
        game.app, "flight", "radial_menu", "the target-menu key"
    )
    loop_key = InputContext.key_label(
        game.app, "flight", "loop_target", "the cycle-target key"
    )

    m.player_waypoints([WAYPOINT_1], arrival_radius_m=WAYPOINT_1_ARRIVAL_RADIUS_M)
    yield from m.wait(0.5)
    m.speech(
        "Morning, rookie. Blue squadron's running drills out past the rocks.\n"
        "First, show me you can find a nav point.",
        speaker="Blue Leader",
    )
    dawdling = m.on(
        m.after(WAYPOINT_NAG_S),
        lambda: m.speech(
            "Any time today, rookie. The rocks aren't going anywhere.",
            speaker="Blue Leader",
        ),
    )
    yield from m.wait(2.5)
    m.hud(
        f"Hold [{radial_key}] to open the target menu,\n"
        f"point at Waypoints, then press [{loop_key}]\n"
        "to lock onto your next waypoint."
    )

    # The waypoint marker detects arrival itself but exposes no event for
    # it, so poll the same radius.
    yield from m.wait_until(near(game.player, WAYPOINT_1, WAYPOINT_1_ARRIVAL_RADIUS_M))
    dawdling.cancel()
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

    # ==================================================================
    # 3. Follow the formation: a catch-up deadline, then a sustained-
    #    separation fail condition for the rest of the circuit. "Close
    #    enough" means close to ANY live member of the formation.
    # ==================================================================
    yield from m.wait_until(blue.alive)
    # Spawned first, so the formation leader; its own progress (not the
    # formation's) marks the end of the circuit in step 4.
    leader = blue.pawns()[0]

    close_to_blue = near_actor(game.player, blue, FOLLOW_RADIUS_M)
    race_started = []

    # The formation's chatter runs alongside the body, so catching up or
    # finishing the circuit early is not held back by it.
    def formation_chatter() -> Iterator[None]:
        m.speech(
            "There you are. Welcome to Blue squadron, you're Blue Five today.\n"
            "Form up on us.",
            speaker="Blue Leader",
        )
        yield from m.wait(5)
        m.speech(
            "A rookie? Lead, you promised no babysitting this week.",
            speaker="Blue Two",
        )
        yield from m.wait(4)
        m.speech(
            "Cut the chatter, Two. Five, stay close to any of us and keep up.",
            speaker="Blue Leader",
        )
        m.hud(f"Stay within {FOLLOW_RADIUS_M}m of any Blue squadron ship.")
        yield from m.wait_until(close_to_blue)
        yield from m.wait(4)
        m.speech("Good, you're with us. Now hold it there.", speaker="Blue Leader")
        for delay, speaker, line in CIRCUIT_CHATTER:
            yield from m.wait(delay)
            if race_started:
                return
            m.speech(line, speaker=speaker)

    m.schedule(formation_chatter())

    caught_up = yield from m.wait_until(close_to_blue, timeout=CATCH_UP_DEADLINE_S)
    if not caught_up:
        m.defeat("You failed to catch up with the formation in time. Mission failed.")
        return

    # Registered only now, so the initial catch-up isn't double-punished by
    # the same radius.
    losing_contact = m.on(
        m.sustained(not_(close_to_blue), SUSTAINED_SEPARATION_S / 2),
        lambda: m.speech(
            "Come on, rookie, you're falling behind! Catch up!", speaker="Blue Leader"
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
    race_started.append(True)

    m.speech(
        "Not bad, Five! Now let's see what you've really got.\n"
        "Race you to the marker! Follow the new waypoints.",
        speaker="Blue Leader",
    )
    m.player_waypoints(RACE_WAYPOINTS)
    # Every man for himself: wingmen would otherwise hold formation.
    blue.break_formation()
    blue.set_waypoints(RACE_WAYPOINTS, loop=False)

    def race_chatter() -> Iterator[None]:
        yield from m.wait(4)
        m.speech("Loser buys the first round!", speaker="Blue Two")
        yield from m.wait(4)
        m.speech("Eat my ion trail, rookie!", speaker="Blue Four")

    m.schedule(race_chatter())
    m.on(
        m.after(RACE_NAG_S),
        lambda: m.speech(
            "Five, we're already at the bar. Where are you?", speaker="Blue Two"
        ),
    )

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

    def wingman_won():
        name = BLUE_NAMES[racers.index(finish_order[0]) - 1]
        m.speech(WINNER_LINES[name], speaker=name)

    m.on(
        lambda: bool(finish_order) and finish_order[0] is not game.player,
        wingman_won,
    )

    player_finished = yield from m.wait_until(
        lambda: game.player in finish_order, timeout=RACE_TIMEOUT_S
    )
    if not player_finished:
        m.defeat("You didn't reach the finish line in time. Mission failed.")
    elif finish_order[0] is game.player:
        m.victory("First across the line! Outstanding flying, rookie!")
    elif len(finish_order) == len(racers):
        m.victory(
            "Dead last, but in one piece. Mission complete.\n"
            "Blue Two says you're buying the first round."
        )
    else:
        m.victory("You made it across without embarrassing yourself. Mission complete.")
