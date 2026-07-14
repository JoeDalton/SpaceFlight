# {py:mod}`space_flight.weapons.laser_cannon`

```{py:module} space_flight.weapons.laser_cannon
```

```{autodoc2-docstring} space_flight.weapons.laser_cannon
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LaserCannon <space_flight.weapons.laser_cannon.LaserCannon>`
  - ```{autodoc2-docstring} space_flight.weapons.laser_cannon.LaserCannon
    :summary:
    ```
* - {py:obj}`LaserShot <space_flight.weapons.laser_cannon.LaserShot>`
  - ```{autodoc2-docstring} space_flight.weapons.laser_cannon.LaserShot
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_laser_shader <space_flight.weapons.laser_cannon._laser_shader>`
  - ```{autodoc2-docstring} space_flight.weapons.laser_cannon._laser_shader
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LASER_SPEED_MPS <space_flight.weapons.laser_cannon.LASER_SPEED_MPS>`
  - ```{autodoc2-docstring} space_flight.weapons.laser_cannon.LASER_SPEED_MPS
    :summary:
    ```
* - {py:obj}`SQT2_S <space_flight.weapons.laser_cannon.SQT2_S>`
  - ```{autodoc2-docstring} space_flight.weapons.laser_cannon.SQT2_S
    :summary:
    ```
* - {py:obj}`LIGHT_ATTENUATION <space_flight.weapons.laser_cannon.LIGHT_ATTENUATION>`
  - ```{autodoc2-docstring} space_flight.weapons.laser_cannon.LIGHT_ATTENUATION
    :summary:
    ```
* - {py:obj}`LASER_LENGTH <space_flight.weapons.laser_cannon.LASER_LENGTH>`
  - ```{autodoc2-docstring} space_flight.weapons.laser_cannon.LASER_LENGTH
    :summary:
    ```
* - {py:obj}`CORE_RADIUS <space_flight.weapons.laser_cannon.CORE_RADIUS>`
  - ```{autodoc2-docstring} space_flight.weapons.laser_cannon.CORE_RADIUS
    :summary:
    ```
* - {py:obj}`GLOW_RADIUS <space_flight.weapons.laser_cannon.GLOW_RADIUS>`
  - ```{autodoc2-docstring} space_flight.weapons.laser_cannon.GLOW_RADIUS
    :summary:
    ```
* - {py:obj}`EMIT_LASER_LIGHT <space_flight.weapons.laser_cannon.EMIT_LASER_LIGHT>`
  - ```{autodoc2-docstring} space_flight.weapons.laser_cannon.EMIT_LASER_LIGHT
    :summary:
    ```
* - {py:obj}`GLOW_TINTS <space_flight.weapons.laser_cannon.GLOW_TINTS>`
  - ```{autodoc2-docstring} space_flight.weapons.laser_cannon.GLOW_TINTS
    :summary:
    ```
* - {py:obj}`_LASER_SHADER <space_flight.weapons.laser_cannon._LASER_SHADER>`
  - ```{autodoc2-docstring} space_flight.weapons.laser_cannon._LASER_SHADER
    :summary:
    ```
````

### API

````{py:data} LASER_SPEED_MPS
:canonical: space_flight.weapons.laser_cannon.LASER_SPEED_MPS
:value: >
   2000.0

```{autodoc2-docstring} space_flight.weapons.laser_cannon.LASER_SPEED_MPS
```

````

````{py:data} SQT2_S
:canonical: space_flight.weapons.laser_cannon.SQT2_S
:value: >
   None

```{autodoc2-docstring} space_flight.weapons.laser_cannon.SQT2_S
```

````

````{py:data} LIGHT_ATTENUATION
:canonical: space_flight.weapons.laser_cannon.LIGHT_ATTENUATION
:value: >
   (1, 0.05, 0)

```{autodoc2-docstring} space_flight.weapons.laser_cannon.LIGHT_ATTENUATION
```

````

````{py:data} LASER_LENGTH
:canonical: space_flight.weapons.laser_cannon.LASER_LENGTH
:value: >
   15.0

```{autodoc2-docstring} space_flight.weapons.laser_cannon.LASER_LENGTH
```

````

````{py:data} CORE_RADIUS
:canonical: space_flight.weapons.laser_cannon.CORE_RADIUS
:value: >
   0.05

```{autodoc2-docstring} space_flight.weapons.laser_cannon.CORE_RADIUS
```

````

````{py:data} GLOW_RADIUS
:canonical: space_flight.weapons.laser_cannon.GLOW_RADIUS
:value: >
   0.2

```{autodoc2-docstring} space_flight.weapons.laser_cannon.GLOW_RADIUS
```

````

````{py:data} EMIT_LASER_LIGHT
:canonical: space_flight.weapons.laser_cannon.EMIT_LASER_LIGHT
:value: >
   False

```{autodoc2-docstring} space_flight.weapons.laser_cannon.EMIT_LASER_LIGHT
```

````

````{py:data} GLOW_TINTS
:canonical: space_flight.weapons.laser_cannon.GLOW_TINTS
:value: >
   None

```{autodoc2-docstring} space_flight.weapons.laser_cannon.GLOW_TINTS
```

````

````{py:data} _LASER_SHADER
:canonical: space_flight.weapons.laser_cannon._LASER_SHADER
:value: >
   None

```{autodoc2-docstring} space_flight.weapons.laser_cannon._LASER_SHADER
```

````

````{py:function} _laser_shader() -> panda3d.core.Shader
:canonical: space_flight.weapons.laser_cannon._laser_shader

```{autodoc2-docstring} space_flight.weapons.laser_cannon._laser_shader
```
````

`````{py:class} LaserCannon(game, parent, parent_node=None)
:canonical: space_flight.weapons.laser_cannon.LaserCannon

Bases: {py:obj}`space_flight.weapons.Weapon`

```{autodoc2-docstring} space_flight.weapons.laser_cannon.LaserCannon
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.weapons.laser_cannon.LaserCannon.__init__
```

````{py:method} fire()
:canonical: space_flight.weapons.laser_cannon.LaserCannon.fire

```{autodoc2-docstring} space_flight.weapons.laser_cannon.LaserCannon.fire
```

````

````{py:method} clean()
:canonical: space_flight.weapons.laser_cannon.LaserCannon.clean

````

`````

`````{py:class} LaserShot(game, origin_ship_id: str, color: panda3d.core.Vec3, power: float, life_time_s: float, light_color: typing.Tuple, speed: numpy.ndarray, start_position, origin_ship=None)
:canonical: space_flight.weapons.laser_cannon.LaserShot

Bases: {py:obj}`space_flight.weapons.Munition`

```{autodoc2-docstring} space_flight.weapons.laser_cannon.LaserShot
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.weapons.laser_cannon.LaserShot.__init__
```

````{py:method} _build_visual(start_position) -> panda3d.core.NodePath
:canonical: space_flight.weapons.laser_cannon.LaserShot._build_visual

````

````{py:method} _attach_collider() -> panda3d.core.NodePath
:canonical: space_flight.weapons.laser_cannon.LaserShot._attach_collider

````

````{py:method} _clean_extra() -> None
:canonical: space_flight.weapons.laser_cannon.LaserShot._clean_extra

````

`````
