# {py:mod}`space_flight.fx.explosion_fx`

```{py:module} space_flight.fx.explosion_fx
```

```{autodoc2-docstring} space_flight.fx.explosion_fx
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_ExplosionBuffer <space_flight.fx.explosion_fx._ExplosionBuffer>`
  - ```{autodoc2-docstring} space_flight.fx.explosion_fx._ExplosionBuffer
    :summary:
    ```
* - {py:obj}`ExplosionPool <space_flight.fx.explosion_fx.ExplosionPool>`
  - ```{autodoc2-docstring} space_flight.fx.explosion_fx.ExplosionPool
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`build_expl_vert <space_flight.fx.explosion_fx.build_expl_vert>`
  - ```{autodoc2-docstring} space_flight.fx.explosion_fx.build_expl_vert
    :summary:
    ```
* - {py:obj}`build_expl_frag <space_flight.fx.explosion_fx.build_expl_frag>`
  - ```{autodoc2-docstring} space_flight.fx.explosion_fx.build_expl_frag
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_FIRE_COUNT <space_flight.fx.explosion_fx._FIRE_COUNT>`
  - ```{autodoc2-docstring} space_flight.fx.explosion_fx._FIRE_COUNT
    :summary:
    ```
* - {py:obj}`_SMOKE_COUNT <space_flight.fx.explosion_fx._SMOKE_COUNT>`
  - ```{autodoc2-docstring} space_flight.fx.explosion_fx._SMOKE_COUNT
    :summary:
    ```
* - {py:obj}`_SPIN_MAX <space_flight.fx.explosion_fx._SPIN_MAX>`
  - ```{autodoc2-docstring} space_flight.fx.explosion_fx._SPIN_MAX
    :summary:
    ```
* - {py:obj}`_SIZE_SCALE <space_flight.fx.explosion_fx._SIZE_SCALE>`
  - ```{autodoc2-docstring} space_flight.fx.explosion_fx._SIZE_SCALE
    :summary:
    ```
* - {py:obj}`_SMOKE_DELAY <space_flight.fx.explosion_fx._SMOKE_DELAY>`
  - ```{autodoc2-docstring} space_flight.fx.explosion_fx._SMOKE_DELAY
    :summary:
    ```
* - {py:obj}`_FIRE_POS_BIAS <space_flight.fx.explosion_fx._FIRE_POS_BIAS>`
  - ```{autodoc2-docstring} space_flight.fx.explosion_fx._FIRE_POS_BIAS
    :summary:
    ```
* - {py:obj}`_SMOKE_POS_BIAS <space_flight.fx.explosion_fx._SMOKE_POS_BIAS>`
  - ```{autodoc2-docstring} space_flight.fx.explosion_fx._SMOKE_POS_BIAS
    :summary:
    ```
* - {py:obj}`_FIRE_FADEIN <space_flight.fx.explosion_fx._FIRE_FADEIN>`
  - ```{autodoc2-docstring} space_flight.fx.explosion_fx._FIRE_FADEIN
    :summary:
    ```
* - {py:obj}`_SMOKE_FADEIN <space_flight.fx.explosion_fx._SMOKE_FADEIN>`
  - ```{autodoc2-docstring} space_flight.fx.explosion_fx._SMOKE_FADEIN
    :summary:
    ```
* - {py:obj}`_ATLAS_FIRE <space_flight.fx.explosion_fx._ATLAS_FIRE>`
  - ```{autodoc2-docstring} space_flight.fx.explosion_fx._ATLAS_FIRE
    :summary:
    ```
* - {py:obj}`_ATLAS_SMOKE <space_flight.fx.explosion_fx._ATLAS_SMOKE>`
  - ```{autodoc2-docstring} space_flight.fx.explosion_fx._ATLAS_SMOKE
    :summary:
    ```
* - {py:obj}`_JSON_FIRE <space_flight.fx.explosion_fx._JSON_FIRE>`
  - ```{autodoc2-docstring} space_flight.fx.explosion_fx._JSON_FIRE
    :summary:
    ```
* - {py:obj}`_JSON_SMOKE <space_flight.fx.explosion_fx._JSON_SMOKE>`
  - ```{autodoc2-docstring} space_flight.fx.explosion_fx._JSON_SMOKE
    :summary:
    ```
````

### API

````{py:data} _FIRE_COUNT
:canonical: space_flight.fx.explosion_fx._FIRE_COUNT
:value: >
   8

```{autodoc2-docstring} space_flight.fx.explosion_fx._FIRE_COUNT
```

````

````{py:data} _SMOKE_COUNT
:canonical: space_flight.fx.explosion_fx._SMOKE_COUNT
:value: >
   8

```{autodoc2-docstring} space_flight.fx.explosion_fx._SMOKE_COUNT
```

````

````{py:data} _SPIN_MAX
:canonical: space_flight.fx.explosion_fx._SPIN_MAX
:value: >
   3.0

```{autodoc2-docstring} space_flight.fx.explosion_fx._SPIN_MAX
```

````

````{py:data} _SIZE_SCALE
:canonical: space_flight.fx.explosion_fx._SIZE_SCALE
:value: >
   100.0

```{autodoc2-docstring} space_flight.fx.explosion_fx._SIZE_SCALE
```

````

````{py:data} _SMOKE_DELAY
:canonical: space_flight.fx.explosion_fx._SMOKE_DELAY
:value: >
   0.3

```{autodoc2-docstring} space_flight.fx.explosion_fx._SMOKE_DELAY
```

````

````{py:data} _FIRE_POS_BIAS
:canonical: space_flight.fx.explosion_fx._FIRE_POS_BIAS
:value: >
   0.3

```{autodoc2-docstring} space_flight.fx.explosion_fx._FIRE_POS_BIAS
```

````

````{py:data} _SMOKE_POS_BIAS
:canonical: space_flight.fx.explosion_fx._SMOKE_POS_BIAS
:value: >
   0.5

```{autodoc2-docstring} space_flight.fx.explosion_fx._SMOKE_POS_BIAS
```

````

````{py:data} _FIRE_FADEIN
:canonical: space_flight.fx.explosion_fx._FIRE_FADEIN
:value: >
   0.3

```{autodoc2-docstring} space_flight.fx.explosion_fx._FIRE_FADEIN
```

````

````{py:data} _SMOKE_FADEIN
:canonical: space_flight.fx.explosion_fx._SMOKE_FADEIN
:value: >
   0.7

```{autodoc2-docstring} space_flight.fx.explosion_fx._SMOKE_FADEIN
```

````

````{py:data} _ATLAS_FIRE
:canonical: space_flight.fx.explosion_fx._ATLAS_FIRE
:value: >
   None

```{autodoc2-docstring} space_flight.fx.explosion_fx._ATLAS_FIRE
```

````

````{py:data} _ATLAS_SMOKE
:canonical: space_flight.fx.explosion_fx._ATLAS_SMOKE
:value: >
   None

```{autodoc2-docstring} space_flight.fx.explosion_fx._ATLAS_SMOKE
```

````

````{py:data} _JSON_FIRE
:canonical: space_flight.fx.explosion_fx._JSON_FIRE
:value: >
   None

```{autodoc2-docstring} space_flight.fx.explosion_fx._JSON_FIRE
```

````

````{py:data} _JSON_SMOKE
:canonical: space_flight.fx.explosion_fx._JSON_SMOKE
:value: >
   None

```{autodoc2-docstring} space_flight.fx.explosion_fx._JSON_SMOKE
```

````

````{py:function} build_expl_vert(size_curve: str, fadein: float) -> str
:canonical: space_flight.fx.explosion_fx.build_expl_vert

```{autodoc2-docstring} space_flight.fx.explosion_fx.build_expl_vert
```
````

````{py:function} build_expl_frag(n_tiles: int) -> str
:canonical: space_flight.fx.explosion_fx.build_expl_frag

```{autodoc2-docstring} space_flight.fx.explosion_fx.build_expl_frag
```
````

`````{py:class} _ExplosionBuffer(game, vert_src, frag_src, texture, tile_rects, bin_order, additive, task_name)
:canonical: space_flight.fx.explosion_fx._ExplosionBuffer

Bases: {py:obj}`space_flight.fx.ParticleBuffer`

```{autodoc2-docstring} space_flight.fx.explosion_fx._ExplosionBuffer
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.fx.explosion_fx._ExplosionBuffer.__init__
```

````{py:method} spawn_particle(pos: numpy.ndarray, vel: numpy.ndarray, size: float, lifetime: float, tile_index: int, spin_rate: float, delay: float = 0.0)
:canonical: space_flight.fx.explosion_fx._ExplosionBuffer.spawn_particle

```{autodoc2-docstring} space_flight.fx.explosion_fx._ExplosionBuffer.spawn_particle
```

````

`````

`````{py:class} ExplosionPool(game)
:canonical: space_flight.fx.explosion_fx.ExplosionPool

```{autodoc2-docstring} space_flight.fx.explosion_fx.ExplosionPool
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.fx.explosion_fx.ExplosionPool.__init__
```

````{py:method} spawn(position: panda3d.core.Point3, scale: float, base_velocity: panda3d.core.Vec3, normal: panda3d.core.Vec3 = None)
:canonical: space_flight.fx.explosion_fx.ExplosionPool.spawn

```{autodoc2-docstring} space_flight.fx.explosion_fx.ExplosionPool.spawn
```

````

````{py:method} clean()
:canonical: space_flight.fx.explosion_fx.ExplosionPool.clean

```{autodoc2-docstring} space_flight.fx.explosion_fx.ExplosionPool.clean
```

````

`````
