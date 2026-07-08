# AI

Every bot-controlled pawn — fighters, capital ships, turrets, tractor beams —
is flown by the same three-stage pipeline: a **tactician** decides *what* to
do, a **navigator** turns that into an explicit direction, and a **pilot**
converts the direction into control inputs the pawn's `move()` understands.
[`Bot.move_bot_task`](../src/space_flight/actors/bot.py) (and `Player`, for
an optionally AI-flown player ship) simply calls the three in sequence each
frame. This page is the guided tour; the per-class API is generated from the
docstrings in the [code reference](docs/).

Most of the code lives in [`src/space_flight/ai/`](../src/space_flight/ai/):
a `generic/` package with the shared base classes, and one package per pawn
family (`fighter/`, `capital_ship/`, `tracking_mount/`) with the concrete
subclasses. `auto_aim.py`, `collision_sensor.py`, `formation.py` and
`interactions.py` are supporting systems used by several of the above.

## The tactician → navigator → pilot pipeline

- **Tactician** ([`generic_tactician.py`](../src/space_flight/ai/generic/generic_tactician.py)):
  a finite state machine over `Intent` (`ENGAGE`, `EVADE`, `DISENGAGE`,
  `REGROUP`, `PATROL`, `FORMATION`, `IDLE`). `think()` re-evaluates the
  intent at a capped frequency (`intent_update_delay`) and only switches
  intent once a **commitment time** for the current intent has elapsed —
  hysteresis that stops a bot flip-flopping between behaviours every frame.
  `update_intent()` (subclass-specific) scores the tactical situation and
  returns `(intent, target_dict)`.
- **Navigator** ([`generic_navigator.py`](../src/space_flight/ai/generic/generic_navigator.py)):
  turns `(intent, target_dict)` into an explicit direction (plus, for ships,
  a desired speed). Provides shared aiming primitives: **Constant Angle
  Pursuit** (kill lateral velocity — good for closing from long range) and
  **lead/lag pursuit** (aim at the target's position at `now + lead_time_s`;
  negative lead time is a lag pursuit for close-in fights).
- **Pilot** ([`generic_pilot.py`](../src/space_flight/ai/generic/generic_pilot.py)):
  the actual control loop. `pilot()` is subclass-specific; concrete pilots
  wrap `simple_pid.PID` controllers (one per axis) that null out an angular
  error each frame.

`target_dict` is a small, informally-typed payload (`target_id`, `score`,
sometimes `position`/`formation_index`) threaded from tactician through
navigator; its exact keys depend on the intent, which is why every navigator
method that consumes it defensively handles the "no target" case.

## `Personality` and per-role tuning

[`ai/__init__.py`](../src/space_flight/ai/__init__.py) defines the shared
`Intent` enum and a `Personality` class holding pre-baked parameter
dictionaries — `FIGHTER_DEFAULT`, `TURRET_DEFAULT`, `TRACTOR_BEAM_DEFAULT`,
`CAPITAL_SHIP_DEFAULT` — one per pawn family. Each dictionary has a
`tactician`/`navigator`/`pilot` (and, for tractor beams, `tractor_beam`)
section holding every tunable constant for that trio: commitment times,
engagement thresholds, PID gains, pursuit biases and cutoff distances. No
tuning constant lives on the classes themselves — a personality dict is
passed in at construction and *is* the bot's behavioural fingerprint, so
retuning or adding a new archetype means adding a new `Personality` entry
rather than touching code. `Bot.set_personality()` can swap all three
components' personality live.

## Ship-flying trio: `Fighter` and `CapitalShip`

Both free-flying ship types share
[`generic_ship_navigator.py`](../src/space_flight/ai/generic/generic_ship_navigator.py)
(`GenericShipNavigator`) and
[`generic_ship_pilot.py`](../src/space_flight/ai/generic/generic_ship_pilot.py)
(`GenericShipPilot`):

- **`GenericShipNavigator`** blends an *intentional* direction
  (`navigate_intent`, subclass-specific) with a *collision-avoidance*
  direction from a [`CollisionSensor`](#collisionsensor-and-formation), the
  two weighted so avoidance can be dwarfed while flying in formation. It also
  implements the intent-agnostic behaviours every ship shares: `regroup`,
  `disengage`, waypoint following (`set_waypoints`/`follow_waypoints`) and
  `formation` (station-keeping relative to a wing leader, itself resolved via
  lead pursuit).
- **`GenericShipPilot`** owns four PID loops (yaw, pitch, roll, throttle),
  driven each frame by `compute_angular_error` (subclass-specific — a
  fighter and a capital ship point their axes at a target differently) and a
  velocity error against the navigator's desired speed.

| Family | Tactician | Navigator | Pilot |
|--------|-----------|-----------|-------|
| Fighter | [`fighter_tactician.py`](../src/space_flight/ai/fighter/fighter_tactician.py) | [`fighter_navigator.py`](../src/space_flight/ai/fighter/fighter_navigator.py) | [`fighter_pilot.py`](../src/space_flight/ai/fighter/fighter_pilot.py) |
| Capital ship | [`capital_ship_tactician.py`](../src/space_flight/ai/capital_ship/capital_ship_tactician.py) | [`capital_ship_navigator.py`](../src/space_flight/ai/capital_ship/capital_ship_navigator.py) | [`capital_ship_pilot.py`](../src/space_flight/ai/capital_ship/capital_ship_pilot.py) |

**`FighterTactician`** prioritises, in order: evade an overwhelming threat
(`evaluate_threats` against `max_threat_score`), disengage if its own
`evaluate_fighting_shape` (health + shield) is too low, engage the best-scored
prey (`evaluate_preys`, boosted for `primary_target_ids`), follow patrol
waypoints, hold formation, or regroup with allies — falling through a
priority list rather than a weighted blend.

**`FighterNavigator.engage_target`** is the most elaborate behaviour in the
codebase: it blends Constant Angle Pursuit, lead pursuit and lag pursuit with
distance-dependent weights (`compute_engage_weights`, overlapping smooth
step functions), fires the laser cannon itself once aligned and in range,
and can override pursuit entirely to `reposition` (hard turn away to avoid
overshooting a closing target) or `extend` (break off if stuck in a
low-closing-speed "spiral of death" for too long).

**`CapitalShipTactician`** mirrors the fighter's priority list minus
per-target engagement scoring (a capital ship engages a scripted/assigned
prey rather than hunting, via `scripted_prey_dict`) and reads shield level
through `Shield.get_shield_level()` for its fighting-shape estimate.
**`CapitalShipNavigator.engage_target`** is currently a stub
(`NotImplementedError`) — capital-ship-vs-target manoeuvring isn't
implemented yet, only patrol/regroup/disengage/formation. **`CapitalShipPilot`**
only corrects yaw/pitch toward a target and rolls purely to stay upright with
the scene (no roll-to-target, unlike the more acrobatic fighter).

## Tracking-mount trio: turrets and tractor beams

[`tracking_mount/`](../src/space_flight/ai/tracking_mount/) is the AI for
anything that swivels in place rather than flies — shared by `Turret` and
`TractorBeamProjector`, both mounted subsystems of a capital ship (see
[Capital-ship subsystems](subsystems.md)):

- **`TrackingMountTactician`** is a stripped-down fighter tactician: score
  preys, engage the best one above `min_engagement_score`, otherwise `IDLE`.
  No evade/disengage/regroup — a mount can't flee.
- **`TrackingMountNavigator`** is purely an *aimer*: it computes a lead-pursuit
  direction and **publishes it onto the pawn** (`pawn.aim_direction`,
  `pawn.target_distance_m`) rather than acting on it. This is the same
  loose-coupling principle used throughout the subsystem code — the navigator
  doesn't know or care whether the mount will fire a laser or extend a
  tractor beam; the pawn's own per-frame logic reads the published solution
  and decides.
- **`TrackingMountPilot`** runs yaw/pitch PID loops against the mount's own
  *base* axes (`base_right`/`base_forward`/`base_up` — the socket it's bolted
  into) rather than world or ship axes, since a mount's yaw/pitch are always
  relative to its mounting.

A tractor beam bot uses the identical trio (`Personality.TRACTOR_BEAM_DEFAULT`
just adds a `tractor_beam` tuning section for grab timing) — see
[`Bot.__init__`](../src/space_flight/actors/bot.py) for how `bot_type`
selects one shared trio for both mount kinds.

## Supporting systems

### `AutoAim`

[`auto_aim.py`](../src/space_flight/ai/auto_aim.py) is a fighter's per-shot
targeting assist, distinct from the tactician/navigator/pilot pipeline (it's
driven from `Fighter.move()` and `LaserCannon.fire()`, not `Bot`). It tracks
whether the current target has stayed inside an acquisition cone for
`target_lock_delay_s`; once acquired, `compute_shot_speed` aims each shot at
the target's *predicted* impact-time position, clamped inside a maximum
assist angle around the barrel so the visual effect stays a "nudge" rather
than a snap-to-target. `configure()` is separated from `__init__` specifically
so a targeting system's boost (see [subsystems.md](subsystems.md)) can
retune a turret's auto-aim quality at runtime.

### `CollisionSensor` and `Formation`

[`collision_sensor.py`](../src/space_flight/ai/collision_sensor.py) gives a
ship three concentric forward collision-detection spheres; whatever collides
with them each frame contributes a weighted repulsion vector (closer
obstacles weigh more), consumed once per frame by
`GenericShipNavigator.navigate_avoidance` and wiped after reading.

[`formation.py`](../src/space_flight/ai/formation.py) is data, not AI logic:
`Formation` holds a named layout (`arrowhead`, `diamond`, `around_diamond`)
of scaled relative slot positions and the list of ship ids currently
occupying them. Ships read their own slot via `pawn.formation` +
`get_ship_index`; the actual station-keeping math lives in
`GenericShipNavigator.formation`.

### `Interactions`

[`interactions.py`](../src/space_flight/ai/interactions.py) is the central
per-frame relationship cache every tactician/navigator/auto-aim query reads
from instead of recomputing pairwise geometry themselves: for every pair of
*opposing* live actors (different non-neutral teams) it precomputes distance,
unit direction, relative velocity and forward alignment. Actors occupy
stable pre-allocated slots (`add_actor`/`remove_actor`, `MAX_ACTORS = 64` by
default) so slot indices never shift and no per-frame allocation is needed;
`update_interactions()` only iterates currently-live pairs, so cost scales
with the number of live actors, not the pre-allocated capacity.

## Where things live

The tactician/navigator/pilot base classes live in
[`ai/generic/`](../src/space_flight/ai/generic/); each pawn family's
concrete subclasses live in their own subpackage
(`ai/fighter/`, `ai/capital_ship/`, `ai/tracking_mount/`). `Personality` and
`Intent` are defined once in [`ai/__init__.py`](../src/space_flight/ai/__init__.py)
and shared by all of them. The auto-generated
[code reference](docs/) has the full per-class API.
