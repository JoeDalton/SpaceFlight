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
````

### API

````{py:data} LOGGER
:canonical: space_flight.ai.auto_aim.LOGGER
:value: >
   'getLogger(...)'

```{autodoc2-docstring} space_flight.ai.auto_aim.LOGGER
```

````

`````{py:class} AutoAim(game, parent, target_lock_delay_s: float = 1.0, acquisition_cone_angle_deg: float = 30.0, max_assist_angle_deg: float = 5.0, max_assist_distance_m: float = 1000.0)
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

````{py:method} compute_shot_speed(start_position: numpy.ndarray)
:canonical: space_flight.ai.auto_aim.AutoAim.compute_shot_speed

```{autodoc2-docstring} space_flight.ai.auto_aim.AutoAim.compute_shot_speed
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
