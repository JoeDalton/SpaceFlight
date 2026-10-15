# {py:mod}`space_flight.weapons.loadout`

```{py:module} space_flight.weapons.loadout
```

```{autodoc2-docstring} space_flight.weapons.loadout
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Loadout <space_flight.weapons.loadout.Loadout>`
  - ```{autodoc2-docstring} space_flight.weapons.loadout.Loadout
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`default_loadout <space_flight.weapons.loadout.default_loadout>`
  - ```{autodoc2-docstring} space_flight.weapons.loadout.default_loadout
    :summary:
    ```
````

### API

`````{py:class} Loadout
:canonical: space_flight.weapons.loadout.Loadout

```{autodoc2-docstring} space_flight.weapons.loadout.Loadout
```

````{py:attribute} lasers
:canonical: space_flight.weapons.loadout.Loadout.lasers
:type: str
:value: >
   None

```{autodoc2-docstring} space_flight.weapons.loadout.Loadout.lasers
```

````

````{py:attribute} ordnance
:canonical: space_flight.weapons.loadout.Loadout.ordnance
:type: collections.abc.Mapping[str, int]
:value: >
   'field(...)'

```{autodoc2-docstring} space_flight.weapons.loadout.Loadout.ordnance
```

````

````{py:method} __post_init__()
:canonical: space_flight.weapons.loadout.Loadout.__post_init__

```{autodoc2-docstring} space_flight.weapons.loadout.Loadout.__post_init__
```

````

````{py:method} from_conf(conf: collections.abc.Mapping) -> space_flight.weapons.loadout.Loadout
:canonical: space_flight.weapons.loadout.Loadout.from_conf
:classmethod:

```{autodoc2-docstring} space_flight.weapons.loadout.Loadout.from_conf
```

````

````{py:method} with_ordnance(**stocks: int) -> space_flight.weapons.loadout.Loadout
:canonical: space_flight.weapons.loadout.Loadout.with_ordnance

```{autodoc2-docstring} space_flight.weapons.loadout.Loadout.with_ordnance
```

````

`````

````{py:function} default_loadout(ship_type: str) -> space_flight.weapons.loadout.Loadout
:canonical: space_flight.weapons.loadout.default_loadout

```{autodoc2-docstring} space_flight.weapons.loadout.default_loadout
```
````
