"""
Mission 1: Rookies -- a tutorial mission.

Teaches the radial target-filter menu (select "Waypoints", then "Fighters",
cycling targets within a filter with "loop"), then an escort-formation
sequence (stay close to any member of the formation, not just its leader)
with two distinct fail conditions, ending in an impromptu race against the
very ships the player was just escorting.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Callable, Iterator

from space_flight.game.levels.common import (
    FRIENDLY_FIRE_GRACE_S,
    build_upfront,
    police_fire,
    relative_position,
)
from space_flight.game.levels.hints import (
    engine_power_hint,
    formation_hint,
    stay_close_hint,
    waypoint_hint,
)
from space_flight.game.scenario import WaveSpec
from space_flight.game.scenario.conditions import (
    near,
    near_actor,
    not_,
    reached_waypoint,
)
from space_flight.weapons import ION
from space_flight.weapons.loadout import default_loadout

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState
    from space_flight.game.scenario import Mission

# --- tunable numbers -------------------------------------------------------
# All illustrative placeholders, sized for the "asteroids" scene's field
# (field_size=15000, so +/-7500m around the origin); the race's first
# waypoints lie just beyond its far edge -- easy to retune after a playtest.
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

ION_LOADOUT = replace(default_loadout("x-wing"), lasers=ION).with_ordnance(
    concussion_missile=0,
    ion_missile=0,
    rocket=0,
    proton_bomb=0,
    ion_torpedo=0,
    proton_torpedo=0,
    ion_bomb=0,
)

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
    loadouts={"x-wing": ION_LOADOUT},
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
# How close the player passes a race waypoint (the route's arrival radius)
RACE_GATE_RADIUS_M = 350
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

# (delay after the previous line, speaker, line) through the race.
RACE_CHATTER = [
    (4, "Blue Two", "Loser buys the first round!"),
    (4, "Blue Four", "Eat my ion trail, rookie!"),
    (6, "Blue Three", "Hey, no cutting through the rocks, Four!"),
    (5, "Blue Four", "Rocks are fair game, Three. Read the rulebook."),
    (8, "Blue Leader", "Push it, Five. Every bit of power to those engines."),
    (10, "Blue Two", "My astromech says I'm already winning."),
    (5, "Blue Three", "Your astromech's been lying to you since flight school, Two."),
    (12, "Blue Leader", "Tight turn coming up. Nobody scratch my paint."),
]


# Lines of the rules of engagement, one group per hit on a teammate; a speaker
# given as a function is picked from the pawn that was shot.
PRE_RACE_WARNINGS = [
    [("Blue Leader", "Five, watch your fire! That's your own squadron!")],
    [
        (
            "Blue Leader",
            "Five, I'm warning you once more. Seriously, back off, or I'll ground you!",
        )
    ],
    [("Blue Leader", "That's it, Five. You're grounded!")],
]
PRE_RACE_GROUNDED = "You kept firing on your own squadron.\nYour wings are grounded."


def cheating_lines(victim_name: Callable, other_name: Callable) -> list:
    """
    The rules of engagement lines once the race is on: accusations of cheating
    from the ship shot and another teammate, then the leader.

    :param victim_name: Speaker: the ship shot
    :param other_name: Speaker: a teammate other than the leader and the ship shot
    :return: One group of (speaker, line) per hit
    """
    return [
        [
            (victim_name, "Hey! Did Five just shoot me?"),
            (other_name, "Looks like the rookie can't win without cheating."),
        ],
        [
            (victim_name, "Shooting your own squad? Seriously, Five?"),
            (
                other_name,
                "Good thing these lasers are ion shots. "
                "The kid's ready to do anything to win.",
            ),
        ],
        [("Blue Leader", "Five, that's enough. Seriously, back off!")],
        [("Blue Leader", "Race over, Five. You're grounded!")],
    ]


RACE_GROUNDED = (
    "You cheated in the race by firing on your own squadron.\nYour wings are grounded."
)

# Race waypoint index -> the line if the player gets there first, and the
# one if a wingman does (spoken by that wingman when its speaker is None).
RACE_GATE_LINES = {
    1: (
        ("Blue Two", "What?! Where did the rookie learn to fly like that?"),
        (None, "Keep up, Five! You're eating my exhaust!"),
    ),
    3: (
        ("Blue Four", "Five's out in front! Somebody catch that kid!"),
        (None, "Last stretch! Nobody's catching me now!"),
    ),
}

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
    build_upfront(
        game,
        scene_name="asteroids",
        player_ship_type="x-wing",
        player_position=PLAYER_SPAWN_POINT,
        player_loadout=ION_LOADOUT,
    )


def mission1_mission(m: Mission) -> Iterator[None]:
    """
    Mission 1: Rookies' mission body.

    :param m: The level's :class:`Mission`
    """
    game = m.game

    # ==================================================================
    # 1. A single waypoint, teaching the Waypoints filter + loop.
    # ==================================================================
    m.player_waypoints([WAYPOINT_1], arrival_radius_m=WAYPOINT_1_ARRIVAL_RADIUS_M)
    nav_point = m.objective("Reach the nav point")
    yield from m.wait(0.5)
    m.speech(
        "Morning, rookie. Blue squadron's running drills out past the rocks.\n"
        "First, show me you can find a nav point.",
        speaker="Blue Leader",
    )
    dawdling = m.say_when(
        m.after(WAYPOINT_NAG_S),
        "Any time today, rookie. The rocks aren't going anywhere.",
        speaker="Blue Leader",
    )
    yield from m.wait(2.5)
    m.hint(waypoint_hint(game.app))

    # The waypoint marker detects arrival itself but exposes no event for
    # it, so poll the same radius.
    yield from m.wait_until(near(game.player, WAYPOINT_1, WAYPOINT_1_ARRIVAL_RADIUS_M))
    nav_point.complete()
    dawdling.cancel()
    m.clear_player_waypoints()

    # ==================================================================
    # 2. Spawn the formation 1km ahead and to the left, teach Fighters + loop.
    # ==================================================================
    spawn_point = relative_position(
        game.player.pawn, right_m=-FORMATION_LEFT_M, forward_m=FORMATION_AHEAD_M
    )
    blue = m.spawn(BLUE_SQUADRON, spawn_point=spawn_point)
    form_up = m.objective("Form up with Blue squadron")

    m.hint(formation_hint(game.app))

    # ==================================================================
    # 3. Follow the formation: a catch-up deadline, then a sustained-
    #    separation fail condition for the rest of the circuit. "Close
    #    enough" means close to ANY live member of the formation.
    # ==================================================================
    yield from m.wait_until(blue.alive)
    # Spawned first, so the formation leader; its own progress (not the
    # formation's) marks the end of the circuit in step 4.
    leader = blue.pawns()[0]

    def victim_name(victim) -> str:
        # Named in spawn order, dead or alive
        return BLUE_NAMES[blue.ids.index(victim.id)]

    def other_name(victim) -> str:
        """A live teammate other than the leader and the ship shot."""
        others = [
            victim_name(p) for p in blue.pawns() if p is not leader and p is not victim
        ]
        return others[0] if others else victim_name(victim)

    # Hits on teammates: a warning, then grounded
    pre_race_police = police_fire(
        m,
        blue,
        PRE_RACE_WARNINGS,
        lambda: m.defeat(PRE_RACE_GROUNDED),
        grace_s=FRIENDLY_FIRE_GRACE_S,
    )

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
        m.hint(stay_close_hint(FOLLOW_RADIUS_M, "Blue squadron"))
        yield from m.wait_until(close_to_blue)
        yield from m.wait(4)
        m.speech("Good, you're with us. Now hold it there.", speaker="Blue Leader")
        yield from m.dialogue(CIRCUIT_CHATTER, stop=lambda: bool(race_started))

    m.schedule(formation_chatter())

    caught_up = yield from m.wait_until(close_to_blue, timeout=CATCH_UP_DEADLINE_S)
    if not caught_up:
        form_up.fail()
        m.defeat("You failed to catch up with the formation in time. Mission failed.")
        return
    form_up.complete()
    circuit = m.objective("Fly the circuit with Blue squadron")

    # Registered only now, so the initial catch-up isn't double-punished by
    # the same radius.
    losing_contact = m.say_when(
        m.sustained(not_(close_to_blue), SUSTAINED_SEPARATION_S / 2),
        "Come on, rookie, you're falling behind! Catch up!",
        speaker="Blue Leader",
    )

    def on_lost_contact():
        circuit.fail()
        m.defeat("You fell too far behind the formation for too long. Mission failed.")

    lost_contact = m.on(
        m.sustained(not_(close_to_blue), SUSTAINED_SEPARATION_S), on_lost_contact
    )

    # ==================================================================
    # 4. The leader's circuit, then the handoff to a race.
    # ==================================================================
    yield from m.wait_until(reached_waypoint(leader, len(CIRCUIT_WAYPOINTS) - 1))
    losing_contact.cancel()
    lost_contact.cancel()
    circuit.complete()
    race_started.append(True)
    # The hit count starts again, with the teammates now accusing the player
    pre_race_police.cancel()
    police_fire(
        m,
        blue,
        cheating_lines(victim_name, other_name),
        lambda: m.defeat(RACE_GROUNDED),
        grace_s=FRIENDLY_FIRE_GRACE_S,
    )

    m.speech(
        "Not bad, Five! Now let's see what you've really got.\n"
        "Race you to the marker! Follow the new waypoints.",
        speaker="Blue Leader",
    )
    m.player_waypoints(RACE_WAYPOINTS)
    race = m.objective("Race to the finish marker")
    m.hint(engine_power_hint(game.app))
    # Every man for himself: wingmen would otherwise hold formation.
    blue.break_formation()
    blue.set_waypoints(RACE_WAYPOINTS, loop=False)
    wingmen = blue.pawns()
    finish_order: list = []

    m.schedule(m.dialogue(RACE_CHATTER, stop=lambda: bool(finish_order)))

    def comment_on_the_lead(index: int, player_line: tuple, wingman_line: tuple):
        """Comment on whoever reaches race waypoint index first."""
        # The player (None) or a wingman's name, in order of arrival
        arrivals: list = []
        m.on(
            near(game.player, RACE_WAYPOINTS[index], RACE_GATE_RADIUS_M),
            lambda: arrivals.append(None),
        )
        for pawn, name in zip(wingmen, BLUE_NAMES):
            m.on(reached_waypoint(pawn, index), lambda name=name: arrivals.append(name))

        def comment():
            if arrivals[0] is None:
                speaker, line = player_line
            else:
                speaker, line = wingman_line[0] or arrivals[0], wingman_line[1]
            m.speech(line, speaker=speaker)

        m.on(lambda: bool(arrivals), comment)

    for index, (player_line, wingman_line) in RACE_GATE_LINES.items():
        comment_on_the_lead(index, player_line, wingman_line)

    m.say_when(
        m.after(RACE_NAG_S),
        "Five, we're already at the bar. Where are you?",
        speaker="Blue Two",
    )

    # ==================================================================
    # 5. Ranking: ends the instant the player crosses the line, ranked by
    #    whoever has already finished by then (no waiting for stragglers) --
    #    a special line for finishing first -- or in defeat if the player
    #    never finishes within the timeout.
    # ==================================================================
    finish_point = RACE_WAYPOINTS[-1]
    racers = [game.player, *wingmen]
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
    m.objective(
        "Bonus: cross the line first",
        done=lambda: bool(finish_order) and finish_order[0] is game.player,
        failed=lambda: bool(finish_order) and finish_order[0] is not game.player,
    )

    player_finished = yield from m.wait_until(
        lambda: game.player in finish_order, timeout=RACE_TIMEOUT_S
    )
    if not player_finished:
        race.fail()
        m.defeat("You didn't reach the finish line in time. Mission failed.")
        return
    race.complete()
    if finish_order[0] is game.player:
        m.victory("First across the line! Outstanding flying, rookie!")
    elif len(finish_order) == len(racers):
        m.victory(
            "Dead last, but in one piece. Mission complete.\n"
            "Blue Two says you're buying the first round."
        )
    else:
        m.victory("You made it across without embarrassing yourself. Mission complete.")
