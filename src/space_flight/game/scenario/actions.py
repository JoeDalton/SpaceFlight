"""
Action factories for scenario triggers.

An action is any callable ``action(game) -> None``. Actions are the imperative
part that stays in Python: they create actors, assign targets, drive the HUD.
The declarative part (sizes, models, spawn points, times) lives in the level's
YAML and reaches these factories as a plain config value.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional, Union

import numpy as np

from space_flight.ai.formation import Formation
from space_flight.ui.player_waypoints import PlayerWaypoints

if TYPE_CHECKING:
    from collections.abc import Iterator

    from space_flight.actors.bot import Bot
    from space_flight.game.flight_state import FlightState
    from space_flight.game.scenario import Action

LOGGER = logging.getLogger()

# Quaternion convention used by the level scenario data (x, y, z, w).
DEFAULT_SPAWN_ORIENTATION = np.array([0, 0, 0, 1])


def spawn_wave(cfg: dict) -> Action:
    """
    Build a wave of bots from a config dict, one ship per frame.

    The wave's ``id`` doubles as its group name, so ``all_destroyed(id)`` and
    targeting-by-name work against it with no extra bookkeeping. When the wave
    declares a ``formation``, the leader spawns at ``spawn_point`` and each
    wingman at its formation slot offset from there; the formation is created per
    wave and kept alive on the scenario so it is not garbage collected once
    spawning finishes.

    Spawning is spread across frames via a scenario job, so a large wave never
    stalls the simulation on a single long loading frame.

    Expected ``cfg`` keys: ``id``, ``size``, ``ship_model``, ``spawn_point``.
    Optional: ``bot_type``, ``team``, ``spawn_orientation``, ``formation``,
    ``record`` (step-by-step-record every bot of this wave via ``game.record``)
    (``{scale_m, shape}``), ``waypoints``, ``loop``, ``target``, ``hud_text``,
    ``hud_time_s``, ``allow_respawn``.

    A wave id is an identity group, so by default it spawns at most once even if
    several triggers point at it: a second attempt is skipped with a warning. Set
    ``allow_respawn: true`` for the rare case where re-spawning the same
    composition into the same group is intended.

    :param cfg: The wave configuration
    :return: The action callable
    """

    def action(game: FlightState) -> None:
        wave_id = cfg["id"]
        if wave_id in game.scenario.scheduled and not cfg.get("allow_respawn", False):
            LOGGER.warning(
                "spawn_wave: '%s' already spawned; skipping "
                "(set allow_respawn: true to override)",
                wave_id,
            )
            return
        # Claim the id in `scheduled` (not `spawned`) so a re-trigger in the same
        # frame cannot schedule a second job, while a condition like
        # `all_destroyed` still sees the wave as "not yet spawned" until its
        # ships actually exist — otherwise it would fire the instant the wave is
        # scheduled but before any ship has spawned.
        game.scenario.scheduled.add(wave_id)
        game.scenario.schedule(_spawn_wave_job(game, cfg))

    return action


def _spawn_wave_job(game: FlightState, cfg: dict) -> Iterator[None]:
    """
    Generator that spawns one ship of a wave per frame.

    Scheduled by :func:`spawn_wave`; advanced once per frame by the scenario
    engine. Yields after each ship so the render loop keeps running.

    :param game: The game/flight state
    :param cfg: The wave configuration (see :func:`spawn_wave`)
    :return: A generator yielding once per spawned ship
    """
    wave_id = cfg["id"]
    size = cfg["size"]
    spawn_point = np.array(cfg["spawn_point"], dtype=float)
    orientation = np.array(cfg.get("spawn_orientation", DEFAULT_SPAWN_ORIENTATION))
    waypoints = [np.array(w) for w in cfg.get("waypoints", [])]
    formation_cfg = cfg.get("formation")

    # A wave only forms up if it declares a formation; otherwise it spawns in a
    # simple centred line (also used for ships past the formation's capacity).
    formation: Optional[Formation] = None
    offsets: Optional[list[np.ndarray]] = None
    if formation_cfg is not None:
        formation = Formation(
            scale_m=formation_cfg.get("scale_m"),
            shape=formation_cfg.get("shape"),
        )
        offsets = formation.relative_positions
        game.scenario.formations.append(formation)

    if cfg.get("hud_text") and not game.headless:
        game.hud.set_event_text(
            text=cfg["hud_text"], display_time_s=cfg.get("hud_time_s", 2.5)
        )

    for i in range(size):
        bot = game.scenario.spawn(
            game,
            groups=[wave_id],
            name=f"{wave_id}_{i}",
            bot_type=cfg.get("bot_type", "fighter"),
            pawn_model=cfg["ship_model"],
            ini_position=spawn_point + _wave_offset(offsets, i, size),
            ini_orientation=orientation,
            team=cfg.get("team", 2),
            debug_decisions=False,
            record=cfg.get("record", False),
        )
        if formation is not None:
            formation.add_ship(ship=bot.pawn)
        if waypoints:
            bot.navigator.set_waypoints(
                waypoints=waypoints, is_loop=cfg.get("loop", True)
            )
        if cfg.get("target"):
            _assign_targets(game, bot, cfg["target"])
        yield  # hand control back so only one ship spawns this frame


def _wave_offset(offsets: Optional[list[np.ndarray]], i: int, size: int) -> np.ndarray:
    """
    Spawn offset for the i-th ship of a wave, relative to its spawn point.

    Uses the formation slot offset when one is available (the leader at index 0
    is the zero offset, so it spawns exactly on the spawn point). Falls back to a
    centred line for waves with no formation, or for ships beyond the formation's
    capacity.

    :param offsets: The formation's scaled relative positions, or ``None``
    :param i: The ship index within the wave
    :param size: The total wave size
    :return: A world-space offset from the spawn point
    """
    if offsets is not None and i < len(offsets):
        return offsets[i]
    return np.array([-(size // 2) * 50 + 50 * i, 0, 0], dtype=float)


def hud_text(text: str, display_time_s: float = 2.5) -> Action:
    """
    Show a one-off message in the HUD event banner.

    :param text: The message to display
    :param display_time_s: How long to show it, in seconds
    :return: The action callable
    """

    def action(game: FlightState) -> None:
        # There is no HUD headless, and no one to read the message.
        if not game.headless:
            game.hud.set_event_text(text=text, display_time_s=display_time_s)

    return action


def player_waypoints(cfg: Union[list, dict]) -> Action:
    """
    Give the player a route to follow, shown as targetable waypoint spheres.

    Only the next waypoint is visible at a time; reaching it reveals the next.
    ``cfg`` is either a bare list of points, or a mapping with ``points``
    (required) and the optional ``arrival_radius_m`` / ``marker_radius_m``.

    :param cfg: The list of waypoints, or a mapping describing the route
    :return: The action callable
    """
    if isinstance(cfg, list):
        cfg = {"points": cfg}
    points = cfg["points"]
    kwargs = {}
    if "arrival_radius_m" in cfg:
        kwargs["arrival_radius_m"] = cfg["arrival_radius_m"]
    if "marker_radius_m" in cfg:
        kwargs["marker_radius_m"] = cfg["marker_radius_m"]

    def action(game: FlightState) -> None:
        game.player_waypoints = PlayerWaypoints(game, points, **kwargs)

    return action


def speech(cfg: Union[str, dict]) -> Action:
    """
    Play a line of speech and show it as a subtitle at the bottom of the screen.

    ``cfg`` may be a bare string (the line of text) or a mapping with keys
    ``text`` (required), ``speaker`` (optional, prefixed to the subtitle), and
    ``display_time_s`` (optional). The audio side is stubbed for now (see
    :func:`_play_speech_audio`); only the subtitle is rendered.

    :param cfg: The speech text, or a mapping describing the line
    :return: The action callable
    """
    if isinstance(cfg, str):
        cfg = {"text": cfg}
    text = cfg["text"]
    speaker = cfg.get("speaker")
    display_time_s = cfg.get("display_time_s", 4.0)
    subtitle = f"{speaker}: {text}" if speaker else text

    def action(game: FlightState) -> None:
        _play_speech_audio(cfg)
        # There is no HUD headless, and no one to read the subtitle.
        if not game.headless:
            game.hud.set_chatter_text(text=subtitle, display_time_s=display_time_s)

    return action


def _play_speech_audio(cfg: dict) -> None:
    """
    Placeholder for playing the spoken-audio clip of a speech line.

    No-op for now: real voice-line playback is not wired up yet, so we only log
    the intent. Replace this with actual audio playback later.

    :param cfg: The speech configuration (``text``, optional ``speaker``)
    """
    speaker = cfg.get("speaker", "narrator")
    LOGGER.info("speech [%s]: %s", speaker, cfg.get("text", ""))


def end_level(cfg: Union[str, dict]) -> Action:
    """
    End the level, summoning the level-end screen for the given outcome.

    Pauses the game beneath it. ``cfg`` may be a bare string (the outcome) or a
    mapping with ``outcome`` (``victory``, ``defeat`` or ``death``) and an
    optional ``text`` explaining the result.

    :param cfg: The outcome string, or a mapping describing the ending
    :return: The action callable
    """
    if isinstance(cfg, str):
        cfg = {"outcome": cfg}
    outcome = cfg["outcome"]
    text = cfg.get("text", "")

    def action(game: FlightState) -> None:
        game.end_level(outcome=outcome, text=text)

    return action


def all(actions: list[Action]) -> Action:
    """
    Run several actions in order when the trigger fires.

    :param actions: The actions to run, in order
    :return: The composed action callable
    """

    def action(game: FlightState) -> None:
        for act in actions:
            act(game)

    return action


def _assign_targets(game: FlightState, bot: Bot, group: str) -> None:
    """
    Make every live member of ``group`` a primary target of ``bot``.

    Dead targets are simply not in the resolved list, so there is nothing to
    guard against.

    :param game: The game/flight state
    :param bot: The bot whose tactician gets the targets
    :param group: The target group name
    """
    for pawn in game.scenario.resolve(game, group):
        bot.tactician.primary_target_ids.append(pawn.id)
