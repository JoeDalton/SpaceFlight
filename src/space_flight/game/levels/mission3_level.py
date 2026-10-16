"""
Mission 3: Escort -- escort a convoy of transports past an
enemy blockade.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

from space_flight.game.levels.common import build_upfront
from space_flight.game.scenario import WaveSpec
from space_flight.game.scenario.conditions import (
    all_of,
    any_of,
    damaged,
    reached_waypoint,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from space_flight.game.flight_state import FlightState
    from space_flight.game.scenario import Mission, WaveHandle

# Orientations are quaternions (w, x, y, z).
# The escort's call signs, in spawn order (the player flies as Red Seven).
RED_NAMES = [
    "Red Leader",
    "Red Two",
    "Red Three",
    "Red Four",
    "Red Five",
    "Red Six",
    "Red Eight",
    "Red Nine",
]

# Said by the escort as it loses its pilots, one line per loss in order (the
# last one repeats); {name} is the pilot lost.
ESCORT_LOSS_LINES = [
    "{name} is down! Close up the gaps, Red squadron.",
    "We lost {name}! They're picking us off one by one!",
    "{name}'s gone... Stay with your wingman, everyone.",
    "{name}, no! Half the squadron's gone. Hold the line!",
    "Another one... {name} is gone. Seven, we need you!",
]

# What is said as a wave is cleared, by what is left of its kind: more of
# them still flying, more to come (a wave not spawned yet), or the last.
BOMBER_CLEAR_LINES = {
    "more_flying": (
        "Red Leader",
        "One bomber group down, but more are still going for the convoy!",
    ),
    "more_to_come": (
        "Red Leader",
        "That's the last of the first wave. Nice shooting, Red squadron.",
    ),
    "last": ("Red Leader", "Bombers cleared! Convoy, you're free to run."),
}
FIGHTER_CLEAR_LINES = {
    "more_flying": (
        "Red Three",
        "Scratch one TIE-Fighter flight, but there's another still on us!",
    ),
    "more_to_come": ("Red Three", "TIE-Fighters are down! They're off our backs."),
    "last": ("Red Two", "Last of those TIE-Fighters is down. Our six is clear!"),
}

# After every enemy wave is down: the closing chatter, then the victory.
ALL_CLEAR_VICTORY_DELAY_S = 7

FACING_NORTH = [1, 0, 0, 0]
FACING_SOUTH = [0, 0, 0, 1]

TRANSPORTS = WaveSpec(
    name="transports",
    ship_model=[("cr-90", 1), ("gr-75", 2)],  # leader, then two wingmen
    bot_type="major_ship",
    team=1,
    spawn_point=[0, -2000, 200],
    spawn_orientation=FACING_NORTH,
    formation="arrowhead",
    formation_scale_m=150,
    waypoints=[
        [0, 0, 200],
        [0, 3000, 200],
        [500, 4000, 200],
        [1000, 4500, 200],
        [2000, 5000, 200],
        [5000, 5000, 200],
        [6000, 4500, 200],
        [6500, 4000, 200],
        [7000, 3000, 200],
    ],
    hyperspace=True,
)
# The convoy is past the blockade once it reaches its last waypoint.
CONVOY_LAST_WAYPOINT = len(TRANSPORTS.waypoints) - 1
# Where the convoy turns east along the coast, about halfway.
CONVOY_HALFWAY_WAYPOINT = 4

ESCORT = WaveSpec(
    name="escort",
    ship_model="x-wing",
    size=8,
    team=1,
    spawn_point=[200, -2100, 300],
    spawn_orientation=FACING_NORTH,
    formation="arrowhead",
    # Flies alongside the convoy: 200m to its right, 100m above.
    waypoints=[[x + 200, y, z + 100] for x, y, z in TRANSPORTS.waypoints],
    hyperspace=True,
)

FIRST_WAVE = WaveSpec(
    name="first_wave",
    ship_model="tie-bomber",
    size=5,
    spawn_point=[300, 6000, 500],
    spawn_orientation=FACING_SOUTH,
    formation="arrowhead",
    waypoints=[[300, 0, 500], [300, -6000, 500]],
)

SECOND_WAVE = WaveSpec(
    name="second_wave",
    ship_model="tie-fighter",
    size=5,
    spawn_point=[300, 5700, 800],
    spawn_orientation=FACING_SOUTH,
    formation="diamond",
    waypoints=[[300, 0, 500], [300, -6000, 500]],
)

THIRD_WAVE = WaveSpec(
    name="third_wave",
    ship_model="tie-bomber",
    size=8,
    spawn_point=[300, 0, 500],
    spawn_orientation=FACING_NORTH,
    formation="diamond",
    waypoints=[[300, 6000, 500], [300, 0, 500]],
)

FOURTH_WAVE = WaveSpec(
    name="fourth_wave",
    ship_model="tie-fighter",
    size=5,
    spawn_point=[300, 300, 800],
    spawn_orientation=FACING_NORTH,
    formation="diamond",
    waypoints=[[300, 6000, 500], [300, 0, 500]],
)


def build_mission3_upfront(game: FlightState):
    """
    Build the heavy, up-front part of the level — run synchronously on a black
    screen BEFORE the hyperspace animation starts.

    This is the player plus the scene's GPU-heavy objects (ocean, cloud field),
    whose one-time first-render preparation would otherwise spike a frame in the
    middle of the animation. The player is created here first because the scene's
    ocean reflection camera copies the player camera's lens.

    :param game: The game/flight state
    """
    build_upfront(
        game,
        scene_name="ocean_planet",
        player_ship_type="a-wing",
        player_position=[0, -2600, 250],
    )


def mission3_mission(m: Mission) -> Iterator[None]:
    """
    The mission3 level's mission body.

    Two timed waves, plus reactive rules registered up front (they must hold
    wherever the timed sequence currently is): a third wave at 200s or once
    the first wave is wiped, and the win/lose conditions on the convoy.

    :param m: The level's :class:`Mission`
    """
    # Handles first, so the rules below can refer to waves not spawned yet.
    transports = m.wave(TRANSPORTS)
    escort = m.wave(ESCORT)
    first_wave = m.wave(FIRST_WAVE)
    second_wave = m.wave(SECOND_WAVE)
    third_wave = m.wave(THIRD_WAVE)
    fourth_wave = m.wave(FOURTH_WAVE)

    # --- reactive rules, live for the whole mission --------------------------

    # Reinforcements at 200s, or 3s after the first wave is wiped -- whichever
    # comes first, and only once.
    def spawn_third_wave():
        m.speech(
            "More bombers, eight of them, dropping out of the clouds!",
            speaker="Red Two",
        )
        third_wave.spawn(target=transports)
        fourth_wave.spawn(target=[escort, m.game.player])
        m.objective(
            "Stop the second bomber wave",
            progress=third_wave.destroyed_count,
            goal=THIRD_WAVE.size,
        )

    m.on(any_of(m.after(200), m.delay(first_wave.all_destroyed, 3)), spawn_third_wave)

    # Won once the convoy reaches its last waypoint and wave 2 is gone.
    convoy_arrived = reached_waypoint(transports, CONVOY_LAST_WAYPOINT)
    blockade_past = all_of(convoy_arrived, second_wave.all_destroyed)
    m.say_when(
        blockade_past,
        "We're through! Thank you, Red squadron. We owe you one.",
        speaker="Convoy Lead",
    )

    # Also won once every enemy wave is down: the convoy is safe from there,
    # no need to wait for it to reach the fleet.
    every_wave_down = all_of(
        first_wave.all_destroyed,
        second_wave.all_destroyed,
        third_wave.all_destroyed,
        fourth_wave.all_destroyed,
    )
    convoy_safe = all_of(every_wave_down, transports.alive)

    m.objective(
        "Escort the convoy to the fleet",
        done=any_of(convoy_arrived, convoy_safe),
        failed=transports.all_destroyed,
    )
    m.objective(
        "Bonus: lose no transport",
        done=any_of(convoy_arrived, convoy_safe),
        failed=transports.any_destroyed,
    )
    m.on(
        m.delay(blockade_past, 3),
        lambda: m.victory("The convoy reached the fleet. Mission accomplished."),
    )
    m.on(
        m.delay(convoy_safe, ALL_CLEAR_VICTORY_DELAY_S),
        lambda: m.victory(
            "Every enemy wave destroyed. The convoy is safe. Mission accomplished."
        ),
    )

    m.say_when(
        transports.any_destroyed,
        "A transport has been destroyed! Focus fire on the bombers!",
        speaker="Red Leader",
    )
    m.say_when(
        m.delay(transports.any_destroyed, 3),
        "We just lost a transport, crew and all. Don't let it happen again!",
        speaker="Convoy Lead",
    )
    m.say_when(
        damaged(transports),
        "We're taking hits! Get those bombers off us!",
        speaker="Convoy Lead",
    )
    m.say_when(
        lambda: transports.destroyed_count() == 2,
        "Another transport gone! Last ship, stick to the escort like glue!",
        speaker="Convoy Lead",
    )
    m.say_when(
        transports.all_destroyed,
        "All transports have been destroyed. Let's retreat!",
        speaker="Red Leader",
    )
    m.on(
        m.delay(transports.all_destroyed, 3),
        lambda: m.defeat("The convoy has been destroyed."),
    )

    # --- combat chatter -------------------------------------------------------
    m.say_when(first_wave.any_destroyed, "Scratch one bomber!", speaker="Red Two")
    m.say_when(second_wave.any_destroyed, "Splash one TIE!", speaker="Red Three")

    # A wave cleared, commented on by what is left of its kind: more of them
    # still flying, more to come, or the last of them.
    def comment_on_the_clear(
        wave: WaveHandle,
        kind: list,
        lines: dict,
        after_the_last: Optional[Callable[[], Iterator[None]]] = None,
    ):
        def comment():
            others = [other for other in kind if other is not wave]
            if any(other.alive() for other in others):
                speaker, line = lines["more_flying"]
            elif not all(other.ids for other in others):
                speaker, line = lines["more_to_come"]
            else:
                speaker, line = lines["last"]
                if after_the_last is not None:
                    m.schedule(after_the_last())
            m.speech(line, speaker=speaker)

        m.on(wave.all_destroyed, comment)

    def convoy_runs_for_it() -> Iterator[None]:
        yield from m.wait(4)
        if not every_wave_down():
            m.speech(
                "Copy, Red Leader. Pushing our engines past the red line.",
                speaker="Convoy Lead",
            )

    bombers = [first_wave, third_wave]
    fighters = [second_wave, fourth_wave]
    for wave in bombers:
        comment_on_the_clear(wave, bombers, BOMBER_CLEAR_LINES, convoy_runs_for_it)
    for wave in fighters:
        comment_on_the_clear(wave, fighters, FIGHTER_CLEAR_LINES)

    # Registered after the waves' comments, so it has the last word.
    m.say_when(
        every_wave_down,
        "That's every last one of them! Nothing left up here but us.",
        speaker="Red Leader",
    )
    m.say_when(
        m.delay(every_wave_down, 4),
        "Red squadron, the drinks are on us when we land.",
        speaker="Convoy Lead",
    )

    # Each pilot lost, mourned by the first survivor in the chain of command.
    mourned = set()

    def mourn_the_escort():
        alive_ids = {pawn.id for pawn in escort.pawns()}
        survivors = [
            name for pawn_id, name in zip(escort.ids, RED_NAMES) if pawn_id in alive_ids
        ]
        for pawn_id, name in zip(escort.ids, RED_NAMES):
            if pawn_id in alive_ids or pawn_id in mourned:
                continue
            mourned.add(pawn_id)
            if survivors:
                line = ESCORT_LOSS_LINES[min(len(mourned), len(ESCORT_LOSS_LINES)) - 1]
                m.speech(line.format(name=name), speaker=survivors[0])

    m.on(lambda: escort.destroyed_count() > len(mourned), mourn_the_escort, once=False)
    m.say_when(
        escort.all_destroyed,
        "Red squadron's gone... It's all on you now, Red Seven.",
        speaker="Convoy Lead",
    )
    m.say_when(
        reached_waypoint(transports, CONVOY_HALFWAY_WAYPOINT),
        "Turning east along the coast. Halfway there, keep them off us!",
        speaker="Convoy Lead",
    )

    # --- the timed waves ------------------------------------------------------
    yield from m.wait(1)
    transports.spawn()

    yield from m.wait(2)
    escort.spawn()
    m.speech(
        "Red squadron standing by. Red Seven, that A-wing's the fastest\n"
        "thing we've got: you're our interceptor. Stay near the convoy.",
        speaker="Red Leader",
    )

    yield from m.wait(10)
    m.speech(
        "Convoy Lead to escort: we're slow, fat and full of medical supplies.\n"
        "We're counting on you.",
        speaker="Convoy Lead",
    )

    yield from m.wait(4)
    first_wave.spawn(target=transports)
    m.objective(
        "Shoot down the bombers",
        progress=first_wave.destroyed_count,
        goal=FIRST_WAVE.size,
    )
    m.speech(
        "Bombers, dead ahead and coming in low! They're after the transports.\n"
        "Red Seven, break and engage!",
        speaker="Red Leader",
    )

    yield from m.wait(20)
    # Interceptors hunt fighters: the escort and the player's A-wing.
    second_wave.spawn(target=[escort, m.game.player])
    m.objective(
        "Clear the TIE-Fighters",
        progress=second_wave.destroyed_count,
        goal=SECOND_WAVE.size,
    )
    m.speech("TIE-Fighters! They're coming for us this time!", speaker="Red Two")
    yield from m.wait(3)
    m.speech(
        "Red Two, Three, with me on the fighters.\n"
        "Seven, keep those bombers off the convoy!",
        speaker="Red Leader",
    )
