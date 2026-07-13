# Actors

Every controllable or destructible thing in the game — the player's fighter,
enemy bots, capital ships and their turrets, laser shots — is built from a
small set of composable base classes. This page is the guided tour of how
they fit together; the per-class API (constructor arguments, methods) is
generated from the docstrings in the [code reference](docs/).

Most of the code lives in
[`src/space_flight/actors/`](../src/space_flight/actors/), with the
capital-ship-specific subsystems (turrets, shields, tractor beams, ...) under
[`actors/capital_ship/`](../src/space_flight/actors/capital_ship/) — see
[Capital-ship subsystems](subsystems.md) for that family in detail.

## Mental model

- A **Pawn** is anything that has a position, orientation and velocity and
  can be flown — a fighter, a capital ship, a turret. It is the physics/state
  half of an actor.
- A **Bot** (or the **Player**) is the *controller*: it owns a pawn and,
  every frame, decides how to move it — either from AI (tactician →
  navigator → pilot) or from player input.
- A **Destructible** is anything with health that the central death handler
  tracks and can kill. Bots (and capital-ship subsystems) are destructibles;
  ships take damage but are cleaned up by their owning bot/player rather than
  registering themselves.
- Rendering is kept separate from game logic: a `Ship` (state, physics,
  health) is paired with a `ShipModel` (the 3D model, purely presentation),
  the same split used for shields (`Shield`/`ShieldModel`) and tracking
  mounts (`TrackingMount`/`TurretModel`).

## `Pawn` — the base of anything flyable

[`pawn.py`](../src/space_flight/actors/pawn.py) is the minimal shared state
of a controllable game element: an id, a team, a `parent` (its controller —
a `Bot` or the `Player`), and the kinematic quantities every flying thing
needs (`position`, `speed`, `forward`/`right`/`up`, plus target-lock state
read by the auto-aim and AI). It carries no physics or rendering of its own;
`Ship` builds on top of it.

## `Ship` — flight physics and state

[`ship.py`](../src/space_flight/actors/ship.py) is a `Pawn` with a full
flight model. Its 10-variable state (position, orientation quaternion,
linear speed) is integrated by the game's central integrator; rotation rates
are treated as directly-commanded inputs (from player input or AI), passed
through a low-pass filter to emulate physical actuator delay. Two flight
models are supported (`FLIGHT_MODEL`): `"space"` (thrust only) and
`"airplane"` (thrust, drag, lift from angle of attack/side-slip).

Key responsibilities:
- **Per-ship-type configuration.** Mass, thrust, turn rates, drag/lift
  coefficients and health all come from that ship type's
  [`configuration.yaml`](../src/space_flight/datafiles/models/ships/).
- **External forces.** `impact_force_n` (from hits, decayed after a fixed
  duration) and `external_force_n` (e.g. a tractor beam's pull, re-applied
  every frame it should act and zeroed otherwise by `compute_derivatives`)
  are accumulated separately from thrust/drag/lift.
- **Damage is deferred.** `apply_damage` and `ship_handle_health` are
  `NotImplementedError` stubs — each concrete ship type defines how damage
  interacts with its own health/shield.
- Owns its engine sound (interior loop for the player's cockpit, 3D-attached
  exterior loop for everyone else) and its `ShipModel`.

`Ship` has two concrete subclasses:

| Class | File | Role |
|-------|------|------|
| `Fighter` | [`fighter.py`](../src/space_flight/actors/fighter.py) | Quick, manoeuvrable — forward cannons, auto-aim, its own regenerating shield |
| `CapitalShip` | [`capital_ship/__init__.py`](../src/space_flight/actors/capital_ship/__init__.py) | Slow, heavy — built from mounted subsystems instead of built-in weapons |

### `Fighter`

Adds a self-contained regenerating shield (damage drains the shield before
health), a `LaserCannon`, a `BombLauncher` fed from a limited `bomb_supply`
(`drop_bomb` spends one unit per release), and `AutoAim` for target leading.
Its collision sphere is sized from `hit_box_radius_m` in its config.

### `CapitalShip`

Has **no built-in weapons or shield of its own** — instead it assembles
itself from `sub_systems` declared in its config:
- **Shield generators** it owns directly and feeds into a single shared
  `Shield` (see [subsystems.md](subsystems.md) — no generators means no
  shield).
- **Targeting systems**, likewise owned directly.
- **Turrets and tractor beams**, which are not owned directly but spawned as
  their own `Bot`s (`_spawn_mounted_bots`) whose pawn is mounted on this
  ship — they have their own tracking AI and die on their own once the ship
  dies (`mounted_on.is_dead`), so `CapitalShip.clean()` only drops its
  references to them rather than tearing them down itself.

Damage goes straight to hull health (no self-shield); the shared shield, if
any, absorbs hits separately via the collision system.

## `ShipModel` — the presentation half

[`ship_model.py`](../src/space_flight/actors/ship_model.py) loads and
positions the 3D model (cockpit or exterior) for a given `ship_type`, with
per-type offset/orientation/scale tables. It knows nothing about physics or
health — `Ship` drives its position/orientation each frame by moving the
node it's parented to.

## Weapons and munitions

[`weapon.py`](../src/space_flight/actors/weapon.py) holds two base classes the
concrete weapons share:

- **`Weapon`** — the emitter (`parent`/`parent_node`), a reload gate
  (`fire_delay` + `_ready_to_fire`, an atomic check-and-consume so a weapon
  cannot fire faster than its rate), and the munition-spawn call. Subclasses
  define the trigger itself.
- **`Munition`** — the whole projectile lifecycle: identity, damage, emitter,
  world velocity, a straight-line coast for its lifetime, registration in
  `game.game_objects`, and a timed self-clean. It exposes the interface the
  collision handlers read (`origin_ship`/`origin_ship_id`/`power`/`speed`/
  `shot`). Subclasses fill in only two hooks — `_build_visual` and
  `_attach_collider` — plus an optional `_clean_extra`.

**`LaserCannon` / `LaserShot`**
([`laser_cannon.py`](../src/space_flight/actors/laser_cannon.py)) fires one of
a ship's configured cannon positions in round-robin, rate-limited by
`laser_fire_rate`. It defers to the parent's `AutoAim` for shot leading if
present, otherwise fires straight down the parent's forward vector plus its
own velocity. Each `LaserShot` is a camera-facing quad billboard with a point
light and a collision segment (long enough to bridge one frame's travel at
laser speed).

**`BombLauncher` / `Bomb`**
([`bomb_launcher.py`](../src/space_flight/actors/bomb_launcher.py)) drops a
bomb along the ship's belly (`-Z`) at `BOMB_SPEED_MPS` plus the ship's
inherited velocity, rate-limited by a reload delay; `launch()` returns whether
a bomb was actually released so the fighter only spends supply on a real drop.
Each `Bomb` is a slow pink sphere with a small collision sphere, and reuses the
laser collision-damage handlers through the shared munition interface.

## `Destructible` and `Destructibles` — central death handling

[`destructibles.py`](../src/space_flight/actors/destructibles.py) is the
generic "has health, dies, gets cleaned up" contract, independent of the
`Pawn`/`Ship` hierarchy:

- **`Destructible`** registers itself with the game's single
  `Destructibles` tracker on construction. Subclasses implement
  `get_health`, `play_death` and `clean`.
- **`Destructibles`** runs once per frame: it partitions tracked objects into
  still-alive and newly-dead by `get_health() <= 0.0`, then for each
  newly-dead object plays its death animation, clears its tasks and cleans
  it up — all in one central sweep, so individual actors never need to poll
  their own death.

`Bot` and every capital-ship `SubSystem` are `Destructible`s. A `Ship` itself
is not — it's cleaned up by whichever `Bot`/`Player` owns it as part of that
owner's own teardown, rather than being tracked independently.

## `Bot` — the AI controller

[`bot.py`](../src/space_flight/actors/bot.py) is a `Destructible` that owns
a pawn and drives it every frame via the tactician → navigator → pilot
pipeline (see the [`ai`](../src/space_flight/ai/) package). `bot_type`
selects both the pawn class and the matching AI trio:

| `bot_type` | Pawn | AI trio |
|------------|------|---------|
| `"fighter"` | `Fighter` | `FighterTactician` / `FighterNavigator` / `FighterPilot` |
| `"capital_ship"` | `CapitalShip` | `CapitalShipTactician` / `CapitalShipNavigator` / `CapitalShipPilot` |
| `"turret"` | `Turret` (subsystem, mounted via `parent_object`) | `TrackingMountTactician` / `...Navigator` / `...Pilot` |
| `"tractor_beam"` | `TractorBeamProjector` (subsystem) | Same tracking-mount trio, with `Personality.TRACTOR_BEAM_DEFAULT` |

A turret or tractor-beam bot doesn't fly a free-standing ship: its pawn is a
subsystem *mounted on* another ship (`parent_object`), and the pawn may
already have registered itself with the interaction system, so `Bot` skips
the duplicate registration if it finds one.

`move_bot_task` branches on `bot_type` only in the shape of the pilot's
output (`throttle`/yaw/pitch/roll for free-flying pawns vs. just yaw/pitch
for tracking mounts) — the tactician→navigator→pilot call pattern is
otherwise identical.

## `Player` — the human-controlled equivalent of a `Bot`

[`player.py`](../src/space_flight/actors/player.py) plays the same role as
`Bot` for the user's own ship (always a `Fighter`, with a cockpit model), but
adds everything specific to being watched by a human:

- **Camera rig.** A jolt/pivot node hierarchy anchors the camera to the
  ship, driven by a damped spring model (`compute_head_acceleration` /
  `compute_head_position`) so the head reacts to acceleration, impacts and
  roll rate, plus the player's free-look input.
- **Targeting.** `loop_target` (cycle) and `point_target` (auto-pick the
  closest, most-forward valid target) both build a `target_mask` from
  `target_filter` (All / Enemies / Waypoints / ...) via
  `update_target_mask`, then hand off to `set_target_from_actor_index`.
- **Optional AI passenger.** `has_ai=True` gives the player the same
  tactician/navigator/pilot trio a `Bot` would use, letting the "player" ship
  fly itself (used for demos/recording).
- **State recording** for offline analysis (`record_state`), gated by the
  `RECORD_GAME` flag.

Unlike `Bot`, `Player` is not a `Destructible` — the player's ship dying ends
the game rather than being cleaned up mid-session.

## `Trihedron`

[`trihedron.py`](../src/space_flight/actors/trihedron.py) is a tiny debug
helper: it attaches a scaled coordinate-axis gizmo to a node, always drawn on
top. Not part of the gameplay actor hierarchy — a visualisation aid only.

## Where things live

`Pawn`, `Ship`/`ShipModel`, `Fighter`, `Weapon`/`Munition` (with
`LaserCannon`/`LaserShot` and `BombLauncher`/`Bomb`), `Bot`, `Player`,
`Destructible(s)` and `Trihedron` live directly under
[`src/space_flight/actors/`](../src/space_flight/actors/). `CapitalShip`
and everything it's built from (subsystems, shields, tracking mounts,
turrets, tractor beams) live under
[`actors/capital_ship/`](../src/space_flight/actors/capital_ship/) — see
[Capital-ship subsystems](subsystems.md) for that part of the tree. The
auto-generated [code reference](docs/) has the full per-class API.
