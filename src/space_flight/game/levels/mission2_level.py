"""
Mission 2: Smugglers -- a patrol mission in the asteroid field of Mission 1.

Blue flight (Blue Leader, Blue Two and the player as Blue Three) patrols the
field for gun-runners. Three neutral GR-75 transports pass through and must
be scanned, not shot (the scan: lock the transport, close within 1000m and
hold it ahead for 15s). All three are clean; a fourth, late straggler is
not. Its scan reveals weapons: it turns hostile and flees for a jump point
while four TIEs jump Blue flight from behind. Won once the smuggler and the
TIEs are destroyed with at most one wingman lost -- with a bonus line when
nobody was lost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator, Sequence

import numpy as np

from space_flight.actors.player import Player
from space_flight.game.scenario import WaveSpec
from space_flight.game.scenario.conditions import all_of, any_of, damaged, near
from space_flight.scenes.scenes import scene_factory
from space_flight.ui.input_context import InputContext

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState
    from space_flight.game.scenario import Mission, WaveHandle

# --- tunable numbers -------------------------------------------------------
# Sized to fit inside the "asteroids" scene's field (field_size=15000, so
# +/-7500m around the origin) -- easy to retune after a playtest.
PLAYER_SPAWN_POINT = [0, -5000, 500]

# Blue flight's patrol loop, around the middle of the field.
PATROL_WAYPOINTS = [
    [0, -2500, 500],
    [1200, 0, 600],
    [0, 2500, 550],
    [-1200, 0, 450],
]

# The clean convoy crosses the field from its north-east corner. Its route
# ends far outside the field, so it never runs out during the mission (a
# bot whose route ends regroups with its "friends" instead).
CONVOY_SPAWN_POINT = [8000, 5200, 700]
EXIT_GATE = [-6500, -3800, 500]
CONVOY_ROUTE = [
    [6000, 4000, 700],
    [2000, 1500, 600],
    [-2000, -1000, 550],
    EXIT_GATE,
    [-14000, -8000, 500],
]
EXIT_GATE_RADIUS_M = 800

# The smuggler spawns relative to the player once the convoy is cleared,
# crossing in front of them.
SMUGGLER_AHEAD_M = 4000
SMUGGLER_LEFT_M = 2500
SMUGGLER_CROSSING_AHEAD_M = 1500
SMUGGLER_EXIT_GATE_M = 6000  # past the crossing point: "left unscanned"
SMUGGLER_ROUTE_END_M = 20000  # past the crossing point: never reached

# Once revealed, the smuggler flees this far along its nose to jump out.
ESCAPE_DISTANCE_M = 6000
JUMP_POINT_RADIUS_M = 400

TIES_BEHIND_M = 1000

INTRO_DELAY_S = 40  # patrol chatter before the convoy shows up
CONVOY_INTERVAL_S = 20  # between two convoy transports
DEFEAT_DELAY_S = 3
VICTORY_DELAY_S = 3


def yaw_towards(start: Sequence[float], end: Sequence[float]) -> tuple:
    """
    The level-flight orientation, as a (w, x, y, z) quaternion about z,
    facing from start towards end (ships fly along their +y axis).

    :param start: World position
    :param end: World position
    :return: The quaternion
    """
    dx, dy = end[0] - start[0], end[1] - start[1]
    half_yaw = 0.5 * np.arctan2(-dx, dy)
    return (float(np.cos(half_yaw)), 0.0, 0.0, float(np.sin(half_yaw)))


BLUE_FLIGHT = WaveSpec(
    name="blue",
    ship_model="x-wing",
    size=2,
    team=1,
    spawn_point=[0, -4600, 500],
    spawn_orientation=(1, 0, 0, 0),  # north, as the player
    formation="arrowhead",
    waypoints=PATROL_WAYPOINTS,
    loop=True,
)


def _transport(name: str) -> WaveSpec:
    """One neutral convoy GR-75 on the convoy route."""
    return WaveSpec(
        name=name,
        ship_model="gr-75",
        size=1,
        bot_type="capital_ship",
        team=0,
        spawn_point=CONVOY_SPAWN_POINT,
        spawn_orientation=yaw_towards(CONVOY_SPAWN_POINT, CONVOY_ROUTE[0]),
        waypoints=CONVOY_ROUTE,
        loop=False,
    )


CONVOY = [_transport("Aurek"), _transport("Besh"), _transport("Cresh")]

# Spawn point, orientation and route depend on the player, given at spawn time.
SMUGGLER = WaveSpec(
    name="Dorn", ship_model="gr-75", size=1, bot_type="capital_ship", team=0
)

TIE_FLIGHT = WaveSpec(
    name="tie",
    ship_model="tie-fighter",
    size=4,
    team=2,
    formation="diamond",
)

CLEAR_LINES = [
    "Clean. Ration packs and hydrospanners.",
    "Second one's clean too.",
    "Third one's clean. Guess the intel was bad.",
]


class _Civilians:
    """The still-neutral live pawns of some waves, usable as a ``who``."""

    def __init__(self, waves: Sequence[WaveHandle]) -> None:
        self.waves = waves

    def pawns(self) -> list:
        return [p for w in self.waves for p in w.pawns() if p.team == 0]


def build_mission2_upfront(game: FlightState) -> None:
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


def mission2_mission(m: Mission) -> Iterator[None]:
    """
    Mission 2: Smugglers' mission body.

    :param m: The level's :class:`Mission`
    """
    game = m.game
    radial_key = InputContext.key_label(
        game.app.bindings, "flight", "radial_menu", "the target-menu key"
    )
    loop_key = InputContext.key_label(
        game.app.bindings, "flight", "loop_target", "the cycle-target key"
    )

    # Handles first, so the rules below can refer to waves not spawned yet.
    blue = m.wave(BLUE_FLIGHT)
    convoy = [m.wave(spec) for spec in CONVOY]
    smuggler = m.wave(SMUGGLER)
    ties = m.wave(TIE_FLIGHT)
    convoy_scans = [m.scan(transport) for transport in convoy]

    # Every rule that can end the level, cancelled together once it has
    # ended, so there is only ever one ending.
    endings = []
    ended = []

    def end(outcome: str, text: str) -> None:
        if ended:
            return
        ended.append(outcome)
        for rule in endings:
            rule.cancel()
        m.end_level(outcome, text)

    def lose_later(condition, speaker: str, line: str, text: str) -> None:
        """A defeat DEFEAT_DELAY_S after condition, announced at once."""
        endings.append(m.on(condition, lambda: m.speech(line, speaker=speaker)))
        endings.append(
            m.on(m.delay(condition, DEFEAT_DELAY_S), lambda: end("defeat", text))
        )

    # --- rules of engagement, live until the reveal --------------------------
    civilians = _Civilians([*convoy, smuggler])
    m.on(
        damaged(civilians),
        lambda: m.speech(
            "Blue Three, cease fire! Those are civilians!", speaker="Blue Leader"
        ),
    )
    revealed = []

    def civilian_destroyed() -> bool:
        return any(t.all_destroyed() for t in convoy) or (
            smuggler.all_destroyed() and not revealed
        )

    endings.append(
        m.on(
            civilian_destroyed,
            lambda: end(
                "defeat",
                "You destroyed a civilian transport. Your wings are grounded.",
            ),
        )
    )
    for transport, scan in zip(convoy, convoy_scans):
        lose_later(
            all_of(
                near(transport, EXIT_GATE, EXIT_GATE_RADIUS_M),
                lambda s=scan: not s.complete(),
            ),
            "Blue Leader",
            "It's leaving the field unscanned!",
            "An unscanned transport slipped through the patrol.",
        )
    endings.append(
        m.on(
            blue.all_destroyed,
            lambda: end("defeat", "Blue flight has been wiped out."),
        )
    )

    # --- scanning chatter ------------------------------------------------------
    m.on(
        any_of(*(scan.started for scan in convoy_scans)),
        lambda: m.speech(
            "That's it, steady... keep it in your sights.", speaker="Blue Leader"
        ),
    )
    cleared = []

    def on_clear() -> None:
        m.hud("Scan complete: CLEAR")
        m.speech(CLEAR_LINES[len(cleared)], speaker="Blue Two")
        cleared.append(True)

    for scan in convoy_scans:
        m.on(scan.complete, on_clear)

    # ==================================================================
    # 1. Patrol chatter
    # ==================================================================
    blue.spawn()
    yield from m.wait_until(lambda: len(blue.ids) == BLUE_FLIGHT.size)
    # Spawned first, so the formation leader.
    leader = blue.pawns()[0]

    def on_first_ally_lost() -> None:
        if leader in blue.pawns():
            m.speech("Blue Two is down! Stay sharp, Three.", speaker="Blue Leader")
        else:
            m.speech("Lead's hit! I'm on my own out here!", speaker="Blue Two")

    m.on(blue.any_destroyed, on_first_ally_lost)

    yield from m.wait(2)
    m.speech(
        "Blue Three, you're on my wing. Blue Two, take the high side.",
        speaker="Blue Leader",
    )
    yield from m.wait(4)
    m.speech("Copy, Lead. Quiet out here... too quiet.", speaker="Blue Two")
    yield from m.wait(4)
    m.speech(
        "Intel says gun-runners use this field to supply the Tarsus pirates.\n"
        "Every hull that comes through gets scanned.",
        speaker="Blue Leader",
    )
    yield from m.wait(6)
    m.hud("Stay with Blue Leader on patrol.")

    # ==================================================================
    # 2. The convoy: three clean transports to scan
    # ==================================================================
    yield from m.wait(INTRO_DELAY_S - 16)
    convoy[0].spawn()
    m.speech(
        "Contact! GR-75 transports coming in from the far side of the field.",
        speaker="Blue Two",
    )
    yield from m.wait(4)
    m.speech(
        "Their transponders say civilian freight. Weapons cold, nobody fires on them.\n"
        "Three, you've got the scanner. Check each one.",
        speaker="Blue Leader",
    )
    yield from m.wait(4)
    m.hud(
        f"Hold [{radial_key}], point at Capital ships, then press [{loop_key}]\n"
        "to lock a transport. Close to 1000m and keep it\n"
        "ahead of you for 15 seconds to scan it.",
        display_time_s=8,
    )
    yield from m.wait(CONVOY_INTERVAL_S - 8)
    convoy[1].spawn()
    yield from m.wait(CONVOY_INTERVAL_S)
    convoy[2].spawn()

    yield from m.wait_until(lambda: len(cleared) == len(convoy))

    # ==================================================================
    # 3. The straggler
    # ==================================================================
    yield from m.wait(4)
    m.speech("That's the lot. Heading home, Lead?", speaker="Blue Two")
    yield from m.wait(4)
    m.speech(
        "Not yet. Something about this doesn't sit right. Hold position.",
        speaker="Blue Leader",
    )
    yield from m.wait(6)

    player_pawn = game.player.pawn
    forward = player_pawn.forward
    spawn_point = (
        player_pawn.position
        + forward * SMUGGLER_AHEAD_M
        - player_pawn.right * SMUGGLER_LEFT_M
    )
    crossing = player_pawn.position + forward * SMUGGLER_CROSSING_AHEAD_M
    heading = (crossing - spawn_point) / np.linalg.norm(crossing - spawn_point)
    smuggler_exit = crossing + heading * SMUGGLER_EXIT_GATE_M
    smuggler.spawn(
        spawn_point=spawn_point, orientation=yaw_towards(spawn_point, crossing)
    )
    yield from m.wait_until(smuggler.alive)
    smuggler.set_waypoints(
        [crossing, smuggler_exit, crossing + heading * SMUGGLER_ROUTE_END_M],
        loop=False,
    )
    smuggler_scan = m.scan(smuggler, contraband=True)
    smuggler_unscanned_exit = m.on(
        near(smuggler, smuggler_exit, EXIT_GATE_RADIUS_M),
        lambda: end("defeat", "An unscanned transport slipped through the patrol."),
    )
    endings.append(smuggler_unscanned_exit)
    m.speech(
        "Another one! Late, alone, and running without a transponder.",
        speaker="Blue Two",
    )
    yield from m.wait(4)
    m.speech("Stragglers make me nervous. Scan it, Three.", speaker="Blue Leader")
    m.on(
        smuggler_scan.progress_at_least(0.5),
        lambda: m.speech(
            "It's picking up speed... it knows we're looking.", speaker="Blue Two"
        ),
    )

    yield from m.wait_until(smuggler_scan.complete)

    # ==================================================================
    # 4. The reveal: the smuggler runs, TIEs jump Blue flight
    # ==================================================================
    revealed.append(True)
    smuggler_unscanned_exit.cancel()
    m.hud("Scan complete: CONTRABAND - WEAPONS")
    m.speech("Weapons crates! It's a gun-runner!", speaker="Blue Leader")
    smuggler.set_team(2)

    dorn = smuggler.pawns()[0]
    jump_point = dorn.position + dorn.forward * ESCAPE_DISTANCE_M
    smuggler.set_waypoints(
        [jump_point, jump_point + dorn.forward * SMUGGLER_ROUTE_END_M], loop=False
    )
    m.on(
        near(smuggler, jump_point, ESCAPE_DISTANCE_M / 2),
        lambda: m.speech(
            "It's spinning up its hyperdrive! Hurry, Three!", speaker="Blue Leader"
        ),
    )
    lose_later(
        near(smuggler, jump_point, JUMP_POINT_RADIUS_M),
        "Blue Two",
        "It jumped to lightspeed...",
        "The gun-runner escaped with its cargo.",
    )

    ties.spawn(
        spawn_point=player_pawn.position - player_pawn.forward * TIES_BEHIND_M,
        orientation=player_pawn.orientation,
        target=blue,
    )

    m.on(
        smuggler.all_destroyed,
        lambda: m.speech("Transport's down! Good shooting!", speaker="Blue Leader"),
    )
    m.on(
        ties.all_destroyed,
        lambda: m.speech("That's the last TIE!", speaker="Blue Two"),
    )

    # The reveal's chatter runs alongside the ending, so a quick kill is not
    # held back by it.
    def reveal_chatter() -> Iterator[None]:
        yield from m.wait(1.5)
        m.speech("Blast! Escort, get them off me!", speaker="Dorn")
        yield from m.wait(1.5)
        m.speech("TIEs! Four of them, right on our six!", speaker="Blue Two")
        yield from m.wait(3)
        m.speech(
            "Two, with me on the fighters. Three, stop that transport\n"
            "before it jumps. Knock out its shield generators!",
            speaker="Blue Leader",
        )
        yield from m.wait(4)
        m.hud(
            f"Hold [{radial_key}], point at Subsystems, then press [{loop_key}]\n"
            "to target the shield generators."
        )

    m.schedule(reveal_chatter())

    # ==================================================================
    # 5. The ending
    # ==================================================================
    won = m.delay(all_of(smuggler.all_destroyed, ties.all_destroyed), VICTORY_DELAY_S)
    yield from m.wait_until(lambda: bool(ended) or won())
    if ended:
        return
    if len(blue.pawns()) == BLUE_FLIGHT.size:
        end(
            "victory",
            "Gun-runner stopped with no losses. Outstanding flying, Blue Three.\n"
            "Drinks are on Blue Leader.",
        )
    else:
        end(
            "victory",
            "Mission complete. The weapons never reached the pirates,\n"
            "but Blue flight lost a pilot.",
        )
