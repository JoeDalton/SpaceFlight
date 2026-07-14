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
* - {py:obj}`_ACQUIRING <space_flight.ai.auto_aim._ACQUIRING>`
  - ```{autodoc2-docstring} space_flight.ai.auto_aim._ACQUIRING
    :summary:
    ```
* - {py:obj}`_LOCKED <space_flight.ai.auto_aim._LOCKED>`
  - ```{autodoc2-docstring} space_flight.ai.auto_aim._LOCKED
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

````{py:data} _ACQUIRING
:canonical: space_flight.ai.auto_aim._ACQUIRING
:value: >
   'acquiring'

```{autodoc2-docstring} space_flight.ai.auto_aim._ACQUIRING
```

````

````{py:data} _LOCKED
:canonical: space_flight.ai.auto_aim._LOCKED
:value: >
   'locked'

```{autodoc2-docstring} space_flight.ai.auto_aim._LOCKED
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

````{py:method} _reset_acquisition()
:canonical: space_flight.ai.auto_aim.AutoAim._reset_acquisition

```{autodoc2-docstring} space_flight.ai.auto_aim.AutoAim._reset_acquisition
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
