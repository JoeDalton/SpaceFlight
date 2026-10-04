# {py:mod}`space_flight.ai.auto_aim`

```{py:module} space_flight.ai.auto_aim
```

```{autodoc2-docstring} space_flight.ai.auto_aim
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`AutoAim <space_flight.ai.auto_aim.AutoAim>`
  - ```{autodoc2-docstring} space_flight.ai.auto_aim.AutoAim
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LOGGER <space_flight.ai.auto_aim.LOGGER>`
  - ```{autodoc2-docstring} space_flight.ai.auto_aim.LOGGER
    :summary:
    ```
* - {py:obj}`LEAD_SMOOTHING_TIME_S <space_flight.ai.auto_aim.LEAD_SMOOTHING_TIME_S>`
  - ```{autodoc2-docstring} space_flight.ai.auto_aim.LEAD_SMOOTHING_TIME_S
    :summary:
    ```
````

### API

````{py:data} LOGGER
:canonical: space_flight.ai.auto_aim.LOGGER
:value: >
   'getLogger(...)'

```{autodoc2-docstring} space_flight.ai.auto_aim.LOGGER
```

````

````{py:data} LEAD_SMOOTHING_TIME_S
:canonical: space_flight.ai.auto_aim.LEAD_SMOOTHING_TIME_S
:value: >
   0.2

```{autodoc2-docstring} space_flight.ai.auto_aim.LEAD_SMOOTHING_TIME_S
```

````

`````{py:class} AutoAim(game: space_flight.game.flight_state.FlightState, parent: space_flight.actors.fighter.Fighter | space_flight.actors.capital_ship.turret.Turret, target_lock_delay_s: float = 1.0, acquisition_cone_angle_deg: float = 30.0, max_assist_angle_deg: float = 5.0, max_assist_distance_m: float = 1000.0)
:canonical: space_flight.ai.auto_aim.AutoAim

```{autodoc2-docstring} space_flight.ai.auto_aim.AutoAim
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.ai.auto_aim.AutoAim.__init__
```

````{py:method} configure(target_lock_delay_s: float = 1.0, acquisition_cone_angle_deg: float = 30.0, max_assist_angle_deg: float = 5.0, max_assist_distance_m: float = 1000.0)
:canonical: space_flight.ai.auto_aim.AutoAim.configure

```{autodoc2-docstring} space_flight.ai.auto_aim.AutoAim.configure
```

````

````{py:method} _target_kinematics() -> tuple[numpy.ndarray, numpy.ndarray] | None
:canonical: space_flight.ai.auto_aim.AutoAim._target_kinematics

```{autodoc2-docstring} space_flight.ai.auto_aim.AutoAim._target_kinematics
```

````

````{py:method} update_lead()
:canonical: space_flight.ai.auto_aim.AutoAim.update_lead

```{autodoc2-docstring} space_flight.ai.auto_aim.AutoAim.update_lead
```

````

````{py:method} predict_target_position() -> numpy.ndarray | None
:canonical: space_flight.ai.auto_aim.AutoAim.predict_target_position

```{autodoc2-docstring} space_flight.ai.auto_aim.AutoAim.predict_target_position
```

````

````{py:method} compute_shot_speed(start_position: numpy.ndarray) -> numpy.ndarray
:canonical: space_flight.ai.auto_aim.AutoAim.compute_shot_speed

```{autodoc2-docstring} space_flight.ai.auto_aim.AutoAim.compute_shot_speed
```

````

````{py:property} is_target_acquired
:canonical: space_flight.ai.auto_aim.AutoAim.is_target_acquired
:type: bool

```{autodoc2-docstring} space_flight.ai.auto_aim.AutoAim.is_target_acquired
```

````

````{py:property} acquisition_elapsed_time_s
:canonical: space_flight.ai.auto_aim.AutoAim.acquisition_elapsed_time_s
:type: float

```{autodoc2-docstring} space_flight.ai.auto_aim.AutoAim.acquisition_elapsed_time_s
```

````

````{py:method} compute_acquisition()
:canonical: space_flight.ai.auto_aim.AutoAim.compute_acquisition

```{autodoc2-docstring} space_flight.ai.auto_aim.AutoAim.compute_acquisition
```

````

````{py:method} clean()
:canonical: space_flight.ai.auto_aim.AutoAim.clean

```{autodoc2-docstring} space_flight.ai.auto_aim.AutoAim.clean
```

````

````{py:method} __del__()
:canonical: space_flight.ai.auto_aim.AutoAim.__del__

```{autodoc2-docstring} space_flight.ai.auto_aim.AutoAim.__del__
```

````

`````
