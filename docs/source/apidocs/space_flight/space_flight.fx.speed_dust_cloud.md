# {py:mod}`space_flight.fx.speed_dust_cloud`

```{py:module} space_flight.fx.speed_dust_cloud
```

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`SpeedDustCloud <space_flight.fx.speed_dust_cloud.SpeedDustCloud>`
  - ```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.SpeedDustCloud
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_dust_shader <space_flight.fx.speed_dust_cloud._dust_shader>`
  - ```{autodoc2-docstring} space_flight.fx.speed_dust_cloud._dust_shader
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`MIN_DUST_ALPHA <space_flight.fx.speed_dust_cloud.MIN_DUST_ALPHA>`
  - ```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.MIN_DUST_ALPHA
    :summary:
    ```
* - {py:obj}`MAX_DUST_ALPHA <space_flight.fx.speed_dust_cloud.MAX_DUST_ALPHA>`
  - ```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.MAX_DUST_ALPHA
    :summary:
    ```
* - {py:obj}`MOTE_HALF_SIZE_M <space_flight.fx.speed_dust_cloud.MOTE_HALF_SIZE_M>`
  - ```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.MOTE_HALF_SIZE_M
    :summary:
    ```
* - {py:obj}`TRAVEL_WRAP_DEPTHS <space_flight.fx.speed_dust_cloud.TRAVEL_WRAP_DEPTHS>`
  - ```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.TRAVEL_WRAP_DEPTHS
    :summary:
    ```
* - {py:obj}`_SHADERS <space_flight.fx.speed_dust_cloud._SHADERS>`
  - ```{autodoc2-docstring} space_flight.fx.speed_dust_cloud._SHADERS
    :summary:
    ```
````

### API

````{py:data} MIN_DUST_ALPHA
:canonical: space_flight.fx.speed_dust_cloud.MIN_DUST_ALPHA
:value: >
   0.2

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.MIN_DUST_ALPHA
```

````

````{py:data} MAX_DUST_ALPHA
:canonical: space_flight.fx.speed_dust_cloud.MAX_DUST_ALPHA
:value: >
   0.8

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.MAX_DUST_ALPHA
```

````

````{py:data} MOTE_HALF_SIZE_M
:canonical: space_flight.fx.speed_dust_cloud.MOTE_HALF_SIZE_M
:value: >
   0.02

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.MOTE_HALF_SIZE_M
```

````

````{py:data} TRAVEL_WRAP_DEPTHS
:canonical: space_flight.fx.speed_dust_cloud.TRAVEL_WRAP_DEPTHS
:value: >
   4096

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.TRAVEL_WRAP_DEPTHS
```

````

````{py:data} _SHADERS
:canonical: space_flight.fx.speed_dust_cloud._SHADERS
:value: >
   None

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud._SHADERS
```

````

````{py:function} _dust_shader() -> panda3d.core.Shader
:canonical: space_flight.fx.speed_dust_cloud._dust_shader

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud._dust_shader
```
````

`````{py:class} SpeedDustCloud(game: space_flight.game.flight_state.FlightState, num_particles: int = 100, spread: float = 30, depth: float = 100.0, colors: typing.List = ['white'], *, defer_build: bool = False)
:canonical: space_flight.fx.speed_dust_cloud.SpeedDustCloud

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.SpeedDustCloud
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.SpeedDustCloud.__init__
```

````{py:method} build(chunk: int = 25) -> collections.abc.Generator[None, None, None]
:canonical: space_flight.fx.speed_dust_cloud.SpeedDustCloud.build

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.SpeedDustCloud.build
```

````

````{py:method} _random_mote() -> tuple
:canonical: space_flight.fx.speed_dust_cloud.SpeedDustCloud._random_mote

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.SpeedDustCloud._random_mote
```

````

````{py:method} _make_geometry(color: str, motes: list[tuple]) -> panda3d.core.NodePath
:canonical: space_flight.fx.speed_dust_cloud.SpeedDustCloud._make_geometry

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.SpeedDustCloud._make_geometry
```

````

````{py:method} dust_update()
:canonical: space_flight.fx.speed_dust_cloud.SpeedDustCloud.dust_update

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.SpeedDustCloud.dust_update
```

````

````{py:method} clean()
:canonical: space_flight.fx.speed_dust_cloud.SpeedDustCloud.clean

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.SpeedDustCloud.clean
```

````

`````
