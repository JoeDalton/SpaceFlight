# {py:mod}`space_flight.ai.collision_sensor`

```{py:module} space_flight.ai.collision_sensor
```

```{autodoc2-docstring} space_flight.ai.collision_sensor
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`CollisionSensor <space_flight.ai.collision_sensor.CollisionSensor>`
  - ```{autodoc2-docstring} space_flight.ai.collision_sensor.CollisionSensor
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LOGGER <space_flight.ai.collision_sensor.LOGGER>`
  - ```{autodoc2-docstring} space_flight.ai.collision_sensor.LOGGER
    :summary:
    ```
````

### API

````{py:data} LOGGER
:canonical: space_flight.ai.collision_sensor.LOGGER
:value: >
   'getLogger(...)'

```{autodoc2-docstring} space_flight.ai.collision_sensor.LOGGER
```

````

`````{py:class} CollisionSensor(game, ship, collision_reference_distance_m=100.0, ship_distance_1_m=5, radius_1_m=30, ship_distance_2_m=50, radius_2_m=50, ship_distance_3_m=125, radius_3_m=100)
:canonical: space_flight.ai.collision_sensor.CollisionSensor

```{autodoc2-docstring} space_flight.ai.collision_sensor.CollisionSensor
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.ai.collision_sensor.CollisionSensor.__init__
```

````{py:method} compute_repulsion() -> tuple[numpy.ndarray, float]
:canonical: space_flight.ai.collision_sensor.CollisionSensor.compute_repulsion

```{autodoc2-docstring} space_flight.ai.collision_sensor.CollisionSensor.compute_repulsion
```

````

````{py:method} clean()
:canonical: space_flight.ai.collision_sensor.CollisionSensor.clean

```{autodoc2-docstring} space_flight.ai.collision_sensor.CollisionSensor.clean
```

````

````{py:method} __del__()
:canonical: space_flight.ai.collision_sensor.CollisionSensor.__del__

```{autodoc2-docstring} space_flight.ai.collision_sensor.CollisionSensor.__del__
```

````

`````
