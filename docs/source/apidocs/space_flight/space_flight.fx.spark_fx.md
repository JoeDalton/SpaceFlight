# {py:mod}`space_flight.fx.spark_fx`

```{py:module} space_flight.fx.spark_fx
```

```{autodoc2-docstring} space_flight.fx.spark_fx
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`SparkPreset <space_flight.fx.spark_fx.SparkPreset>`
  - ```{autodoc2-docstring} space_flight.fx.spark_fx.SparkPreset
    :summary:
    ```
* - {py:obj}`SparkPool <space_flight.fx.spark_fx.SparkPool>`
  - ```{autodoc2-docstring} space_flight.fx.spark_fx.SparkPool
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_spark_shader <space_flight.fx.spark_fx._spark_shader>`
  - ```{autodoc2-docstring} space_flight.fx.spark_fx._spark_shader
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`SPARK_SIZE_SCALE <space_flight.fx.spark_fx.SPARK_SIZE_SCALE>`
  - ```{autodoc2-docstring} space_flight.fx.spark_fx.SPARK_SIZE_SCALE
    :summary:
    ```
* - {py:obj}`SPARK_SPEED_SCALE <space_flight.fx.spark_fx.SPARK_SPEED_SCALE>`
  - ```{autodoc2-docstring} space_flight.fx.spark_fx.SPARK_SPEED_SCALE
    :summary:
    ```
* - {py:obj}`SPARK_JET_ANGLE_SCALE <space_flight.fx.spark_fx.SPARK_JET_ANGLE_SCALE>`
  - ```{autodoc2-docstring} space_flight.fx.spark_fx.SPARK_JET_ANGLE_SCALE
    :summary:
    ```
* - {py:obj}`_SPARK_COLUMNS <space_flight.fx.spark_fx._SPARK_COLUMNS>`
  - ```{autodoc2-docstring} space_flight.fx.spark_fx._SPARK_COLUMNS
    :summary:
    ```
* - {py:obj}`_SPARK_TEXTURE <space_flight.fx.spark_fx._SPARK_TEXTURE>`
  - ```{autodoc2-docstring} space_flight.fx.spark_fx._SPARK_TEXTURE
    :summary:
    ```
* - {py:obj}`_SPARK_SHADER <space_flight.fx.spark_fx._SPARK_SHADER>`
  - ```{autodoc2-docstring} space_flight.fx.spark_fx._SPARK_SHADER
    :summary:
    ```
* - {py:obj}`METAL <space_flight.fx.spark_fx.METAL>`
  - ```{autodoc2-docstring} space_flight.fx.spark_fx.METAL
    :summary:
    ```
* - {py:obj}`ICE <space_flight.fx.spark_fx.ICE>`
  - ```{autodoc2-docstring} space_flight.fx.spark_fx.ICE
    :summary:
    ```
* - {py:obj}`MAGIC <space_flight.fx.spark_fx.MAGIC>`
  - ```{autodoc2-docstring} space_flight.fx.spark_fx.MAGIC
    :summary:
    ```
* - {py:obj}`ROCK <space_flight.fx.spark_fx.ROCK>`
  - ```{autodoc2-docstring} space_flight.fx.spark_fx.ROCK
    :summary:
    ```
````

### API

````{py:data} SPARK_SIZE_SCALE
:canonical: space_flight.fx.spark_fx.SPARK_SIZE_SCALE
:value: >
   10.0

```{autodoc2-docstring} space_flight.fx.spark_fx.SPARK_SIZE_SCALE
```

````

````{py:data} SPARK_SPEED_SCALE
:canonical: space_flight.fx.spark_fx.SPARK_SPEED_SCALE
:value: >
   10.0

```{autodoc2-docstring} space_flight.fx.spark_fx.SPARK_SPEED_SCALE
```

````

````{py:data} SPARK_JET_ANGLE_SCALE
:canonical: space_flight.fx.spark_fx.SPARK_JET_ANGLE_SCALE
:value: >
   1.0

```{autodoc2-docstring} space_flight.fx.spark_fx.SPARK_JET_ANGLE_SCALE
```

````

````{py:data} _SPARK_COLUMNS
:canonical: space_flight.fx.spark_fx._SPARK_COLUMNS
:value: >
   [('velocity', 3), ('size', 1), ('lifetime', 1), ('gravity', 1), ('spark_color', 4)]

```{autodoc2-docstring} space_flight.fx.spark_fx._SPARK_COLUMNS
```

````

````{py:data} _SPARK_TEXTURE
:canonical: space_flight.fx.spark_fx._SPARK_TEXTURE
:value: >
   None

```{autodoc2-docstring} space_flight.fx.spark_fx._SPARK_TEXTURE
```

````

````{py:data} _SPARK_SHADER
:canonical: space_flight.fx.spark_fx._SPARK_SHADER
:value: >
   None

```{autodoc2-docstring} space_flight.fx.spark_fx._SPARK_SHADER
```

````

````{py:function} _spark_shader() -> panda3d.core.Shader
:canonical: space_flight.fx.spark_fx._spark_shader

```{autodoc2-docstring} space_flight.fx.spark_fx._spark_shader
```
````

`````{py:class} SparkPreset
:canonical: space_flight.fx.spark_fx.SparkPreset

```{autodoc2-docstring} space_flight.fx.spark_fx.SparkPreset
```

````{py:attribute} color_inner
:canonical: space_flight.fx.spark_fx.SparkPreset.color_inner
:type: tuple
:value: >
   None

```{autodoc2-docstring} space_flight.fx.spark_fx.SparkPreset.color_inner
```

````

````{py:attribute} color_outer
:canonical: space_flight.fx.spark_fx.SparkPreset.color_outer
:type: tuple
:value: >
   None

```{autodoc2-docstring} space_flight.fx.spark_fx.SparkPreset.color_outer
```

````

````{py:attribute} count
:canonical: space_flight.fx.spark_fx.SparkPreset.count
:type: int
:value: >
   None

```{autodoc2-docstring} space_flight.fx.spark_fx.SparkPreset.count
```

````

````{py:attribute} speed
:canonical: space_flight.fx.spark_fx.SparkPreset.speed
:type: float
:value: >
   None

```{autodoc2-docstring} space_flight.fx.spark_fx.SparkPreset.speed
```

````

````{py:attribute} spread
:canonical: space_flight.fx.spark_fx.SparkPreset.spread
:type: float
:value: >
   None

```{autodoc2-docstring} space_flight.fx.spark_fx.SparkPreset.spread
```

````

````{py:attribute} gravity
:canonical: space_flight.fx.spark_fx.SparkPreset.gravity
:type: float
:value: >
   None

```{autodoc2-docstring} space_flight.fx.spark_fx.SparkPreset.gravity
```

````

````{py:attribute} lifetime
:canonical: space_flight.fx.spark_fx.SparkPreset.lifetime
:type: float
:value: >
   None

```{autodoc2-docstring} space_flight.fx.spark_fx.SparkPreset.lifetime
```

````

````{py:attribute} size
:canonical: space_flight.fx.spark_fx.SparkPreset.size
:type: float
:value: >
   None

```{autodoc2-docstring} space_flight.fx.spark_fx.SparkPreset.size
```

````

`````

````{py:data} METAL
:canonical: space_flight.fx.spark_fx.METAL
:value: >
   'SparkPreset(...)'

```{autodoc2-docstring} space_flight.fx.spark_fx.METAL
```

````

````{py:data} ICE
:canonical: space_flight.fx.spark_fx.ICE
:value: >
   'SparkPreset(...)'

```{autodoc2-docstring} space_flight.fx.spark_fx.ICE
```

````

````{py:data} MAGIC
:canonical: space_flight.fx.spark_fx.MAGIC
:value: >
   'SparkPreset(...)'

```{autodoc2-docstring} space_flight.fx.spark_fx.MAGIC
```

````

````{py:data} ROCK
:canonical: space_flight.fx.spark_fx.ROCK
:value: >
   'SparkPreset(...)'

```{autodoc2-docstring} space_flight.fx.spark_fx.ROCK
```

````

`````{py:class} SparkPool(game: space_flight.game.flight_state.FlightState)
:canonical: space_flight.fx.spark_fx.SparkPool

Bases: {py:obj}`space_flight.fx.ParticleBuffer`

```{autodoc2-docstring} space_flight.fx.spark_fx.SparkPool
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.fx.spark_fx.SparkPool.__init__
```

````{py:method} spawn(position: panda3d.core.Point3, normal: panda3d.core.Vec3, base_velocity: panda3d.core.Vec3, preset: space_flight.fx.spark_fx.SparkPreset) -> None
:canonical: space_flight.fx.spark_fx.SparkPool.spawn

```{autodoc2-docstring} space_flight.fx.spark_fx.SparkPool.spawn
```

````

`````
