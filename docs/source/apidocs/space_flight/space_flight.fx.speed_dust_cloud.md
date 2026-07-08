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

`````{py:class} SpeedDustCloud(game, num_particles: int = 100, spread: float = 30, depth: float = 100.0, colors: typing.List = ['white'], *, defer_build: bool = False)
:canonical: space_flight.fx.speed_dust_cloud.SpeedDustCloud

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.SpeedDustCloud
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.SpeedDustCloud.__init__
```

````{py:method} build(chunk: int = 25)
:canonical: space_flight.fx.speed_dust_cloud.SpeedDustCloud.build

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.SpeedDustCloud.build
```

````

````{py:method} init_particle(particle)
:canonical: space_flight.fx.speed_dust_cloud.SpeedDustCloud.init_particle

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.SpeedDustCloud.init_particle
```

````

````{py:method} reset_particle(particle)
:canonical: space_flight.fx.speed_dust_cloud.SpeedDustCloud.reset_particle

```{autodoc2-docstring} space_flight.fx.speed_dust_cloud.SpeedDustCloud.reset_particle
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
