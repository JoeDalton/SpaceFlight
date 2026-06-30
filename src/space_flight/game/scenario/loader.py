"""
Turns a level's YAML scenario file into a :class:`Scenario`.

The file has two sections::

    waves:        # reusable spawn definitions, keyed by group id
      first_wave:
        size: 5
        ship_model: tie-bomber
        spawn_point: [300, 6000, 500]
        ...

    triggers:     # mission rules: when -> then
      - when: { after_seconds: 50 }
        then: { spawn: first_wave }
      - when: { delay: { after: { all_destroyed: first_wave }, seconds: 3 } }
        then: { spawn: second_wave }

Each ``when``/``then`` node is a single-key dict whose key selects a factory from
:mod:`scenario.conditions` / :mod:`scenario.actions`. ``when`` is parsed
recursively so combinators (``delay``, ``all_of``, ``any_of``) nest naturally.

Requires PyYAML.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

import yaml

from space_flight.game.scenario import Scenario, Trigger, actions, conditions

if TYPE_CHECKING:
    from space_flight.game.scenario import Action, Condition


def load_scenario(path: Union[str, Path]) -> Scenario:
    """
    Load and build a :class:`Scenario` from a YAML file.

    :param path: Path to the scenario YAML
    :return: A ready-to-run :class:`Scenario`
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    waves = data.get("waves", {})

    triggers = []
    for entry in data.get("triggers", []):
        condition = _build_condition(entry["when"])
        action = _build_action(entry["then"], waves)
        triggers.append(
            Trigger(
                condition=condition,
                action=action,
                once=entry.get("once", True),
                name=entry.get("name"),
            )
        )

    scenario = Scenario(triggers)
    # Pre-declare every wave id as a (still empty) identity group so conditions
    # that poll it before it spawns (e.g. `near: {who: <wave>}`) resolve to an
    # empty list instead of warning about an "unknown group". Genuine typos in
    # group references still warn.
    for wave_id in waves:
        scenario.groups.setdefault(wave_id, [])
    return scenario


def _single(node: dict) -> tuple[str, Any]:
    """
    Unpack a single-key ``{kind: arg}`` node.

    :param node: The mapping to unpack
    :return: The node's key and its value
    """
    if not isinstance(node, dict) or len(node) != 1:
        raise ValueError(f"Expected a single-key mapping, got {node!r}")
    ((kind, arg),) = node.items()
    return kind, arg


def _build_condition(node: dict) -> Condition:
    """
    Recursively build a condition callable from a ``when`` node.

    Every condition is a single-key mapping (e.g. ``{after_seconds: 10}``,
    ``{fired: blockade_past}``) — including the inner ``after`` of a ``delay``.

    :param node: A condition node
    :return: The condition callable
    """
    kind, arg = _single(node)
    if kind == "after_seconds":
        return conditions.after_seconds(arg)
    if kind == "all_destroyed":
        return conditions.all_destroyed(arg)
    if kind == "any_destroyed":
        return conditions.any_destroyed(arg)
    if kind == "any_alive":
        return conditions.any_alive(arg)
    if kind == "fired":
        return conditions.fired(arg)
    if kind == "reached_waypoint":
        return conditions.reached_waypoint(arg["who"], arg["index"])
    if kind == "near":
        return conditions.near(arg["who"], arg["point"], arg["radius"])
    if kind == "delay":
        return conditions.Delay(_build_condition(arg["after"]), arg["seconds"])
    if kind == "all_of":
        return conditions.AllOf(*[_build_condition(n) for n in arg])
    if kind == "any_of":
        return conditions.AnyOf(*[_build_condition(n) for n in arg])
    raise ValueError(f"Unknown condition '{kind}'")


def _build_action(node: dict, waves: dict) -> Action:
    """
    Build an action callable from a ``then`` node.

    Every action is a single-key mapping (e.g. ``{spawn: first_wave}``,
    ``{end_level: victory}``).

    :param node: An action node
    :param waves: The file's ``waves`` section, for ``spawn`` to look up
    :return: The action callable
    """
    kind, arg = _single(node)
    if kind == "spawn":
        if arg not in waves:
            raise ValueError(f"spawn: unknown wave '{arg}'")
        return actions.spawn_wave({"id": arg, **waves[arg]})
    if kind == "hud_text":
        # arg may be a bare string or {text, display_time_s}
        if isinstance(arg, str):
            return actions.hud_text(arg)
        return actions.hud_text(arg["text"], arg.get("display_time_s", 2.5))
    if kind == "speech":
        # arg may be a bare string or {text, speaker, display_time_s}
        return actions.speech(arg)
    if kind == "player_waypoints":
        # arg may be a bare list of points or {points, *_radius_m}
        return actions.player_waypoints(arg)
    if kind == "end_level":
        # arg may be a bare outcome string or {outcome, text}
        return actions.end_level(arg)
    if kind == "all":
        return actions.all([_build_action(n, waves) for n in arg])
    raise ValueError(f"Unknown action '{kind}'")
