# {py:mod}`space_flight.ai.tracking_mount.tracking_mount_navigator`

```{py:module} space_flight.ai.tracking_mount.tracking_mount_navigator
```

```{autodoc2-docstring} space_flight.ai.tracking_mount.tracking_mount_navigator
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`TrackingMountNavigator <space_flight.ai.tracking_mount.tracking_mount_navigator.TrackingMountNavigator>`
  - ```{autodoc2-docstring} space_flight.ai.tracking_mount.tracking_mount_navigator.TrackingMountNavigator
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LOGGER <space_flight.ai.tracking_mount.tracking_mount_navigator.LOGGER>`
  - ```{autodoc2-docstring} space_flight.ai.tracking_mount.tracking_mount_navigator.LOGGER
    :summary:
    ```
* - {py:obj}`NO_DIRECTION <space_flight.ai.tracking_mount.tracking_mount_navigator.NO_DIRECTION>`
  - ```{autodoc2-docstring} space_flight.ai.tracking_mount.tracking_mount_navigator.NO_DIRECTION
    :summary:
    ```
````

### API

````{py:data} LOGGER
:canonical: space_flight.ai.tracking_mount.tracking_mount_navigator.LOGGER
:value: >
   'getLogger(...)'

```{autodoc2-docstring} space_flight.ai.tracking_mount.tracking_mount_navigator.LOGGER
```

````

````{py:data} NO_DIRECTION
:canonical: space_flight.ai.tracking_mount.tracking_mount_navigator.NO_DIRECTION
:value: >
   'zeros(...)'

```{autodoc2-docstring} space_flight.ai.tracking_mount.tracking_mount_navigator.NO_DIRECTION
```

````

`````{py:class} TrackingMountNavigator(game, pawn: space_flight.actors.pawn.Pawn, personality: dict = Personality.TURRET_DEFAULT, debug: bool = False)
:canonical: space_flight.ai.tracking_mount.tracking_mount_navigator.TrackingMountNavigator

Bases: {py:obj}`space_flight.ai.generic.generic_navigator.GenericNavigator`

```{autodoc2-docstring} space_flight.ai.tracking_mount.tracking_mount_navigator.TrackingMountNavigator
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.ai.tracking_mount.tracking_mount_navigator.TrackingMountNavigator.__init__
```

````{py:method} navigate(intent: int, target_dict: dict) -> numpy.ndarray
:canonical: space_flight.ai.tracking_mount.tracking_mount_navigator.TrackingMountNavigator.navigate

```{autodoc2-docstring} space_flight.ai.tracking_mount.tracking_mount_navigator.TrackingMountNavigator.navigate
```

````

````{py:method} engage_target(target_dict: dict = {}) -> numpy.ndarray
:canonical: space_flight.ai.tracking_mount.tracking_mount_navigator.TrackingMountNavigator.engage_target

```{autodoc2-docstring} space_flight.ai.tracking_mount.tracking_mount_navigator.TrackingMountNavigator.engage_target
```

````

````{py:method} _publish_no_engagement()
:canonical: space_flight.ai.tracking_mount.tracking_mount_navigator.TrackingMountNavigator._publish_no_engagement

```{autodoc2-docstring} space_flight.ai.tracking_mount.tracking_mount_navigator.TrackingMountNavigator._publish_no_engagement
```

````

`````
