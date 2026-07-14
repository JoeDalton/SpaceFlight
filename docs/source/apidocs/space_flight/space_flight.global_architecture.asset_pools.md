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

`````{py:class} TexturePool(app, path: pathlib.Path, pattern: str)
:canonical: space_flight.global_architecture.asset_pools.TexturePool

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.TexturePool
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.TexturePool.__init__
```

````{py:method} get_texture() -> object
:canonical: space_flight.global_architecture.asset_pools.TexturePool.get_texture

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.TexturePool.get_texture
```

````

`````

````{py:function} build_texture_pool(app, directory: pathlib.Path, pattern: str) -> list
:canonical: space_flight.global_architecture.asset_pools.build_texture_pool

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.build_texture_pool
```
````

````{py:function} load_texture(app, texture_file: str) -> object
:canonical: space_flight.global_architecture.asset_pools.load_texture

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.load_texture
```
````

`````{py:class} SoundPool(app, path: pathlib.Path, pattern: str, is_3d: bool)
:canonical: space_flight.global_architecture.asset_pools.SoundPool

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.SoundPool
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.SoundPool.__init__
```

````{py:method} get_sound(randomize_pitch: bool = False) -> object
:canonical: space_flight.global_architecture.asset_pools.SoundPool.get_sound

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.SoundPool.get_sound
```

````

````{py:method} release_sound(sound)
:canonical: space_flight.global_architecture.asset_pools.SoundPool.release_sound

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.SoundPool.release_sound
```

````

`````

````{py:function} build_sound_pool(app, directory: pathlib.Path, pattern: str, is_3d: bool) -> list
:canonical: space_flight.global_architecture.asset_pools.build_sound_pool

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.build_sound_pool
```
````

````{py:function} load_3d_sound(app, sound_file: str) -> object
:canonical: space_flight.global_architecture.asset_pools.load_3d_sound

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.load_3d_sound
```
````

````{py:function} load_generic_sound(app, sound_file: str)
:canonical: space_flight.global_architecture.asset_pools.load_generic_sound

```{autodoc2-docstring} space_flight.global_architecture.asset_pools.load_generic_sound
```
````
