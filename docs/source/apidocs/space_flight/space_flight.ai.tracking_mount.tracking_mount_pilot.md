# {py:mod}`space_flight.ai.tracking_mount.tracking_mount_pilot`

```{py:module} space_flight.ai.tracking_mount.tracking_mount_pilot
```

```{autodoc2-docstring} space_flight.ai.tracking_mount.tracking_mount_pilot
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`TrackingMountPilot <space_flight.ai.tracking_mount.tracking_mount_pilot.TrackingMountPilot>`
  - ```{autodoc2-docstring} space_flight.ai.tracking_mount.tracking_mount_pilot.TrackingMountPilot
    :summary:
    ```
````

### API

`````{py:class} TrackingMountPilot(game, pawn: space_flight.actors.pawn.Pawn, personality: dict = Personality.TURRET_DEFAULT)
:canonical: space_flight.ai.tracking_mount.tracking_mount_pilot.TrackingMountPilot

Bases: {py:obj}`space_flight.ai.generic.generic_pilot.GenericPilot`

```{autodoc2-docstring} space_flight.ai.tracking_mount.tracking_mount_pilot.TrackingMountPilot
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.ai.tracking_mount.tracking_mount_pilot.TrackingMountPilot.__init__
```

````{py:method} set_on(current_normalized_yaw_rate_command: float = 0.0, current_normalized_pitch_rate_command: float = 0.0)
:canonical: space_flight.ai.tracking_mount.tracking_mount_pilot.TrackingMountPilot.set_on

```{autodoc2-docstring} space_flight.ai.tracking_mount.tracking_mount_pilot.TrackingMountPilot.set_on
```

````

````{py:method} set_off()
:canonical: space_flight.ai.tracking_mount.tracking_mount_pilot.TrackingMountPilot.set_off

```{autodoc2-docstring} space_flight.ai.tracking_mount.tracking_mount_pilot.TrackingMountPilot.set_off
```

````

````{py:method} pilot(target_direction: numpy.ndarray = np.zeros(3))
:canonical: space_flight.ai.tracking_mount.tracking_mount_pilot.TrackingMountPilot.pilot

```{autodoc2-docstring} space_flight.ai.tracking_mount.tracking_mount_pilot.TrackingMountPilot.pilot
```

````

`````
