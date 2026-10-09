# {py:mod}`space_flight.global_architecture.asset_pools`

```{py:module} space_flight.global_architecture.asset_pools
```

```{autodoc2-docstring} space_flight.global_architecture.asset_pools
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`TexturePool <space_flight.global_architecture.asset_pools.TexturePool>`
  - ```{autodoc2-docstring} space_flight.global_architecture.asset_pools.TexturePool
    :summary:
    ```
* - {py:obj}`SoundPool <space_flight.global_architecture.asset_pools.SoundPool>`
  - ```{autodoc2-docstring} space_flight.global_architecture.asset_pools.SoundPool
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`build_texture_pool <space_flight.global_architecture.asset_pools.build_texture_pool>`
  - ```{autodoc2-docstring} space_flight.global_architecture.asset_pools.build_texture_pool
    :summary:
    ```
* - {py:obj}`load_texture <space_flight.global_architecture.asset_pools.load_texture>`
  - ```{autodoc2-docstring} space_flight.global_architecture.asset_pools.load_texture
    :summary:
    ```
* - {py:obj}`build_sound_pool <space_flight.global_architecture.asset_pools.build_sound_pool>`
  - ```{autodoc2-docstring} space_flight.global_architecture.asset_pools.build_sound_pool
    :summary:
    ```
* - {py:obj}`load_3d_sound <space_flight.global_architecture.asset_pools.load_3d_sound>`
  - ```{autodoc2-docstring} space_flight.global_architecture.asset_pools.load_3d_sound
    :summary:
    ```
* - {py:obj}`load_generic_sound <space_flight.global_architecture.asset_pools.load_generic_sound>`
  - ```{autodoc2-docstring} space_flight.global_architecture.asset_pools.load_generic_sound
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LOGGER <space_flight.global_architecture.asset_pools.LOGGER>`
  - ```{autodoc2-docstring} space_flight.global_architecture.asset_pools.LOGGER
    :summary:
    ```
* - {py:obj}`SOUND_POOL_LENGTH <space_flight.global_architecture.asset_pools.SOUND_POOL_LENGTH>`
  - ```{autodoc2-docstring} space_flight.global_architecture.asset_pools.SOUND_POOL_LENGTH
    :summary:
    ```
````

### API

````{py:data} LOGGER
:canonical: space_flight.global_architecture.asset_pools.LOGGER
:value: >
   'getLogger(...)'

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.LOGGER
```

````

````{py:data} SOUND_POOL_LENGTH
:canonical: space_flight.global_architecture.asset_pools.SOUND_POOL_LENGTH
:value: >
   1000

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.SOUND_POOL_LENGTH
```

````

`````{py:class} TexturePool(app: space_flight.global_architecture.simulator.SpaceFlightSimulator, path: pathlib.Path, pattern: str)
:canonical: space_flight.global_architecture.asset_pools.TexturePool

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.TexturePool
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.TexturePool.__init__
```

````{py:method} get_texture() -> panda3d.core.Texture
:canonical: space_flight.global_architecture.asset_pools.TexturePool.get_texture

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.TexturePool.get_texture
```

````

`````

````{py:function} build_texture_pool(app: space_flight.global_architecture.simulator.SpaceFlightSimulator, directory: pathlib.Path, pattern: str) -> list
:canonical: space_flight.global_architecture.asset_pools.build_texture_pool

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.build_texture_pool
```
````

````{py:function} load_texture(app: space_flight.global_architecture.simulator.SpaceFlightSimulator, texture_file: pathlib.Path) -> panda3d.core.Texture
:canonical: space_flight.global_architecture.asset_pools.load_texture

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.load_texture
```
````

`````{py:class} SoundPool(app: space_flight.global_architecture.simulator.SpaceFlightSimulator, path: pathlib.Path, pattern: str, is_3d: bool)
:canonical: space_flight.global_architecture.asset_pools.SoundPool

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.SoundPool
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.SoundPool.__init__
```

````{py:method} get_sound(randomize_pitch: bool = False) -> panda3d.core.AudioSound
:canonical: space_flight.global_architecture.asset_pools.SoundPool.get_sound

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.SoundPool.get_sound
```

````

````{py:method} release_sound(sound: panda3d.core.AudioSound)
:canonical: space_flight.global_architecture.asset_pools.SoundPool.release_sound

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.SoundPool.release_sound
```

````

````{py:method} in_use_sounds() -> list[panda3d.core.AudioSound]
:canonical: space_flight.global_architecture.asset_pools.SoundPool.in_use_sounds

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.SoundPool.in_use_sounds
```

````

````{py:method} release_all()
:canonical: space_flight.global_architecture.asset_pools.SoundPool.release_all

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.SoundPool.release_all
```

````

`````

````{py:function} build_sound_pool(app: space_flight.global_architecture.simulator.SpaceFlightSimulator, directory: pathlib.Path, pattern: str, is_3d: bool) -> list
:canonical: space_flight.global_architecture.asset_pools.build_sound_pool

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.build_sound_pool
```
````

````{py:function} load_3d_sound(app: space_flight.global_architecture.simulator.SpaceFlightSimulator, sound_file: pathlib.Path) -> panda3d.core.AudioSound
:canonical: space_flight.global_architecture.asset_pools.load_3d_sound

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.load_3d_sound
```
````

````{py:function} load_generic_sound(app: space_flight.global_architecture.simulator.SpaceFlightSimulator, sound_file: pathlib.Path) -> panda3d.core.AudioSound
:canonical: space_flight.global_architecture.asset_pools.load_generic_sound

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.load_generic_sound
```
````
