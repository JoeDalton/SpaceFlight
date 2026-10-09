# {py:mod}`space_flight.ai.missile.incoming_missile`

```{py:module} space_flight.ai.missile.incoming_missile
```

```{autodoc2-docstring} space_flight.ai.missile.incoming_missile
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`IncomingMissile <space_flight.ai.missile.incoming_missile.IncomingMissile>`
  - ```{autodoc2-docstring} space_flight.ai.missile.incoming_missile.IncomingMissile
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`nearest_incoming <space_flight.ai.missile.incoming_missile.nearest_incoming>`
  - ```{autodoc2-docstring} space_flight.ai.missile.incoming_missile.nearest_incoming
    :summary:
    ```
````

### API

`````{py:class} IncomingMissile
:canonical: space_flight.ai.missile.incoming_missile.IncomingMissile

```{autodoc2-docstring} space_flight.ai.missile.incoming_missile.IncomingMissile
```

````{py:attribute} controller
:canonical: space_flight.ai.missile.incoming_missile.IncomingMissile.controller
:type: space_flight.actors.ordnance.OrdnanceController
:value: >
   None

```{autodoc2-docstring} space_flight.ai.missile.incoming_missile.IncomingMissile.controller
```

````

````{py:attribute} position
:canonical: space_flight.ai.missile.incoming_missile.IncomingMissile.position
:type: numpy.ndarray
:value: >
   None

```{autodoc2-docstring} space_flight.ai.missile.incoming_missile.IncomingMissile.position
```

````

````{py:attribute} distance_m
:canonical: space_flight.ai.missile.incoming_missile.IncomingMissile.distance_m
:type: float
:value: >
   None

```{autodoc2-docstring} space_flight.ai.missile.incoming_missile.IncomingMissile.distance_m
```

````

````{py:attribute} closing_speed_mps
:canonical: space_flight.ai.missile.incoming_missile.IncomingMissile.closing_speed_mps
:type: float
:value: >
   None

```{autodoc2-docstring} space_flight.ai.missile.incoming_missile.IncomingMissile.closing_speed_mps
```

````

````{py:method} between(controller: space_flight.actors.ordnance.OrdnanceController, target: typing.Any) -> space_flight.ai.missile.incoming_missile.IncomingMissile
:canonical: space_flight.ai.missile.incoming_missile.IncomingMissile.between
:classmethod:

```{autodoc2-docstring} space_flight.ai.missile.incoming_missile.IncomingMissile.between
```

````

````{py:property} time_to_impact_s
:canonical: space_flight.ai.missile.incoming_missile.IncomingMissile.time_to_impact_s
:type: float

```{autodoc2-docstring} space_flight.ai.missile.incoming_missile.IncomingMissile.time_to_impact_s
```

````

`````

````{py:function} nearest_incoming(pawn: space_flight.actors.pawn.Pawn) -> space_flight.ai.missile.incoming_missile.IncomingMissile | None
:canonical: space_flight.ai.missile.incoming_missile.nearest_incoming

```{autodoc2-docstring} space_flight.ai.missile.incoming_missile.nearest_incoming
```
````
