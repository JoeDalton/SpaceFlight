# {py:mod}`space_flight.ai.formation`

```{py:module} space_flight.ai.formation
```

```{autodoc2-docstring} space_flight.ai.formation
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Formation <space_flight.ai.formation.Formation>`
  - ```{autodoc2-docstring} space_flight.ai.formation.Formation
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LOGGER <space_flight.ai.formation.LOGGER>`
  - ```{autodoc2-docstring} space_flight.ai.formation.LOGGER
    :summary:
    ```
````

### API

````{py:data} LOGGER
:canonical: space_flight.ai.formation.LOGGER
:value: >
   'getLogger(...)'

```{autodoc2-docstring} space_flight.ai.formation.LOGGER
```

````

`````{py:class} Formation(scale_m: float | None = None, shape: int | None = None)
:canonical: space_flight.ai.formation.Formation

```{autodoc2-docstring} space_flight.ai.formation.Formation
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.ai.formation.Formation.__init__
```

````{py:attribute} FIGHTER_SCALE_M
:canonical: space_flight.ai.formation.Formation.FIGHTER_SCALE_M
:value: >
   30

```{autodoc2-docstring} space_flight.ai.formation.Formation.FIGHTER_SCALE_M
```

````

````{py:attribute} CAPITAL_SHIP_SCALE_M
:canonical: space_flight.ai.formation.Formation.CAPITAL_SHIP_SCALE_M
:value: >
   500

```{autodoc2-docstring} space_flight.ai.formation.Formation.CAPITAL_SHIP_SCALE_M
```

````

````{py:attribute} ARROWHEAD_POSITIONS
:canonical: space_flight.ai.formation.Formation.ARROWHEAD_POSITIONS
:value: >
   None

```{autodoc2-docstring} space_flight.ai.formation.Formation.ARROWHEAD_POSITIONS
```

````

````{py:attribute} DIAMOND_POSITIONS
:canonical: space_flight.ai.formation.Formation.DIAMOND_POSITIONS
:value: >
   None

```{autodoc2-docstring} space_flight.ai.formation.Formation.DIAMOND_POSITIONS
```

````

````{py:attribute} AROUND_DIAMOND_POSITIONS
:canonical: space_flight.ai.formation.Formation.AROUND_DIAMOND_POSITIONS
:value: >
   None

```{autodoc2-docstring} space_flight.ai.formation.Formation.AROUND_DIAMOND_POSITIONS
```

````

````{py:method} get_ship_index(ship_id)
:canonical: space_flight.ai.formation.Formation.get_ship_index

```{autodoc2-docstring} space_flight.ai.formation.Formation.get_ship_index
```

````

````{py:method} add_ship(ship, leader=False)
:canonical: space_flight.ai.formation.Formation.add_ship

```{autodoc2-docstring} space_flight.ai.formation.Formation.add_ship
```

````

````{py:method} remove_ship(ship_id)
:canonical: space_flight.ai.formation.Formation.remove_ship

```{autodoc2-docstring} space_flight.ai.formation.Formation.remove_ship
```

````

`````
