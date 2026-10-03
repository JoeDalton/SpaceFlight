# Actors

Every controllable or destructible thing in the game — the player's fighter,
enemy bots, capital ships and their turrets, laser shots — is built from a
small set of composable base classes. This page is the guided tour; the
per-class API is in the [code reference](apidocs/index.rst). The
capital-ship family (turrets, shields, tractor beams, ...) is detailed in
[Capital-ship subsystems](subsystems.md).

## Mental model

- A **Pawn** is anything that has a position, orientation and velocity and
  can be flown — a fighter or a capital ship (`Ship` subclasses `Pawn`). It
  is the physics/state half of an actor. A bot's controlled object is also
  called its pawn: for turrets and tractor beams that is a mounted
  `SubSystem` exposing the same attributes without inheriting `Pawn`.
- A **Bot** (or the **Player**) is the *controller*: it owns a pawn and,
  every frame, decides how to move it — either from AI (tactician →
  navigator → pilot) or from player input.
- A **Destructible** is anything with health that the central death handler
  tracks and can kill: bots, capital-ship subsystems and the shared shield.
  Ships take damage but are not destructibles: each is cleaned up by its
  owning bot/player as part of that owner's teardown.
- Rendering is kept separate from game logic: a `Ship` (state, physics,
  health) is paired with a `ShipModel` (the 3D model, purely presentation),
  the same split used for shields (`Shield`/`ShieldModel`) and tracking
  mounts (`TrackingMount`/`TurretModel`).

## `Pawn` — the base of anything flyable

[`pawn.py`](../../src/space_flight/actors/pawn.py) is the minimal shared state
of a controllable game element: an id, a team, a `parent` (its controller —
a `Bot` or the `Player`), the kinematic quantities every flying thing needs
(`position`, `speed`, `forward`/`right`/`up`), target-lock state read by the
auto-aim and AI, and the `mobility` / `shield_level` signals the AI reads to
size up a target. It carries no physics or rendering of its own.

## `Ship` — flight physics and state

[`ship.py`](../../src/space_flight/actors/ship.py) is a `Pawn` with a full
flight model. Its 10-variable state (position, orientation quaternion,
linear speed) is integrated by the game's central integrator; rotation rates
are directly-commanded inputs (player or AI), low-pass filtered to emulate
actuator delay. Two flight models are supported (`FLIGHT_MODEL`): `"space"`
(thrust only) and `"airplane"` (thrust, lift from angle of attack/side-slip,
and drag — viscous/wave plus lift-induced, the latter quadratic in the
(clipped) lift force).

Key responsibilities:
- **Per-ship-type configuration.** Mass, thrust, turn rates, drag/lift
  coefficients, `lift_inefficiency` (= 1/(π·AR·e), from wing aspect ratio and
  Oswald efficiency) and health come from that ship type's
  [`configuration.yaml`](../../src/space_flight/datafiles/models/ships/).
- **Throttle-dependent turn rate.** The commanded rates are scaled by
  `turn_rate_scale(throttle)`: a parabola from 50% of the max rates at idle,
  through 100% at 60% throttle (the fitted peak sits at about 56% throttle
  and is clipped to 100%), to 70% at full thrust, then a linear drop to
  10% at max boost (`THROTTLE_BOOST_VALUE`).
- **External forces**, accumulated separately from thrust/drag/lift:
  `impact_force_n` (each hit's force is removed after
  `DAMAGE_FORCE_APPLICATION_DURATION_S`, 0.1 s) and `external_force_n` (e.g.
  a tractor beam's pull, added via `apply_external_force` every frame it
  should act and zeroed by `compute_derivatives`).
- **Damage is ship-type dependent.** `apply_damage` and `ship_handle_health`
  are `NotImplementedError` stubs overridden by each concrete ship type.
- Owns its engine sound (interior loop for the player's cockpit, 3D-attached
  exterior loop for everyone else; none if its config has none) and its
  `ShipModel`.
- **Hooks for pawns that fly like ships but are not quite ships** (ordnance):
  `_load_configuration`, `_compute_max_speed_mps`, `_build_model`,
  `_build_damage_fx`, `_turn_rate_scale`, and `_compute_attitude_derivative`
  (the orientation derivative and body axes, shared by `compute_derivatives`).

`Ship` has two concrete subclasses:

| Class | File | Role |
|-------|------|------|
| `Fighter` | [`fighter.py`](../../src/space_flight/actors/fighter.py) | Quick, manoeuvrable — forward cannons, auto-aim, its own regenerating shield |
| `CapitalShip` | [`capital_ship/__init__.py`](../../src/space_flight/actors/capital_ship/__init__.py) | Slow, heavy — built from mounted subsystems instead of built-in weapons |

### `Fighter`

Adds a self-contained regenerating shield (damage drains the shield before
health), a `LaserCannon`, `AutoAim` for target leading, and one
`OrdnanceLauncher` per entry of its config's `loadout`
(`{ordnance_name: count}`, see [ordnance](#ordnance-bombs-rockets-missiles-flares)).
Its collision sphere is sized from `hit_box_radius_m` in its config.

Ordnance is used the same way by the player and the AI, through the
*selected secondary* weapon (`selected_secondary`, a bomb, rocket or missile
launcher with stock left): `cycle_secondary` selects the next one in loadout
order, looping, and `fire_secondary` launches it, then moves on once it is
spent. A missile gets the current target only while auto-aim is locked on it.
Flares have their own trigger, `drop_flare`, from the loadout's flare launcher
(`flare_launcher`).

### `CapitalShip`

Has **no built-in weapons or shield of its own**; it assembles itself from
the `sub_systems` declared in its config:
- **Shield generators**, owned directly, feeding a single shared `Shield`
  (no generators means no shield; see [subsystems.md](subsystems.md)).
- **Targeting systems**, likewise owned directly.
- **Turrets and tractor beams**, spawned as their own `Bot`s
  (`_spawn_mounted_bots`) whose pawn is mounted on this ship. They die on
  their own once the ship dies (`mounted_on.is_dead`), so
  `CapitalShip.clean()` only drops its references to them.

Damage goes straight to hull health; the shared shield, if any, absorbs hits
separately via the collision system.

## `ShipModel` — the presentation half

[`ship_model.py`](../../src/space_flight/actors/ship_model.py) loads the 3D
model (cockpit or exterior) for a given `ship_type`, with a per-type
offset/orientation/scale, and parents it to the ship node. It knows nothing
about physics or health: `Ship` moves that node each frame.

## Weapons and munitions

[`weapons/__init__.py`](../../src/space_flight/weapons/__init__.py) holds two
base classes the concrete weapons share:

- **`Weapon`** — the emitter (`parent`/`parent_node`), a reload gate
  (`fire_delay` + `_ready_to_fire`, an atomic check-and-consume so a weapon
  cannot fire faster than its rate), and the munition-spawn call. Subclasses
  define the trigger itself.
- **`Munition`** — the whole projectile lifecycle of a laser shot: identity,
  damage, emitter, world velocity, a straight-line coast for its lifetime,
  registration in `game.game_objects`, and a timed self-clean. It exposes the
  interface the collision handlers read (`origin_ship`/`origin_ship_id`/
  `power`/`speed`, `on_impact()`/`impact_position()`), which ordnance exposes
  too. Subclasses fill in only `_build_visual` and `_attach_collider`, plus an
  optional `_clean_extra`.

**`LaserCannon` / `LaserShot`**
([`weapons/laser_cannon.py`](../../src/space_flight/weapons/laser_cannon.py))
fires a ship's configured cannon positions in round-robin, rate-limited by
`laser_fire_rate`. It uses the parent's `AutoAim` for shot leading if
present, otherwise fires along the parent's forward vector plus its own
velocity. Each `LaserShot` renders as an analytic capsule impostor (see
[shaders.md](shaders.md)), with a collision segment long enough to bridge
one frame's travel and an optional point light behind the global
`EMIT_LASER_LIGHT` toggle.

### Ordnance: bombs, rockets, missiles, flares

All four share the same code; they differ only by their configuration,
[`datafiles/models/ordnance/<name>/configuration.yaml`](../../src/space_flight/datafiles/models/ordnance/):
`type` (`bomb`/`rocket`/`missile`/`flare`), `life_time_s`, `damage` and
`damage_type` (`physical` only for now), `reload_s`, the launch
(`launch_direction` — `forward`, `down` or `backward` — `speed_mps` relative to
the launching ship, `launch_offset_m`), the placeholder look and collision
(`visual_radius_m`, `collision_radius_m`, RGBA `color`) and, for missiles, the
turn rates.

- **`OrdnanceLauncher`**
  ([`weapons/ordnance_launcher.py`](../../src/space_flight/weapons/ordnance_launcher.py))
  holds a limited `stock` and a reload gate, and is the single source of the
  launch properties: `initial_velocity()` is the ship's velocity plus
  `speed_mps` along the launch direction — read by the bomb-run release solver
  as well. `launch(target_id)` spends one unit only on an actual launch, and
  only a missile keeps the target.
- **`Ordnance`** ([`actors/ordnance.py`](../../src/space_flight/actors/ordnance.py))
  is a `Ship` flying at a constant speed: its velocity is frozen in its body
  axes (no engine, no aerodynamics), so it flies straight unless it turns —
  which only a guided missile does, its velocity turning with it. Its pilot's
  rates still go through `Ship.set_inputs`. Toward the collision handlers it is
  a munition (`origin_ship`, `power`, `on_impact()`...). Its look is a
  coloured sphere (`build_ordnance_sphere`).
- **`OrdnanceController`** (same file) flies it for its life, then removes
  it — at once on impact too, silently (no explosion, no smoke), through the
  `Destructible` death handling. It is not a `Bot`: a missile has no tactician
  (it always engages the target its launcher gave it), and ordnance is not
  registered in `Interactions` (not targetable, and kept off its 64 slots).
  A missile with a target is steered by a
  [`MissileNavigator`](../../src/space_flight/ai/missile/missile_navigator.py)
  (constant-angle pursuit) and a `FighterPilot`
  (`Personality.MISSILE_DEFAULT`); everything else — and a missile whose target
  is lost — flies straight on.

Flares are decoys: they only stop other ordnance (both are spent), never
each other, and never their own team's ordnance (see [Game](game.md)).

## `Destructible` and `Destructibles` — central death handling

[`destructibles.py`](../../src/space_flight/actors/destructibles.py) is the
generic "has health, dies, gets cleaned up" contract, independent of the
`Pawn`/`Ship` hierarchy:

- **`Destructible`** registers itself with the game's single
  `Destructibles` tracker on construction. Subclasses implement
  `get_health`, `play_death` and `clean`.
- Death is a **timed phase**. Each object composes a `DyingPhase` (see
  below) and exposes overridable hooks:
  - `begin_death()` — entered once when `get_health()` first hits zero: kick
    off the death animation (spin, cut engines, smoke, drop out of
    targeting, ...).
  - `update_death()` — polled each frame while dying; returns `True` once the
    phase has lasted `death_duration_s` (default `0`: reaped the same frame).
  - `finish_death()` — the terminal effect, defaulting to `play_death`.
- **`Destructibles`** runs once per frame: it moves objects whose health has
  reached zero into a *dying* list (calling `begin_death`), advances every
  dying object (`update_death`), and only when one reports finished does it
  fire `finish_death`, clear its tasks and clean it up. So a killed ship can
  spin out of control for a few seconds — still collidable — before it
  explodes and is removed. Objects already cleaned out-of-band (e.g. a turret
  pawn whose `Bot` cleaned it first) are skipped.

The dying-phase *timer* is **`DyingPhase`** in
[`utils/state_machine.py`](../../src/space_flight/utils/state_machine.py):
an is-dying flag plus an injected, pause-aware clock, exposing `begin()` /
`elapsed_s()` / `finished(duration_s)`. It carries no policy, so both
`Destructible` and the non-Destructible `Player` compose it. The spin-out
itself lives on `Ship` (`begin_tumble` / `tumble_step`, a √time-ramped
body-rate about a random axis) and its smoke/fire trail in
[`DamageFX`](fx.md). A mounted `SubSystem` cannot tumble: a standalone one
(shield generator, targeting system — its `parent` is the ship it's
`mounted_on`) smokes for `SUBSYSTEM_DEATH_SMOKE_DURATION_S` (0.6 s) before
exploding, while a bot-controlled mount (turret, tractor beam) explodes
immediately.

## `Bot` — the AI controller

[`bot.py`](../../src/space_flight/actors/bot.py) is a `Destructible` that owns
a pawn and drives it via the tactician → navigator → pilot pipeline (see
[AI](ai.md)). The pawn moves every frame, but the bot only *thinks* a few
times a second, on a frame balanced against the other bots (see
[When a bot thinks](ai.md#when-a-bot-thinks)). `bot_type` selects both the
pawn class and the matching AI trio:

| `bot_type` | Pawn | AI trio |
|------------|------|---------|
| `"fighter"` | `Fighter` | `FighterTactician` / `FighterNavigator` / `FighterPilot` |
| `"capital_ship"` | `CapitalShip` | `CapitalShipTactician` / `CapitalShipNavigator` / `CapitalShipPilot` |
| `"turret"` | `Turret` (subsystem, mounted via `parent_object`) | `TrackingMountTactician` / `...Navigator` / `...Pilot` |
| `"tractor_beam"` | `TractorBeamProjector` (subsystem) | Same tracking-mount trio, with `Personality.TRACTOR_BEAM_DEFAULT` |

A turret or tractor-beam pawn is a subsystem *mounted on* another ship
(`parent_object`) that has already registered itself with the interaction
system, so `Bot` skips the duplicate registration.

`move_bot_task` differs by `bot_type` only in the navigator/pilot I/O: for
ships, a direction plus desired speed becomes `throttle`/yaw/pitch/roll (with
the navigator's optional up-reference); for tracking mounts, a direction
becomes just yaw/pitch, and the navigator runs every frame (only the pilot
waits for a think). While the bot is dying it skips the AI entirely and
drives the pawn's tumble instead.

## `Player` — the human-controlled equivalent of a `Bot`

[`player.py`](../../src/space_flight/actors/player.py) plays the same role as
`Bot` for the user's own ship (always a `Fighter`, with a cockpit model), plus
everything specific to being watched by a human:

- **Camera rig.** A jolt/pivot node hierarchy anchors the camera to the
  ship, driven by a damped spring model (`compute_head_acceleration` /
  `compute_head_position`) so the head reacts to acceleration, impacts and
  roll rate, plus the player's free-look input.
- **Targeting.** `open_radial_target_menu` pushes a `RadialMenuState` over
  `TARGET_FILTERS` (All, Enemies, Capital ships, Subsystems, Turrets,
  Fighters, Waypoints, plus an empty slot); the chosen label becomes
  `target_filter` (empty slot or no selection means All). `loop_target(±1)`
  (cycle) and `point_target` (best nearby, forward target) both build
  `target_mask` over `interactions.live_actors` via `update_target_mask`:
  "All" excludes waypoint markers, "Enemies" uses the player's `interact`
  row, "Turrets" matches `isinstance(actor, Turret)`, and the other filters
  match the actor's `category`. Turrets have `category="sub_system"`, so they
  show under both Subsystems and Turrets; an unknown filter matches nothing.
- **Optional AI passenger.** `has_ai=True` gives the player the same
  fighter trio a `Bot` uses, letting the ship fly itself (all current levels
  pass `has_ai=False`).
- **State recording** for offline analysis (`record_state`), gated by the
  `RECORD_GAME` flag.

`Player` is not a `Destructible`: the player's death ends the level rather
than being cleaned up mid-session. It still plays the same spin-out: it
composes a `DyingPhase` and, while dying, hands control (camera included) to
the pawn's tumble until `death_spin_finished()`, when `FlightState` shows the
level-end screen.

## `Trihedron`

[`trihedron.py`](../../src/space_flight/actors/trihedron.py) is a debug
helper that attaches a scaled coordinate-axis gizmo to a node, always drawn
on top. Not part of the gameplay hierarchy.

## Where things live

`Pawn`, `Ship`/`ShipModel`, `Fighter`, `Bot`, `Player`, `Destructible(s)`
and `Trihedron` live under
[`src/space_flight/actors/`](../../src/space_flight/actors/) (beside
`scan.py`, the mission scan state, see [Game](game.md));
`Weapon`/`Munition`, `LaserCannon`/`LaserShot` and `OrdnanceLauncher`
under [`src/space_flight/weapons/`](../../src/space_flight/weapons/) (the
`Ordnance` pawn and its controller in `actors/ordnance.py`);
`CapitalShip` and everything it is built from under
[`actors/capital_ship/`](../../src/space_flight/actors/capital_ship/) (see
[Capital-ship subsystems](subsystems.md)).
