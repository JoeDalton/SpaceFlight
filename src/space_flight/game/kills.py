"""
Kill attribution: who killed whom.

Every hit stamps its target with who dealt it (:func:`credit_hit`), and the
last one standing when the target dies gets the kill, logged by the level's
:class:`KillLog` (``game.kill_log``). Deaths are found by polling health
(``Destructibles.handle_deaths``), so the stamp is what carries the cause up
to that point.

Who fired a shot is captured as a :class:`DamageSource` when it is fired,
not when it lands: the shooter may be gone (and torn down) by then.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable, Optional

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

#: Victim categories that count as kills (not ordnance, flares or shields).
KILL_CATEGORIES = ("fighter", "capital_ship", "sub_system")


def actor_name(actor: Any) -> str:
    """
    A readable name for a pawn or subsystem.

    Ships and turrets are named by their controller (a Bot, or the player);
    other subsystems (shield generators, hangars) by their ship and their own
    name, e.g. ``"isd/hangar_0"``.

    :param actor: A ship pawn or a subsystem
    :return: Its name
    """
    owner = getattr(actor, "parent", None)
    mounted_on = getattr(actor, "mounted_on", None)
    if mounted_on is not None and owner is mounted_on:
        return f"{actor_name(mounted_on)}/{actor.name}"
    return getattr(owner, "name", None) or getattr(actor, "name", None) or "unknown"


@dataclass(frozen=True)
class DamageSource:
    """
    Who dealt some damage, as it was when the shot was fired.

    :param actor_id: The shooter's pawn (or subsystem) id
    :param team: The shooter's team
    :param name: The shooter's name (see :func:`actor_name`)
    :param category: The shooter's category ("fighter", "sub_system", ...)
    :param is_player: Whether the player's ship fired it
    """

    actor_id: uuid.UUID
    team: int
    name: str
    category: Optional[str]
    is_player: bool

    @classmethod
    def of(cls, actor: Any, game: FlightState) -> DamageSource:
        """
        :param actor: The shooting (or ramming) pawn or subsystem
        :param game: The game/flight state, to tell the player apart
        :return: Its source, captured now
        """
        player = getattr(game, "player", None)
        return cls(
            actor_id=actor.id,
            team=getattr(actor, "team", 0),
            name=actor_name(actor),
            category=getattr(actor, "category", None),
            is_player=player is not None and actor is getattr(player, "pawn", None),
        )


def credit_hit(target: Any, source: Optional[DamageSource], cause: str = "weapon"):
    """
    Stamp target with who is hitting it, before the hit's damage is applied.

    A wreck (health already gone) keeps its stamp: its killer is settled, and a
    shot into the falling hull must not steal the kill.

    :param target: The pawn or subsystem about to take damage
    :param source: Who deals it (None for no one, e.g. terrain)
    :param cause: How: "weapon", "ram" or "crash"
    """
    if target.health <= 0.0:
        return
    target.last_hit_by = source
    target.last_hit_cause = cause


@dataclass(frozen=True)
class Kill:
    """
    One logged death.

    :param victim_id: The dead pawn's (or subsystem's) id
    :param victim_name: Its name (see :func:`actor_name`)
    :param victim_team: Its team when it died
    :param victim_category: Its category ("fighter", "capital_ship", "sub_system")
    :param victim_is_player: Whether it was the player's ship
    :param killer: Who gets the kill, None for no one (a crash, ...)
    :param cause: "weapon", "ram", "crash", "collateral" (died with the ship it
        was mounted on) or "unknown"
    :param time_s: Game time of the death
    """

    victim_id: uuid.UUID
    victim_name: str
    victim_team: int
    victim_category: str
    victim_is_player: bool
    killer: Optional[DamageSource]
    cause: str
    time_s: float

    @property
    def by_player(self) -> bool:
        """Whether the player gets this kill (never their own death)."""
        return (
            self.killer is not None
            and self.killer.is_player
            and not self.victim_is_player
        )


class KillLog:
    """
    Every kill of a level, in order. FlightState owns one (``game.kill_log``)
    and records each pawn or subsystem as it dies.

    :param game: The game/flight state
    """

    def __init__(self, game: FlightState):
        self.game = game
        self.kills: list[Kill] = []
        self._by_victim: dict[uuid.UUID, Kill] = {}

    def record(self, dead: Any) -> Optional[Kill]:
        """
        Log a death, crediting its last hitter.

        Takes a dying Destructible as it is: a Bot stands for its pawn. Only
        ships and subsystems count, and each only once: a turret dies both as
        its Bot and as its own subsystem. A subsystem that dies with the ship it
        was mounted on is credited to that ship's killer, whoever hit it last.

        :param dead: The Destructible (or player pawn) entering its death
        :return: The new kill, or None if it does not count / is already logged
        """
        victim = getattr(dead, "pawn", dead)
        category = getattr(victim, "category", None)
        if category not in KILL_CATEGORIES or victim.id in self._by_victim:
            return None

        killer = getattr(victim, "last_hit_by", None)
        cause = getattr(victim, "last_hit_cause", None)
        # A subsystem whose ship is gone is brought down with it (see
        # SubSystem.handle_health), whoever last scratched it.
        host = getattr(victim, "mounted_on", None)
        if host is not None and host is not victim and getattr(host, "is_dead", False):
            host_kill = self._by_victim.get(host.id)
            killer = None if host_kill is None else host_kill.killer
            cause = "collateral"

        player = getattr(self.game, "player", None)
        kill = Kill(
            victim_id=victim.id,
            victim_name=actor_name(victim),
            victim_team=getattr(victim, "team", 0),
            victim_category=category,
            victim_is_player=player is not None
            and victim is getattr(player, "pawn", None),
            killer=killer,
            cause=cause or "unknown",
            time_s=self.game.game_time.get_current_time(),
        )
        self.kills.append(kill)
        self._by_victim[victim.id] = kill
        return kill

    def kill_of(self, victim_id: uuid.UUID) -> Optional[Kill]:
        """The kill logged for victim_id, if it is dead."""
        return self._by_victim.get(victim_id)

    def count(
        self,
        victim_ids: Optional[Iterable[uuid.UUID]] = None,
        by_player: bool = False,
    ) -> int:
        """
        :param victim_ids: Only count these victims (all of them by default)
        :param by_player: Only count the player's kills
        :return: How many kills match
        """
        ids = None if victim_ids is None else set(victim_ids)
        return sum(
            1
            for kill in self.kills
            if (ids is None or kill.victim_id in ids)
            and (not by_player or kill.by_player)
        )

    def player_kills(self) -> list[Kill]:
        """The player's kills, in order."""
        return [kill for kill in self.kills if kill.by_player]

    def player_summary(self) -> dict:
        """
        The player's kill tally, for the level-end screen.

        :return: ``{"kills": n, "by_category": {category: n}, "friendly": n}``,
            friendly counting the player's kills on their own team
        """
        kills = self.player_kills()
        by_category = {}
        for kill in kills:
            by_category[kill.victim_category] = (
                by_category.get(kill.victim_category, 0) + 1
            )
        friendly = sum(
            1
            for kill in kills
            if kill.victim_team != 0 and kill.victim_team == kill.killer.team
        )
        return {"kills": len(kills), "by_category": by_category, "friendly": friendly}
