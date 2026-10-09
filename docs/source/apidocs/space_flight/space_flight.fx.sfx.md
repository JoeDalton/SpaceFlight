# {py:mod}`space_flight.fx.sfx`

```{py:module} space_flight.fx.sfx
```

```{autodoc2-docstring} space_flight.fx.sfx
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`PhysicsAudio3DManager <space_flight.fx.sfx.PhysicsAudio3DManager>`
  - ```{autodoc2-docstring} space_flight.fx.sfx.PhysicsAudio3DManager
    :summary:
    ```
* - {py:obj}`SFX <space_flight.fx.sfx.SFX>`
  - ```{autodoc2-docstring} space_flight.fx.sfx.SFX
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_velocity_of <space_flight.fx.sfx._velocity_of>`
  - ```{autodoc2-docstring} space_flight.fx.sfx._velocity_of
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LOGGER <space_flight.fx.sfx.LOGGER>`
  - ```{autodoc2-docstring} space_flight.fx.sfx.LOGGER
    :summary:
    ```
* - {py:obj}`SOUND_VOLUME_REFERENCE_DISTANCE_M <space_flight.fx.sfx.SOUND_VOLUME_REFERENCE_DISTANCE_M>`
  - ```{autodoc2-docstring} space_flight.fx.sfx.SOUND_VOLUME_REFERENCE_DISTANCE_M
    :summary:
    ```
* - {py:obj}`MAX_SOUND_DISTANCE_M <space_flight.fx.sfx.MAX_SOUND_DISTANCE_M>`
  - ```{autodoc2-docstring} space_flight.fx.sfx.MAX_SOUND_DISTANCE_M
    :summary:
    ```
* - {py:obj}`SFX_MAX_SOUND_DURATION_S <space_flight.fx.sfx.SFX_MAX_SOUND_DURATION_S>`
  - ```{autodoc2-docstring} space_flight.fx.sfx.SFX_MAX_SOUND_DURATION_S
    :summary:
    ```
* - {py:obj}`TERRAIN_HIT_SOUND_MULTIPLIER <space_flight.fx.sfx.TERRAIN_HIT_SOUND_MULTIPLIER>`
  - ```{autodoc2-docstring} space_flight.fx.sfx.TERRAIN_HIT_SOUND_MULTIPLIER
    :summary:
    ```
* - {py:obj}`TARGET_HIT_SOUND_MULTIPLIER <space_flight.fx.sfx.TARGET_HIT_SOUND_MULTIPLIER>`
  - ```{autodoc2-docstring} space_flight.fx.sfx.TARGET_HIT_SOUND_MULTIPLIER
    :summary:
    ```
* - {py:obj}`PLAYER_HIT_SOUND_MULTIPLIER <space_flight.fx.sfx.PLAYER_HIT_SOUND_MULTIPLIER>`
  - ```{autodoc2-docstring} space_flight.fx.sfx.PLAYER_HIT_SOUND_MULTIPLIER
    :summary:
    ```
* - {py:obj}`PLAYER_CANNON_FIRE_VOLUME <space_flight.fx.sfx.PLAYER_CANNON_FIRE_VOLUME>`
  - ```{autodoc2-docstring} space_flight.fx.sfx.PLAYER_CANNON_FIRE_VOLUME
    :summary:
    ```
* - {py:obj}`NPC_CANNON_FIRE_VOLUME <space_flight.fx.sfx.NPC_CANNON_FIRE_VOLUME>`
  - ```{autodoc2-docstring} space_flight.fx.sfx.NPC_CANNON_FIRE_VOLUME
    :summary:
    ```
* - {py:obj}`PLAYER_DISTANT_IMPACT_VOLUME <space_flight.fx.sfx.PLAYER_DISTANT_IMPACT_VOLUME>`
  - ```{autodoc2-docstring} space_flight.fx.sfx.PLAYER_DISTANT_IMPACT_VOLUME
    :summary:
    ```
* - {py:obj}`NPC_DISTANT_IMPACT_VOLUME <space_flight.fx.sfx.NPC_DISTANT_IMPACT_VOLUME>`
  - ```{autodoc2-docstring} space_flight.fx.sfx.NPC_DISTANT_IMPACT_VOLUME
    :summary:
    ```
* - {py:obj}`SOUND_POOL_LENGTH <space_flight.fx.sfx.SOUND_POOL_LENGTH>`
  - ```{autodoc2-docstring} space_flight.fx.sfx.SOUND_POOL_LENGTH
    :summary:
    ```
* - {py:obj}`DISTANCE_FACTOR <space_flight.fx.sfx.DISTANCE_FACTOR>`
  - ```{autodoc2-docstring} space_flight.fx.sfx.DISTANCE_FACTOR
    :summary:
    ```
* - {py:obj}`DOPPLER_FACTOR <space_flight.fx.sfx.DOPPLER_FACTOR>`
  - ```{autodoc2-docstring} space_flight.fx.sfx.DOPPLER_FACTOR
    :summary:
    ```
````

### API

````{py:data} LOGGER
:canonical: space_flight.fx.sfx.LOGGER
:value: >
   'getLogger(...)'

```{autodoc2-docstring} space_flight.fx.sfx.LOGGER
```

````

````{py:data} SOUND_VOLUME_REFERENCE_DISTANCE_M
:canonical: space_flight.fx.sfx.SOUND_VOLUME_REFERENCE_DISTANCE_M
:value: >
   500

```{autodoc2-docstring} space_flight.fx.sfx.SOUND_VOLUME_REFERENCE_DISTANCE_M
```

````

````{py:data} MAX_SOUND_DISTANCE_M
:canonical: space_flight.fx.sfx.MAX_SOUND_DISTANCE_M
:value: >
   2000

```{autodoc2-docstring} space_flight.fx.sfx.MAX_SOUND_DISTANCE_M
```

````

````{py:data} SFX_MAX_SOUND_DURATION_S
:canonical: space_flight.fx.sfx.SFX_MAX_SOUND_DURATION_S
:value: >
   5

```{autodoc2-docstring} space_flight.fx.sfx.SFX_MAX_SOUND_DURATION_S
```

````

````{py:data} TERRAIN_HIT_SOUND_MULTIPLIER
:canonical: space_flight.fx.sfx.TERRAIN_HIT_SOUND_MULTIPLIER
:value: >
   0.01

```{autodoc2-docstring} space_flight.fx.sfx.TERRAIN_HIT_SOUND_MULTIPLIER
```

````

````{py:data} TARGET_HIT_SOUND_MULTIPLIER
:canonical: space_flight.fx.sfx.TARGET_HIT_SOUND_MULTIPLIER
:value: >
   0.5

```{autodoc2-docstring} space_flight.fx.sfx.TARGET_HIT_SOUND_MULTIPLIER
```

````

````{py:data} PLAYER_HIT_SOUND_MULTIPLIER
:canonical: space_flight.fx.sfx.PLAYER_HIT_SOUND_MULTIPLIER
:value: >
   1.0

```{autodoc2-docstring} space_flight.fx.sfx.PLAYER_HIT_SOUND_MULTIPLIER
```

````

````{py:data} PLAYER_CANNON_FIRE_VOLUME
:canonical: space_flight.fx.sfx.PLAYER_CANNON_FIRE_VOLUME
:value: >
   1.0

```{autodoc2-docstring} space_flight.fx.sfx.PLAYER_CANNON_FIRE_VOLUME
```

````

````{py:data} NPC_CANNON_FIRE_VOLUME
:canonical: space_flight.fx.sfx.NPC_CANNON_FIRE_VOLUME
:value: >
   3.0

```{autodoc2-docstring} space_flight.fx.sfx.NPC_CANNON_FIRE_VOLUME
```

````

````{py:data} PLAYER_DISTANT_IMPACT_VOLUME
:canonical: space_flight.fx.sfx.PLAYER_DISTANT_IMPACT_VOLUME
:value: >
   1.0

```{autodoc2-docstring} space_flight.fx.sfx.PLAYER_DISTANT_IMPACT_VOLUME
```

````

````{py:data} NPC_DISTANT_IMPACT_VOLUME
:canonical: space_flight.fx.sfx.NPC_DISTANT_IMPACT_VOLUME
:value: >
   0.2

```{autodoc2-docstring} space_flight.fx.sfx.NPC_DISTANT_IMPACT_VOLUME
```

````

````{py:data} SOUND_POOL_LENGTH
:canonical: space_flight.fx.sfx.SOUND_POOL_LENGTH
:value: >
   20

```{autodoc2-docstring} space_flight.fx.sfx.SOUND_POOL_LENGTH
```

````

````{py:data} DISTANCE_FACTOR
:canonical: space_flight.fx.sfx.DISTANCE_FACTOR
:value: >
   1.0

```{autodoc2-docstring} space_flight.fx.sfx.DISTANCE_FACTOR
```

````

````{py:data} DOPPLER_FACTOR
:canonical: space_flight.fx.sfx.DOPPLER_FACTOR
:value: >
   0.5

```{autodoc2-docstring} space_flight.fx.sfx.DOPPLER_FACTOR
```

````

````{py:function} _velocity_of(source_ref: weakref.ref[space_flight.actors.pawn.Pawn | space_flight.actors.capital_ship.sub_system.SubSystem] | None) -> panda3d.core.VBase3
:canonical: space_flight.fx.sfx._velocity_of

```{autodoc2-docstring} space_flight.fx.sfx._velocity_of
```
````

`````{py:class} PhysicsAudio3DManager(*args: typing.Any, **kwargs: typing.Any)
:canonical: space_flight.fx.sfx.PhysicsAudio3DManager

Bases: {py:obj}`direct.showbase.Audio3DManager.Audio3DManager`

```{autodoc2-docstring} space_flight.fx.sfx.PhysicsAudio3DManager
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.fx.sfx.PhysicsAudio3DManager.__init__
```

````{py:method} set_sound_velocity_source(sound: panda3d.core.AudioSound, source: space_flight.actors.pawn.Pawn | space_flight.actors.capital_ship.sub_system.SubSystem | None)
:canonical: space_flight.fx.sfx.PhysicsAudio3DManager.set_sound_velocity_source

```{autodoc2-docstring} space_flight.fx.sfx.PhysicsAudio3DManager.set_sound_velocity_source
```

````

````{py:method} set_listener_velocity_source(source: space_flight.actors.pawn.Pawn | space_flight.actors.capital_ship.sub_system.SubSystem | None)
:canonical: space_flight.fx.sfx.PhysicsAudio3DManager.set_listener_velocity_source

```{autodoc2-docstring} space_flight.fx.sfx.PhysicsAudio3DManager.set_listener_velocity_source
```

````

````{py:method} getSoundVelocity(sound: panda3d.core.AudioSound) -> panda3d.core.VBase3
:canonical: space_flight.fx.sfx.PhysicsAudio3DManager.getSoundVelocity

````

````{py:method} getListenerVelocity() -> panda3d.core.VBase3
:canonical: space_flight.fx.sfx.PhysicsAudio3DManager.getListenerVelocity

````

````{py:method} detachSound(sound: panda3d.core.AudioSound) -> int
:canonical: space_flight.fx.sfx.PhysicsAudio3DManager.detachSound

````

`````

`````{py:class} SFX(app: space_flight.global_architecture.simulator.SpaceFlightSimulator)
:canonical: space_flight.fx.sfx.SFX

```{autodoc2-docstring} space_flight.fx.sfx.SFX
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.fx.sfx.SFX.__init__
```

````{py:method} attach_sound(sound: panda3d.core.AudioSound, node: panda3d.core.NodePath, velocity_source: space_flight.actors.pawn.Pawn | space_flight.actors.capital_ship.sub_system.SubSystem | None = None)
:canonical: space_flight.fx.sfx.SFX.attach_sound

```{autodoc2-docstring} space_flight.fx.sfx.SFX.attach_sound
```

````

````{py:method} set_listener_velocity_source(source: space_flight.actors.pawn.Pawn | space_flight.actors.capital_ship.sub_system.SubSystem | None)
:canonical: space_flight.fx.sfx.SFX.set_listener_velocity_source

```{autodoc2-docstring} space_flight.fx.sfx.SFX.set_listener_velocity_source
```

````

````{py:method} pause()
:canonical: space_flight.fx.sfx.SFX.pause

```{autodoc2-docstring} space_flight.fx.sfx.SFX.pause
```

````

````{py:method} resume()
:canonical: space_flight.fx.sfx.SFX.resume

```{autodoc2-docstring} space_flight.fx.sfx.SFX.resume
```

````

````{py:method} stop_level_sounds()
:canonical: space_flight.fx.sfx.SFX.stop_level_sounds

```{autodoc2-docstring} space_flight.fx.sfx.SFX.stop_level_sounds
```

````

````{py:method} build_sound_pool(directory: pathlib.Path, pattern: str, is_3d: bool) -> list[panda3d.core.AudioSound]
:canonical: space_flight.fx.sfx.SFX.build_sound_pool

```{autodoc2-docstring} space_flight.fx.sfx.SFX.build_sound_pool
```

````

````{py:method} get_3d_sound(sound_file: str | pathlib.Path) -> panda3d.core.AudioSound
:canonical: space_flight.fx.sfx.SFX.get_3d_sound

```{autodoc2-docstring} space_flight.fx.sfx.SFX.get_3d_sound
```

````

````{py:method} get_sounds_from_asset_manager()
:canonical: space_flight.fx.sfx.SFX.get_sounds_from_asset_manager

```{autodoc2-docstring} space_flight.fx.sfx.SFX.get_sounds_from_asset_manager
```

````

````{py:method} distant_impact_hit(game: space_flight.game.flight_state.FlightState, player_ship_pos: numpy.ndarray, hit_pos: numpy.ndarray, impact_type: str, is_player: bool = False)
:canonical: space_flight.fx.sfx.SFX.distant_impact_hit

```{autodoc2-docstring} space_flight.fx.sfx.SFX.distant_impact_hit
```

````

````{py:method} tractor_beam_grab(game: space_flight.game.flight_state.FlightState)
:canonical: space_flight.fx.sfx.SFX.tractor_beam_grab

```{autodoc2-docstring} space_flight.fx.sfx.SFX.tractor_beam_grab
```

````

````{py:method} tractor_beam_release(game: space_flight.game.flight_state.FlightState)
:canonical: space_flight.fx.sfx.SFX.tractor_beam_release

```{autodoc2-docstring} space_flight.fx.sfx.SFX.tractor_beam_release
```

````

````{py:method} laser_impact_hit_on_player(game: space_flight.game.flight_state.FlightState, relative_hit_point: numpy.ndarray, is_shield: bool)
:canonical: space_flight.fx.sfx.SFX.laser_impact_hit_on_player

```{autodoc2-docstring} space_flight.fx.sfx.SFX.laser_impact_hit_on_player
```

````

````{py:method} player_crash(game: space_flight.game.flight_state.FlightState, relative_hit_point: numpy.ndarray, in_terrain: bool)
:canonical: space_flight.fx.sfx.SFX.player_crash

```{autodoc2-docstring} space_flight.fx.sfx.SFX.player_crash
```

````

````{py:method} cannon_fire(game: space_flight.game.flight_state.FlightState, sound_pool: space_flight.global_architecture.asset_pools.SoundPool, node: panda3d.core.NodePath, velocity_source: space_flight.actors.pawn.Pawn | space_flight.actors.capital_ship.sub_system.SubSystem | None = None, is_player: bool = False)
:canonical: space_flight.fx.sfx.SFX.cannon_fire

```{autodoc2-docstring} space_flight.fx.sfx.SFX.cannon_fire
```

````

````{py:method} update_task(task: direct.task.Task.Task) -> int
:canonical: space_flight.fx.sfx.SFX.update_task

```{autodoc2-docstring} space_flight.fx.sfx.SFX.update_task
```

````

`````
