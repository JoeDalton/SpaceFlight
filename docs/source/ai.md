# AI

Every bot-controlled pawn — fighters, capital ships, turrets, tractor beams —
is flown by the same three-stage pipeline: a **tactician** decides *what* to
do, a **navigator** turns that into an explicit direction, and a **pilot**
converts the direction into control inputs the pawn's `move()` understands.
[`Bot.move_bot_task`](../../src/space_flight/actors/bot.py) (and `Player`, for
an optionally AI-flown player ship) calls the three in sequence. This page is
the guided tour; the per-class API is in the [code reference](apidocs/index.rst).

## The tactician → navigator → pilot pipeline

- **Tactician** ([`generic_tactician.py`](../../src/space_flight/ai/generic/generic_tactician.py)):
  a finite state machine over `Intent` (`ENGAGE`, `EVADE`, `DISENGAGE`,
  `REGROUP`, `PATROL`, `FORMATION`, `IDLE`, `DEFEND_MISSILE`). `think()`
  re-evaluates the intent every `intent_update_delay` and only switches once
  the current intent's **commitment time** has elapsed — hysteresis that stops
  a bot flip-flopping between behaviours. `update_intent()` (subclass-specific)
  scores the situation and returns `(intent, target_dict)`.
- **Navigator** ([`generic_navigator.py`](../../src/space_flight/ai/generic/generic_navigator.py)):
  turns `(intent, target_dict)` into a direction (plus, for ships, a desired
  speed). Shared aiming primitives: **Constant Angle Pursuit** (kill lateral
  velocity — closing from long range) and **lead/lag pursuit** (aim at the
  target's position at `now + lead_time_s`; a negative lead time lags).
- **Pilot** ([`generic_pilot.py`](../../src/space_flight/ai/generic/generic_pilot.py)):
  the control loop. Concrete pilots wrap one `simple_pid.PID` per axis, nulling
  an angular error once per sample period (`sample_time_s` in the personality:
  0.1 s for fighters and mounts, 0.2 s for capital ships).

`target_dict` is an informally-typed payload (`target_id`, `score`, and per
intent `position`, `formation_index`, `attack_mode`…). For `DISENGAGE`,
`PATROL` and `REGROUP`, `target_id` holds the `Intent` itself as a sentinel;
every navigator method that consumes the dict handles the "no target" case.

### When a bot thinks

The pilot's commands only change once per sample period, so a bot only
*thinks* (runs its navigator and pilot) on those frames and its ship flies the
last commands in between; the tactician, cheap and on its own timer, runs
every frame. [`think_scheduler.py`](../../src/space_flight/ai/think_scheduler.py)
cuts time into one-frame slots and gives each bot the least-busy slot of its
period, so every frame carries about the same share of bots instead of a
periodic hitch. The bot then drives its pilot's PIDs itself
(`sample_externally`).

Two things can't wait for the next think:
- **Weapons.** A fighter's gun reloads faster than the bot thinks, and a
  late bomb release misses. So `navigate()` arms its fire / release decision,
  and on the frames in between `FighterNavigator.update_triggers` takes it
  again on fresh geometry from [`Interactions`](#interactions).
- **Obstacle contacts.** The collision sensor only collects contacts for the
  frame the bot thinks in (see [`CollisionSensor`](#collisionsensor-and-formation)).

Turrets and tractor beams still navigate every frame (cheap, and it publishes
the firing solution the mount checks every frame); only their pilot follows
the schedule. The player's AI mode (`has_ai`) is not scheduled.

## `Personality` and per-role tuning

[`ai/__init__.py`](../../src/space_flight/ai/__init__.py) defines the shared
`Intent` and `AttackMode` (`PURSUIT`, `STRAFE`, `ORBIT`, `BOMB`) enums and
`Personality`, whose dictionaries — `FIGHTER_DEFAULT`, `TURRET_DEFAULT`,
`TRACTOR_BEAM_DEFAULT`, `ESCORT_SHIP_DEFAULT`, and `MISSILE_DEFAULT` (pilot
only) — hold, per
`tactician`/`navigator`/`pilot` section (plus `tractor_beam` for tractor
beams), most tunables: commitment times, engagement thresholds, PID gains,
pursuit biases, cutoff distances. A new archetype is mostly a new
`Personality` entry. Some tunables are still module constants
(`SCENE_ROLL_MULTIPLIER` in `fighter_pilot.py`, `COLLISION_REFERENCE_SPEED_MPS`
in `generic_ship_navigator.py`, `REFERENCE_ERROR_VELOCITY_MPS` in
`ai/__init__.py`, the `CollisionSensor` geometry, the `AutoAim` defaults).
`Bot.set_personality()` swaps the dict on all three components: values read
at use (tactician thresholds, navigator parameters) take effect immediately,
but PID gains are baked in at construction, and a mount pawn keeps its own
personality.

## Ship-flying trio: `Fighter` and `CapitalShip`

Both free-flying ship types share
[`GenericShipNavigator`](../../src/space_flight/ai/generic/generic_ship_navigator.py)
and [`GenericShipPilot`](../../src/space_flight/ai/generic/generic_ship_pilot.py):

- **`GenericShipNavigator`** blends an *intentional* direction
  (`navigate_intent`, subclass-specific) with a *collision-avoidance* one from
  a [`CollisionSensor`](#collisionsensor-and-formation), with an avoidance
  weight that phases flying deliberately close (formation, strafe corridor,
  bomb run) dwarf. It also implements the behaviours every ship shares:
  `regroup`, `disengage`, waypoint following (`set_waypoints` /
  `follow_waypoints`, which decelerates a ship that stops getting closer to its
  waypoint, e.g. orbiting it because its turn radius is too large) and `formation` (station-keeping on a wing leader by
  lead pursuit).
  A navigator may set a speed floor, `minimum_speed_mps` (`compute_minimum_speed`:
  an intent's `minimum_speed_factor` × `max_speed_mps`); a fighter's pursuit
  raises it to `attack.minimum_speed_factor` (reposition included), and with
  `minimum_speed_overrides_avoidance` avoidance cannot slow the ship below it
  (it still steers).
- **`GenericShipPilot`** owns four PID loops (yaw, pitch, roll, throttle),
  fed at each think by `compute_angular_error` (subclass-specific — a fighter
  and a capital ship point their axes differently) and the velocity error
  against the desired speed. The throttle is a feedforward estimate of the
  throttle holding the desired speed (`compute_feedforward_throttle`: drag
  plus lift-induced drag) plus the PID correction. Below the navigator's
  speed floor, the yaw/pitch commands are eased down to `min_turn_authority`
  over `energy_protection_range_factor` × `max_speed_mps`
  (`compute_turn_authority`, energy protection); roll is never limited.

| Family | Tactician | Navigator | Pilot |
|--------|-----------|-----------|-------|
| Fighter | [`fighter_tactician.py`](../../src/space_flight/ai/fighter/fighter_tactician.py) | [`fighter_navigator.py`](../../src/space_flight/ai/fighter/fighter_navigator.py) | [`fighter_pilot.py`](../../src/space_flight/ai/fighter/fighter_pilot.py) |
| Major ship | [`major_ship_tactician.py`](../../src/space_flight/ai/major_ship/major_ship_tactician.py) | [`major_ship_navigator.py`](../../src/space_flight/ai/major_ship/major_ship_navigator.py) | [`major_ship_pilot.py`](../../src/space_flight/ai/major_ship/major_ship_pilot.py) |

**`FighterTactician`** falls through a priority list (not a weighted blend):
defend against a missile close to impact (see below), evade an overwhelming
threat (`evaluate_threats` ≥ `max_threat_score`), disengage if
`evaluate_fighting_shape` (half health + shield) is too low, engage the
best-scored prey (`evaluate_preys`, boosted for
`primary_target_ids`), hold formation, patrol, else regroup. A wingman holds
formation even when it carries waypoints (`evaluate_orders`): every member of a
wave gets the route, so whoever takes the lead after the leader's death follows
it from where the leader left it (wingmen keep their route progress in step
with the leader's). When engaging it
also plans the attack (`_plan_attack`, in `target_dict`): first the weapon and
its launcher (`weapon`, `launcher`), then the geometry (`attack_mode`): `BOMB`
for a bomb, otherwise `STRAFE` vs. `PURSUIT` by the target's mobility (below
`strafe_mobility_threshold`, a target is *slow*, otherwise *agile*). The
weapon (`_choose_weapon`), among the launchers with stock left in the loadout,
matching the target's mobility (each missile and rocket says which targets it
is for, `target_mobility`):
- **heavy ordnance** — a bomb, or a torpedo against a slow *primary* target,
  whichever `prefer_torpedoes_to_bombs` puts first — only if it beats guns
  (`_heavy_ordnance_beats_guns`, `heavy_ordnance_scoring`: a target both tough
  and valuable, stationary enough, with stock to spare);
- a **concussion missile** against an agile *primary* target;
- a **rocket** against any slow target;
- the **guns** otherwise.

**Missile defense** comes first in that priority list:
`FighterTactician.evaluate_missile_defense` picks `DEFEND_MISSILE` (like any
intent change, once the current intent's commitment has elapsed) when the
nearest missile homing on the pawn (its `incoming_missiles`, see
[guided missiles](#guided-missiles-a-navigator-and-a-pilot-no-tactician)) is
within `missile_defense_time_s` of impact; its `target_id` is that missile's
controller id.

**`FighterNavigator.engage_target`** dispatches on that attack mode:
- **`PURSUIT`** — blends Constant Angle Pursuit (`compute_constant_angle_pursuit`
  aims at where the target will be, laterally, a second from now: it is fed
  the lateral part of `v_target − v_self`, the convention of
  `Interactions.rel_velocities[self, target]`), lead and lag pursuit with
  distance-dependent weights (`compute_engage_weights`, overlapping smooth
  steps), fires once aligned and in range, and can override pursuit to
  `reposition` (hard turn away before overshooting a closing target) or
  `extend` (break off a low-closing-speed "spiral of death"). For agile prey.
- **`STRAFE`** — a committed `ingress → attack → break → reposition` run on a
  slow or immobile target: press in firing, peel off at point-blank, extend,
  come around.
- **`BOMB`** — a committed `ingress → approach → run → break → reposition`
  cycle that overflies a slow/immobile target and drops a bomb from the belly
  (`-Z`). The ingress banks onto the target's track line; the approach and run
  fly belly-down along it (the pilot's up-reference makes the fighter roll only
  to level with that reference, like the capital ship).
  `compute_release_condition` treats the bomb as a straight (no-gravity)
  projectile at its launcher's `initial_velocity()` and releases when the
  flight-time-led intercept falls inside a cone of that velocity; the drop
  goes through the player's own `pawn.fire_secondary()`, with the selected
  secondary weapon (nothing is released if it is not a bomb).

Arming a weapon selects the launcher the tactician chose (while it has stock
left). Pursuit and strafe runs fire the guns, plus (`navigator.ordnance` in
the personality):
- a **missile** once locked (the lock builds while it is selected), within
  `missile_max_range_fraction` of its reach (launch speed × life time), and
  while fewer than `max_missiles_in_flight` of the bot's missiles already home
  on the target (read from its `incoming_missiles`);
- a **rocket** once the target is within gun range and the lead solution for
  the rocket's flight time is within `rocket_fire_min_cos_angle` of the nose.

**`DEFEND_MISSILE`** is a beam turn (`defend_missile`): full speed,
perpendicular to the missile's line of sight, on the side closest to the
heading. A fighter carrying flares also drops one per missile, at the think
the missile is within `flare_range_fraction` of its `decoy_range_m`
(`navigator.countermeasures`), where a flare may lure it.

**`MajorShipTactician`** is the fighter's list without threat evasion or
prey scoring: it engages a scripted prey (`scripted_prey_dict`) tagged
`AttackMode.ORBIT`. **`MajorShipNavigator`** orbits it: a constant standoff
off the nearest point of the target's oriented bounding box, driven
tangentially so the target stays abeam on the turret flank (a circle round a
compact target, a racetrack round a long one). **`MajorShipPilot`** only
yaws/pitches toward the target and rolls to stay level with the scene (no
roll-to-target).

## Tracking-mount trio: turrets and tractor beams

[`tracking_mount/`](../../src/space_flight/ai/tracking_mount/) is the AI for
anything that swivels in place — `Turret` and `TractorBeamProjector`, both
mounted subsystems of a capital ship (see
[Capital-ship subsystems](subsystems.md)):

- **`TrackingMountTactician`**: engage the best prey above
  `min_engagement_score`, otherwise `IDLE`. No evade/disengage/regroup — a
  mount can't flee.
- **`TrackingMountNavigator`** is purely an *aimer*: it computes a
  lead-pursuit direction and **publishes it onto the pawn**
  (`pawn.aim_direction`, `pawn.target_distance_m`). It doesn't know whether the
  mount will fire or grab; the pawn's own per-frame logic reads the solution
  and decides.
- **`TrackingMountPilot`** runs yaw/pitch PID loops against the mount's
  *base* axes (`base_right`/`base_forward`/`base_up`, the socket it's bolted
  into), since a mount's yaw/pitch are relative to its mounting.

Both mount kinds share this trio; `Personality.TRACTOR_BEAM_DEFAULT` only adds
a `tractor_beam` section for grab timing (see
[`Bot.__init__`](../../src/space_flight/actors/bot.py)).

## Guided missiles: a navigator and a pilot, no tactician

A missile's intent is always to engage the target its launcher gave it (the
launching ship's target, only if the launcher's missile lock held, see
[`TargetLock`](#targetlock)), so it has no tactician. Its
[`MissileNavigator`](../../src/space_flight/ai/missile/missile_navigator.py)
does constant-angle pursuit of that target at the missile's (constant) speed,
and returns a zero direction once the target is lost (destroyed or gone from
`Interactions`): the missile then drops its guidance and flies straight on. It
is flown by an ordinary `FighterPilot` with `Personality.MISSILE_DEFAULT`,
every frame (an `OrdnanceController` is not scheduled by the
`ThinkScheduler`). See [ordnance](actors.md#ordnance-bombs-rockets-missiles-flares).

While it homes, a missile keeps its target warned: the target pawn's
`incoming_missiles` dictionary holds an
[`IncomingMissile`](../../src/space_flight/ai/missile/incoming_missile.py)
message per missile (position, distance, closing speed, `time_to_impact_s`),
keyed by the missile's controller id, withdrawn once the missile is lost,
spent or decoyed. `nearest_incoming(pawn)` reads the nearest one: the bots'
missile defense and the player's [HUD](ui.md) use it. Only pawns get it (not
capital-ship subsystems).

## Supporting systems

### `TargetLock`

[`target_lock.py`](../../src/space_flight/ai/target_lock.py) locks onto the
parent's target once it has stayed inside a cone around the nose
(`interactions.alignments`) for a delay; anything else (no target, target
changed or gone, out of the cone) restarts the delay. `update()` runs once per
frame; `reset()` also forgets the target. Auto-aim owns one, and so does each
missile launcher, tuned by the missile's `lock_delay_s` and
`lock_cone_angle_deg` (see [ordnance](actors.md#ordnance-bombs-rockets-missiles-flares)).

### `AutoAim`

[`auto_aim.py`](../../src/space_flight/ai/auto_aim.py) is a per-shot
targeting assist for fighters and for turrets boosted by a living targeting
system (`Turret._apply_targeting_support`). It sits outside the pipeline:
driven from `Fighter.move()` / `Turret._operate()` and `LaserCannon.fire()`,
not `Bot`. Once its `TargetLock` holds (`target_lock_delay_s` in an
acquisition cone), `compute_shot_direction` aims each shot at
`predict_target_position()`, clamped to a maximum assist angle around the
barrel (a "nudge", not a snap); the cannon then adds its random shot deviation
(see [weapons](actors.md#weapons-and-munitions)). With `enabled` off, the
target is never locked (the crosshair never shows a lock) and shots go
straight ahead, but the lead is still computed for the lead indicator.
`configure()` is separate from `__init__` so a targeting system can retune a
turret's auto-aim at runtime.

Its tuning comes from the [gameplay settings](global_architecture.md#gameplay_settingspy--difficulty)
(`auto_aim_params`): the player's side for the player's fighter, the bots'
side for every other fighter and turret. A turret's targeting system
overrides whatever its own `auto_aim` config sets (the CR-90's lock delay and
assist angle), whatever the difficulty (a TODO in `Turret._auto_aim_params`);
only `enabled` always comes from the gameplay settings.

The predicted position is the target's current position plus a *lead offset*:
how far it moves during a bolt's time of flight (distance / `LASER_SPEED_MPS`)
at its velocity relative to the shooter, since bolts inherit the shooter's
velocity. `update_lead()` low-pass filters that offset once per frame
(`LEAD_SMOOTHING_TIME_S`), damping the velocity kicks of hits; filtering the
offset rather than the position keeps the lead on the target. The filter
restarts on a new target. The player's HUD shows the same point as its lead
indicator (see [docs/ui.md](ui.md#hudpy--heads-up-display)).

### `CollisionSensor` and `Formation`

[`collision_sensor.py`](../../src/space_flight/ai/collision_sensor.py) gives a
ship three overlapping look-ahead spheres, centred 5/50/125 m ahead of the nose
with radii 30/50/100 m by default; the outer ones can be disabled via
`active_range` (e.g. during a bomb run). Each contact adds a repulsion along
its surface normal, weighted by inverse distance; `navigate_avoidance` consumes
them when the bot thinks. The collision system records contacts
(`record_obstacle`, current frame only) right after each traversal, and
`set_active` takes the spheres out of the traversal on frames their bot won't
think — the full flow is in
[game.md](game.md#sensor-contacts-from-traversal-to-avoidance).

[`formation.py`](../../src/space_flight/ai/formation.py) is data, not logic:
`Formation` holds a named layout (`arrowhead`, `diamond`, `around_diamond`) of
scaled slot positions and the ids of the ships in them, leader first. Ships
find their slot via `pawn.formation.get_ship_index`; the station-keeping is
`GenericShipNavigator.formation`.

### `Interactions`

[`interactions.py`](../../src/space_flight/ai/interactions.py) is the
per-frame relationship cache every tactician/navigator/auto-aim reads instead
of recomputing pairwise geometry. For every pair of live actors it stores
distance, unit direction, relative velocity and forward alignment, and flags in
`interact` the pairs that can fight: different non-neutral teams within
`INTERACT_MAX_DISTANCE_M` (10 km). The diagonal is always zero. Actors occupy
stable pre-allocated slots (`add_actor`/`remove_actor`, `MAX_ACTORS = 64` by
default), so indices never shift and nothing is allocated per frame.
`update_interactions()` computes all live pairs at once with numpy and writes
them into the matrices in place (callers keep views), so cost scales with live
actors, not capacity. Gotcha: `live_actors` (and masks over it, or rows sliced
with `alive`) are compacted, so their positions are not the slot indices from
`get_actor_index_from_id`; translate via `np.where(alive)[0]`.

## Where things live

[`ai/`](../../src/space_flight/ai/): `generic/` holds the
tactician/navigator/pilot base classes, `fighter/`, `major_ship/` and
`tracking_mount/` each family's subclasses, `missile/` the missile navigator
and the incoming-missile message (`incoming_missile.py`),
and `__init__.py` the shared
`Personality`, `Intent` and `AttackMode`. `auto_aim.py`, `collision_sensor.py`,
`formation.py`, `interactions.py` and `think_scheduler.py` are the supporting
systems.
