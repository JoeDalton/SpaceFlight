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

* - {py:obj}`SFX <space_flight.fx.sfx.SFX>`
  - ```{autodoc2-docstring} space_flight.fx.sfx.SFX
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
* - {py:obj}`SOUND_POOL_LENGTH <space_flight.fx.sfx.SOUND_POOL_LENGTH>`
  - ```{autodoc2-docstring} space_flight.fx.sfx.SOUND_POOL_LENGTH
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
   1.0

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

````{py:data} SOUND_POOL_LENGTH
:canonical: space_flight.fx.sfx.SOUND_POOL_LENGTH
:value: >
   20

```{autodoc2-docstring} space_flight.fx.sfx.SOUND_POOL_LENGTH
```

````

`````{py:class} SFX(app)
:canonical: space_flight.fx.sfx.SFX

```{autodoc2-docstring} space_flight.fx.sfx.SFX
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.fx.sfx.SFX.__init__
```

````{py:method} build_sound_pool(directory: pathlib.Path, pattern: str, is_3d: bool) -> typing.List[str]
:canonical: space_flight.fx.sfx.SFX.build_sound_pool

```{autodoc2-docstring} space_flight.fx.sfx.SFX.build_sound_pool
```

````

````{py:method} get_3d_sound(sound_file: str) -> object
:canonical: space_flight.fx.sfx.SFX.get_3d_sound

```{autodoc2-docstring} space_flight.fx.sfx.SFX.get_3d_sound
```

````

````{py:method} get_sounds_from_asset_manager()
:canonical: space_flight.fx.sfx.SFX.get_sounds_from_asset_manager

```{autodoc2-docstring} space_flight.fx.sfx.SFX.get_sounds_from_asset_manager
```

````

````{py:method} distant_impact_hit(game, player_ship_pos: numpy.ndarray, hit_pos: numpy.ndarray, impact_type: str)
:canonical: space_flight.fx.sfx.SFX.distant_impact_hit

```{autodoc2-docstring} space_flight.fx.sfx.SFX.distant_impact_hit
```

````

````{py:method} tractor_beam_grab(game)
:canonical: space_flight.fx.sfx.SFX.tractor_beam_grab

```{autodoc2-docstring} space_flight.fx.sfx.SFX.tractor_beam_grab
```

````

````{py:method} laser_impact_hit_on_player(game, relative_hit_point: numpy.ndarray, is_shield: bool)
:canonical: space_flight.fx.sfx.SFX.laser_impact_hit_on_player

```{autodoc2-docstring} space_flight.fx.sfx.SFX.laser_impact_hit_on_player
```

````

````{py:method} player_crash(game, relative_hit_point: numpy.ndarray, in_terrain: bool)
:canonical: space_flight.fx.sfx.SFX.player_crash

```{autodoc2-docstring} space_flight.fx.sfx.SFX.player_crash
```

````

````{py:method} cannon_fire(game, sound_pool, node)
:canonical: space_flight.fx.sfx.SFX.cannon_fire

```{autodoc2-docstring} space_flight.fx.sfx.SFX.cannon_fire
```

````

````{py:method} update_task(task)
:canonical: space_flight.fx.sfx.SFX.update_task

```{autodoc2-docstring} space_flight.fx.sfx.SFX.update_task
```

````

`````
