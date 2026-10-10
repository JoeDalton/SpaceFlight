# Major-ship subsystems

Major ships (escort and capital ships) are not monolithic health bars: they
are built from **subsystems** — destructible modules bolted onto the hull
(shield generators, targeting systems, turrets, tractor beams, hangars;
engines are planned). Each is a target in its own right: knock out the shield
generators and the bubble drops; kill the targeting system and the turrets
lose their aim assist and fire-rate boost; destroy the turrets and the ship
stops shooting back; destroy a hangar and no more fighters launch from it.

All of the subsystem code lives in
[`src/space_flight/actors/major_ship/`](../../src/space_flight/actors/major_ship/).
This page is the guided tour; the per-class API is in the
[code reference](apidocs/index.rst).

## Mental model

- A **subsystem** is a [`SubSystem`](#the-subsystem-base) — a destructible chunk
  of a ship. It owns its health and a collider, is targetable, and explodes when
  killed. It is *mounted on* a ship and dies with it.
- Some subsystems are **passive** (they just exist and can be shot off — the
  planned engines). Others are **active** and change the ship's capabilities
  while alive: the shield generator projects a bubble, the targeting system
  boosts turrets, a turret shoots, a tractor beam grabs, a hangar launches
  fighters.
- Active subsystems are deliberately **loosely coupled**. A subsystem never
  reaches "up" to command the ship; instead the ship (or its turrets) *pull* what
  they need each frame and check the subsystem's alive/dead state. So killing a
  subsystem needs no teardown wiring — the capability simply stops being pulled.

## The `SubSystem` base

[`sub_system.py`](../../src/space_flight/actors/major_ship/sub_system.py) defines
the behaviour every subsystem shares:

- **Destructible.** It owns a strength pool (`health` / `max_health`) and
  monitors it every frame. When depleted it plays a death explosion at its last
  location and is cleaned up centrally.
- **Mounted.** Its node hangs off the ship node at a mounting offset.
  `mounted_on` is the ship it is bolted to (used to spare that ship from its
  own colliders and to route ram-pushback to it). For most subsystems `parent`
  *is* the ship; for the aiming mounts `parent` is the controlling Bot and
  `mounted_on` is passed explicitly.
- **Into-only collider.** A `"subsystem"` collider that is only ever *hit* —
  like terrain it never initiates collisions. A sphere of `hit_box_radius_m`
  by default, or a box when given `half_extents_m` (half-sizes along the ship
  axes, e.g. a hangar bay); `hit_box_radius_m` is then the box's bounding
  radius, wherever a size is read (AI standoffs, aim). Its `owner` tag points
  back at the subsystem so the collision handlers can route a laser hit to
  `take_hit`, and same-vehicle pairs are skipped so a ship never collides with
  its own parts.
- **Targetable.** It registers with the interaction system, so bots and the
  player can lock onto it individually.
- **Dies with its ship.** If the ship it is mounted on is gone, the subsystem
  zeroes its own health so it is cleaned up on the next frame.

| Subsystem | Class | Base | Role |
|-----------|-------|------|------|
| Engine | `Engine` | `SubSystem` | Unused stub (future engine module) |
| Hangar | `Hangar` | `SubSystem` | Launches fighter bots on request (box collider) |
| Tractor beam mount (stub) | `TractorBeamProjector` | `SubSystem` | Placeholder hull module (see note below) |
| Shield generator | `ShieldGenerator` | `SubSystem` | Projects a protective shield bubble |
| Targeting system | `TargetingSystem` | `SubSystem` | Grants turrets auto-aim + faster fire |
| Tracking mount | `TrackingMount` | `SubSystem` | Base for turrets/tractor beams that swivel to aim |
| Turret | `Turret` | `TrackingMount` | Aims and fires laser cannons |
| Tractor beam | `TractorBeamProjector` | `TrackingMount` | Aims, grabs a prey and reels it in |

## Passive module: engine

[`Engine`](../../src/space_flight/actors/major_ship/engine.py) is an unused
stub: a bare `SubSystem` with no behaviour or visual, taking only
`(game, parent)`. `MajorShip` never spawns it.

## Hangar

A [`Hangar`](../../src/space_flight/actors/major_ship/hangar.py) is a bay
launching fighter bots on request (launch only: launched fighters never come
back). `MajorShip` builds one per entry of the `hangars` config key, so escort
and capital ships alike may carry them; the star destroyer has one ventral bay.

- **The bay** is a box collider (`relative_position` = its centre,
  `half_extents_m` along the ship axes) with a placeholder box visual. Ships
  ramming it are pushed back like off any subsystem; lasers damage it.
- **Stock.** What a hangar holds is up to the level, not the ship config: the
  level module defines a dictionary of fighters per type (e.g.
  `{"tie-fighter": 12, "tie-bomber": 6}`) and passes it with
  `set_stock(stock)` once the ship exists. The dictionary is copied; unknown
  ship types and negative counts are refused. A hangar holds nothing until
  stocked.
- **Requests.** `launch(fighter_type, count=None, on_launched=None,
  primary_target_ids=())` queues a `LaunchOrder` of `count` fighters
  (`group_size` by default) of `fighter_type`, filled one launch at a time
  behind any earlier request; the order records the launched pawn ids and is
  `done` once filled or cancelled. A type not in the stock raises
  (`KeyError`); a request for a type whose stock is empty, or to a hangar
  that cannot launch, does nothing (it comes back already cancelled).
- **Launching** (its per-frame `update`): one fighter every
  `launch_interval_s`, of the order's type, as a fighter `Bot` of
  the ship's team (read at launch). It appears at `launch_point`: just outside
  the box face `launch_direction` points out of, its collision sphere clear of
  the box by `launch_margin_m`, nose first along `launch_direction` (its top
  toward the ship axis the most across it, the bow for a ventral bay: its
  thrust then carries it away from the bay rather than along it), with the
  ship's velocity plus `launch_speed_mps` along `launch_direction`. The ship's own
  hull sphere must leave that point outside (the star destroyer's is kept
  small for that). Each order's fighters fly in a `formation` (the first one
  out leads; a full formation starts a new one) and get its primary targets.
- **Limits.** A launch waits while `max_active` of the hangar's fighters are
  alive, or while no more than `HANGAR_ACTOR_SLOT_RESERVE` interaction slots
  are free (see [ai.md](ai.md)). Each launch spends one fighter of its type's
  stock; once a type is spent, what is left of its request is cancelled and
  the next request goes on.
- **Destruction.** Once the hangar or its ship is destroyed (or dying), its
  queued orders are cancelled and new requests are refused. Fighters already
  out fight on.
- Launched fighters are independent bots: a later `set_team` on the ship does
  not reach them.

## Shield generator & shield

A ship may mount **several**
[`ShieldGenerator`](../../src/space_flight/actors/major_ship/shield_generator.py)s
(or **none**), and they all project **one shared**
[`Shield`](../../src/space_flight/actors/major_ship/shield.py), built and
owned by the ship. The generators are the *hardware*, the shield the *effect*:
a ship with no generators gets no shield (a stray `shield` spec on it is
ignored, with a warning).

- **Pro-rata perks.** With `initial` generators and `alive` still standing,
  the fraction `alive / initial` scales both the maximum strength and the
  regeneration rate, and the current strength is scaled by the same ratio as
  the maximum (a partly depleted shield loses the same proportion). Shooting
  off one of three generators leaves the shield at two-thirds strength; this
  is recomputed every frame. `get_shield_level()` reads 0 once the shield's
  final death has begun.
- **One-way coupling.** The shield polls the generators' alive state; the
  generators know nothing of the shield and stay plain destructible hardware.
  The shield's `get_shield_level()` (its current strength) feeds the fleet
  AI's fighting-shape estimate.

The shield has **two distinct failure modes**:

- **Disabled** — its own strength pool is depleted by hits. The bubble
  collapses (the fluid *death* animation) and stays *down*: not protecting,
  hidden, but still alive. After a regeneration cooldown it strengthens again
  and *reappears* (the death animation played in reverse).
- **Destroyed** — **every** generator (or the whole ship) is destroyed. This is
  the only thing that ends the shield's life. It plays the same collapse and
  only *then* reports itself dead, so cleanup waits for the animation.

Key behaviours:

- **Not functional while animating.** During either animation the shield
  blocks nothing (`munition_into_shield` skips it); it only protects while
  fully *up*.
- **Regeneration cooldown.** Regeneration starts 10 s after the last absorbed
  hit, **doubled** (20 s) while the shield is down.
- **Direction-dependent absorption.** A munition fired from *outside* is
  absorbed; one fired from *inside* passes through, so a ship sheltering in the
  bubble can still shoot out (and at the hull). It is decided on the munition's
  launch point: `Shield.contains(point)` tells whether a world point lies
  inside the bubble as it is now. The point is first expressed in the shield's
  own frame (so the test follows the ship as it moves and turns), then:
  - **sphere**: within `radius_m` of the ship's origin;
  - **tube** (capsule): within `radius_m` of its axis segment, the nearest axis
    point being the point's projection on the axis, clamped between `point_a`
    and `point_b` (so past either end the test becomes the end cap's sphere);
  - **shared model**: never inside (no analytic shape; its baked one-sided
    polygons are only hit from outside anyway). Munition hits against a model
    bubble are still to be verified in game: no ship uses one yet.
- **Health-driven look.** The tint goes from light blue at full strength,
  through violet, to pink when empty; hits leave a localised flash of the same
  world size (`_IMPACT_RADIUS_M`, 20 m) on any bubble, a frigate's or a star
  destroyer's.

The **visuals are separated from the logic**: the mesh (sphere / capsule /
shared model), the animated shader and its uniforms, the impact flashes and the
fluid retraction live in
[`ShieldModel`](../../src/space_flight/actors/major_ship/shield_model.py)
(which also carries the `make_capsule` mesh builder for tube shields). `Shield`
keeps the game logic (strength, collision, lifecycle, the death/appearance
state machine) and drives the model each frame. The collider is built from the
dimensions the model resolved, so the visible bubble and the thing lasers hit
always coincide. Shader details: [shaders.md](shaders.md#shield-shaders).

### A note on cleanup timing

A destroyed shield must *finish its collapse* before it vanishes, so it keeps
reporting positive health to the central death handler until the animation
completes. Its node hangs off the ship node, which is removed when the ship
dies, so the shield detects its doom the same frame the last generator's or
the ship's health hits zero; when the *ship* is dying, it also reparents itself
to the world root so it can play out.

## Targeting system

The [`TargetingSystem`](../../src/space_flight/actors/major_ship/targeting_system.py)
is fire control: while alive it grants **every turret on the same ship**
auto-aim (shots lead the target, tuned by its `auto_aim` config over the bots'
[gameplay settings](global_architecture.md#gameplay_settingspy--difficulty),
see [`AutoAim`](ai.md#autoaim)) and a faster rate of fire
(`fire_rate_multiplier`). It only exposes those and its alive/dead
state; the turrets *pull* them each frame. Destroy it and on the next frame the
turrets revert to unassisted fire at their base rate.

## Tracking mounts: turrets & the tractor beam

A [`TrackingMount`](../../src/space_flight/actors/major_ship/tracking_mount.py) is a
subsystem that **swivels in yaw and pitch to track a target**: the shared base
of the laser turret and the tractor beam. Everything about *aiming* lives in the
mount — the mounting frame, the yaw/pitch state and rate limits, the swivelling
model, and the "remarkable directions" the AI reads — while what the mount
*does* once aimed is deferred to an `_operate()` hook.

A tracking mount is driven by a **Bot**: the Bot is its `parent` while
`mounted_on` is the ship it sits on. Its AI picks a prey and steers the barrel,
publishing a lead solution (`aim_direction`, `target_distance_m`) that
`_operate()` acts on. Its swivelling geometry is the
[`TurretModel`](../../src/space_flight/actors/major_ship/turret_model.py).

- **[`Turret`](../../src/space_flight/actors/major_ship/turret.py)** adds laser
  cannons and the fire decision: it fires when its barrel is aligned with where
  the prey is heading and the prey is in range, boosted by a living targeting
  system.
- **[`TractorBeamProjector`](../../src/space_flight/actors/major_ship/tractor_beam.py)**
  grabs a prey and reels it in. When a prey enters its grab cone within range it
  locks on and applies two forces each frame: a drag opposing the prey's
  velocity relative to the projector's ship, and a light attraction. The **cone
  acquires, range retains**: once locked it holds the prey until the grab times
  out, the prey wrenches free by exceeding a relative speed, leaves range, or is
  gone — after which a cooldown prevents an instant re-grab. Hardware specs
  come from its config, grab timing from `Personality.TRACTOR_BEAM_DEFAULT`.

> **Two `TractorBeamProjector`s.** Besides the functional tracking mount
> ([`tractor_beam.py`](../../src/space_flight/actors/major_ship/tractor_beam.py)),
> [`tractor_beam_projector.py`](../../src/space_flight/actors/major_ship/tractor_beam_projector.py)
> holds a bare, unused `SubSystem` stub of the same name. Use the
> tracking-mount version.

## Where things live

Every subsystem module, including the turret and tractor-beam mounts and their
`TurretModel`, sits under
[`src/space_flight/actors/major_ship/`](../../src/space_flight/actors/major_ship/).
